import asyncio, logging, time, numpy as np, pickle
import websockets
from typing import List, Dict, Any
import random
import os
from fl_main.lib.util.communication_handler import init_fl_server, send, send_websocket, receive 
from fl_main.lib.util.data_struc import convert_LDict_to_Dict
from fl_main.lib.util.helpers import read_config, set_config_file, write_config, get_ip
from fl_main.lib.util.messengers import generate_rotation_message, generate_db_push_message, generate_ack_message, \
     generate_cluster_model_dist_message, generate_agent_participation_confirm_message
from fl_main.lib.util.states import ParticipateMSGLocation, RotationMSGLocation, ModelUpMSGLocation, PollingMSGLocation, \
     ModelType, AgentMsgType
from fl_main.pseudodb.sqlite_db import SQLiteDBHandler
from .state_manager import StateManager
from .aggregation import Aggregator


class Server:
    """
    Server class instance provides interface between the aggregator and DB,
    and the aggregator and an agent (client)
    """

    def __init__(self):
        """
        Instantiation of a Server instance
        """
        # read the config file
        config_file = set_config_file("aggregator")
        self.config = read_config(config_file)

        # functional components
        self.sm = StateManager()
        self.agg = Aggregator(self.sm)  # aggregation functions

        # Config de la DB (la misma que usa PseudoDB)
        db_config_file = set_config_file("db")
        db_config = read_config(db_config_file)

        db_data_path = db_config['db_data_path']
        db_name = db_config['db_name']
        
        # Create DB directory if it doesn't exist
        if not os.path.exists(db_data_path):
            os.makedirs(db_data_path)
        
        # Create models directory if specified
        db_model_path = db_config.get('db_model_path')
        if db_model_path and not os.path.exists(db_model_path):
            os.makedirs(db_model_path)
        
        self.db_file = f'{db_data_path}/{db_name}.db'   # ./db/sample_data.db
        self.dbhandler = SQLiteDBHandler(self.db_file)
        try:
            # Ensure DB schema exists (idempotent)
            self.dbhandler.initialize_DB()
        except Exception as e:
            logging.warning(f"No se pudo inicializar DB desde Server (se intentará usar fichero existente): {e}")

        # Set up FL server's advertised IP address
        # Prefer device_ip if set, otherwise use aggr_ip, fallback to detected host IP
        device_ip = self.config.get('device_ip')
        configured_ip = self.config.get('aggr_ip', '')
        host_ip = get_ip()
        
        if device_ip and device_ip != 'CHANGE_ME':
            # Use explicitly configured device IP
            self.aggr_ip = device_ip
            logging.info(f"Using configured device_ip: {self.aggr_ip}")
        elif configured_ip and configured_ip != host_ip:
            logging.warning(f"Configured aggr_ip {configured_ip} != host IP {host_ip}; using host IP for advertising.")
            self.aggr_ip = host_ip
        else:
            self.aggr_ip = host_ip if not configured_ip else configured_ip

        # port numbers, websocket info
        self.reg_socket = self.config['reg_socket']
        self.recv_socket = self.config['recv_socket']
        self.exch_socket = self.config['exch_socket']

        # Set up DB info to connect with DB
        self.db_ip = self.config['db_ip']
        self.db_socket = self.config['db_socket']

        # thresholds
        self.round_interval = self.config['round_interval']
        self.sm.agg_threshold = self.config['aggregation_threshold']

        self.is_polling = bool(self.config['polling'])
        # Interval between agent reachability checks (seconds) to avoid log spam
        self.agent_wait_interval = int(self.config.get('agent_wait_interval', 10))
        # TTL (in seconds) to consider DB agent entries stale and eligible for cleanup
        self.agent_ttl_seconds = int(self.config.get('agent_ttl_seconds', 300))
        # Pending rotation message (for polling mode)
        self.pending_rotation_msg = None
        # Track which agents have received rotation (set of agent_ids)
        self.rotation_notified_agents = set()
        self._init_round_from_db()
        # Load agent entries from DB into a pending list. Actual connection
        # and adding to StateManager happens in a background coroutine
        # that waits for agents to become reachable.
        self._load_agents_from_db()
        self.db_agents = []

    def _init_round_from_db(self):
        try:
            max_round = self.dbhandler.get_max_round(ModelType.cluster)
        except Exception as e:
            logging.error(f"No se pudo leer MAX(round) desde DB, inicio en 0. Error: {e}")
            self.sm.round = 0
            return

        self.sm.round = max_round
        logging.info(f"Round inicial cargado desde DB: {self.sm.round}")

    def _load_agents_from_db(self):
        """
        Carga agentes desde la tabla 'agents' y los guarda en `self.db_agents`.
        No se añaden todavía a `StateManager` para evitar asumir que están
        conectados; una rutina en background intentará conectar y añadirlos
        cuando estén disponibles.
        """
        try:
            rows = self.dbhandler.get_all_agents()
        except Exception as e:
            logging.error(f"No se pudieron cargar agentes desde DB: {e}")
            return
        if not rows:
            logging.info("No hay agentes registrados en la tabla 'agents'.")
            self.db_agents = []
            return

        # Store rows to be processed by the background waiter
        self.db_agents = rows
        logging.info(f"Agentes cargados desde DB en memoria (pendientes): {self.db_agents}")

    async def _wait_for_agents_routine(self):
        """
        Rutina en background que intenta conectar periódicamente con los
        agentes almacenados en DB. Cuando un agente responde, se añade al
        `StateManager` y se actualiza su `last_seen` en la DB.
        """
        logging.info("Iniciando rutina de espera de agentes desde DB...")
        while True:
            # Cleanup stale agents in DB before attempting connections
            try:
                self.dbhandler.cleanup_old_agents(self.agent_ttl_seconds)
            except Exception as e:
                logging.debug(f"Error ejecutando cleanup_old_agents: {e}")
            # Reload DB list in case new agents were added by registraciones
            try:
                rows = self.dbhandler.get_all_agents()
            except Exception as e:
                logging.error(f"Error leyendo agentes desde DB en waiter: {e}")
                rows = []

            for agent_id, ip, socket in rows:
                # Skip if already in StateManager
                if any(a.get('agent_id') == agent_id for a in self.sm.agent_set):
                    continue

                wsaddr = f'ws://{ip}:{socket}'
                try:
                    # Try to open a short-lived connection to check reachability
                    async with websockets.connect(wsaddr, ping_interval=None) as websocket:
                        logging.info(f'Agente {agent_id} reachable at {ip}:{socket}')
                        # Add to StateManager
                        try:
                            self.sm.add_agent(agent_id, agent_id, ip, socket)
                        except Exception as e:
                            logging.error(f"Error añadiendo agente {agent_id} a StateManager: {e}")

                        # Update DB (upsert) to refresh last_seen
                        try:
                            self.dbhandler.upsert_agent(agent_id, ip, int(socket))
                        except Exception as e:
                            logging.error(f"Error actualizando agente {agent_id} en DB: {e}")
                except Exception:
                    logging.debug(f'Agente {agent_id} no disponible aún en {ip}:{socket}')

            # Sleep some time before next poll; keep light frequency
            await asyncio.sleep(self.agent_wait_interval)
    
    async def register(self, websocket: str, path):
        """
        Receiving the participation message specifying the model structures
        Sending back socket information for future model exchanges.
        Sending back the welcome message as a response.
        :param websocket:
        :param path:
        :return:
        """
        # Receiving participation messages
        msg = await receive(websocket)
        logging.info(f'--- {msg[int(ParticipateMSGLocation.msg_type)]} Message Received ---')
        logging.debug(f'Message: {msg}')

        # Check if it is a simulation run
        es = self._get_exch_socket(msg)

        # Add an agent to the agent list
        agent_name = msg[int(ParticipateMSGLocation.agent_name)]
        agent_id = msg[int(ParticipateMSGLocation.agent_id)]
        addr = msg[int(ParticipateMSGLocation.agent_ip)]

        logging.info(f"register(): participation message from agent_name={agent_name}, agent_id={agent_id}, addr={addr}, exch_socket={es}")

        uid, ues = self.sm.add_agent(agent_name, agent_id, addr, es)
        try:
            ok = self.dbhandler.upsert_agent(agent_id, addr, int(es))
            if ok:
                logging.info(f"register(): agent {agent_id} saved/updated in DB (ip={addr}, socket={es})")
            else:
                logging.warning(f"register(): upsert_agent returned False for {agent_id} (ip={addr}, socket={es})")
        except Exception as e:
            logging.error(f"No se pudo guardar/actualizar agente {agent_id} en DB: {e}")

        # If the weights in the first models should be used as the init models
        # The very first agent connecting to the aggregator decides the shape of the models
        if self.sm.round == 0:
            await self._initialize_fl(msg)

        # If there was at least one global model, just proceed

        # Wait for sending messages
        await asyncio.sleep(0.5)

        # send back 'welcome' message
        await self._send_updated_global_model(websocket, uid, ues)

    def _get_exch_socket(self, msg):
        """
        Get EXCH Socket
        :param msg: Message received
        :return: exch_socket
        """
        if msg[int(ParticipateMSGLocation.sim_flag)]:
            logging.info(f'--- This run is a simulation ---')
            es = msg[int(ParticipateMSGLocation.exch_socket)]
        else:
            es = self.exch_socket
        return es

    async def _initialize_fl(self, msg):
        """
        Initialize FL round
        :param msg: Message received
        :return:
        """
        # Extract values from the message received
        agent_id = msg[int(ParticipateMSGLocation.agent_id)]
        model_id = msg[int(ParticipateMSGLocation.model_id)]
        gene_time = msg[int(ParticipateMSGLocation.gene_time)]
        lmodels = msg[int(ParticipateMSGLocation.lmodels)] # <- Extract local models
        performance = msg[int(ParticipateMSGLocation.meta_data)]
        init_weights_flag = bool(msg[int(ParticipateMSGLocation.init_flag)])

        # Initialize model info
        self.sm.initialize_model_info(lmodels, init_weights_flag)

        # Pushing the local model to DB
        await self._push_local_models(agent_id, model_id, lmodels, gene_time, performance)

        # Recognize this step as one aggregation round
        self.sm.increment_round()

    async def _send_updated_global_model(self, websocket, agent_id, exch_socket):
        """
        Send cluster models to the agent
        :param addr: IP address of agent
        :param es: Port of the agent
        :return:
        """
        # Defensive: cluster_model_ids may be empty if no aggregation has
        # yet occurred. In that case send an empty models dict and empty id
        # so the agent can proceed without crashing the server.
        if not getattr(self.sm, 'cluster_model_ids', None):
            model_id = ''
            cluster_models = {}
            logging.debug(f'_send_updated_global_model: no cluster models yet for agent {agent_id}')
        else:
            model_id = self.sm.cluster_model_ids[-1]
            cluster_models = convert_LDict_to_Dict(self.sm.cluster_models)

        reply = generate_agent_participation_confirm_message(
            self.sm.id, model_id, cluster_models,
            self.sm.round, agent_id, exch_socket, self.recv_socket, self.aggr_ip)
        await send_websocket(reply, websocket)
        logging.info(f'--- Global Models Sent to {agent_id} ---')

    async def receive_msg_from_agent(self, websocket, path):
        """
        Receiving messages from agents for model updates or polling
        :param websocket:
        :param path:
        :return:
        """
        msg = await receive(websocket)

        if msg[int(ModelUpMSGLocation.msg_type)] == AgentMsgType.update:
            await self._process_lmodel_upload(msg)

        elif msg[int(PollingMSGLocation.msg_type)] == AgentMsgType.polling:
            await self._process_polling(msg, websocket)

    async def _process_lmodel_upload(self, msg):
        """
        Process local models uploaded from agents
        :param msg: message received from the agent
        :return:
        """
        lmodels = msg[int(ModelUpMSGLocation.lmodels)]
        agent_id = msg[int(ModelUpMSGLocation.agent_id)]
        model_id = msg[int(ModelUpMSGLocation.model_id)]
        gene_time = msg[int(ModelUpMSGLocation.gene_time)]
        perf_val = msg[int(ModelUpMSGLocation.meta_data)]
        await self._push_local_models(agent_id, model_id, lmodels, gene_time, perf_val)

        logging.info('--- Local Model Received ---')
        logging.debug(f'Local models: {lmodels}')

        # Debug: log model keys and buffer state before/after
        try:
            logging.info(f"_process_lmodel_upload: agent_id={agent_id} model_id={model_id} num_keys={len(list(lmodels.keys()))}")
        except Exception:
            pass

        # Store local models in the buffer
        try:
            self.sm.buffer_local_models(lmodels, participate=False, meta_data=perf_val)
            logging.info(f"_process_lmodel_upload: buffer size now={len(self.sm.local_models_buffer) if hasattr(self.sm, 'local_models_buffer') else 'unknown'}")
        except Exception as e:
            logging.error(f"Error buffering local models from {agent_id}: {e}")

    async def _process_polling(self, msg, websocket):
        """
        Process the polling message from agents
        :param msg: message received from the agent
        :param websocket:
        :return:
        """
        logging.debug(f'--- AgentMsgType.polling ---')
        agent_id = msg[int(PollingMSGLocation.agent_id)]
        
        # Priority 1: Check for pending rotation message
        if self.pending_rotation_msg is not None:
            await send_websocket(self.pending_rotation_msg, websocket)
            logging.info(f'--- Rotation message sent to {agent_id} via polling ---')
            self.rotation_notified_agents.add(agent_id)
            
            # Check if all active agents have been notified
            active_agent_ids = {a['agent_id'] for a in self.sm.agents}
            if active_agent_ids.issubset(self.rotation_notified_agents):
                logging.info(f'All {len(active_agent_ids)} agents notified of rotation. Exiting to yield role.')
                # Persist config changes before exiting
                try:
                    winner_info = self.pending_rotation_msg
                    winner_ip = winner_info[int(RotationMSGLocation.new_aggregator_ip)]
                    winner_sock = winner_info[int(RotationMSGLocation.new_aggregator_reg_socket)]
                    
                    cfg_agent_file = set_config_file('agent')
                    cfg_agent = read_config(cfg_agent_file)
                    cfg_agent['role'] = 'agent'
                    cfg_agent['aggr_ip'] = winner_ip
                    cfg_agent['reg_socket'] = str(winner_sock)
                    write_config(cfg_agent_file, cfg_agent)

                    cfg_aggr_file = set_config_file('aggregator')
                    cfg_aggr = read_config(cfg_aggr_file)
                    cfg_aggr['aggr_ip'] = winner_ip
                    cfg_aggr['reg_socket'] = str(winner_sock)
                    cfg_aggr['role'] = 'agent'
                    write_config(cfg_aggr_file, cfg_aggr)
                    logging.info(f'Config persisted: now agent pointing to {winner_ip}:{winner_sock}')
                except Exception as e:
                    logging.error(f'Failed to persist config after rotation: {e}')
                os._exit(0)
            else:
                remaining = active_agent_ids - self.rotation_notified_agents
                logging.info(f'Rotation sent to {agent_id}. Waiting for {len(remaining)} more agents: {remaining}')
            return
        
        # Priority 2: Check for new global model
        if self.sm.round > int(msg[int(PollingMSGLocation.round)]):
            # Defensive: if no cluster models exist yet, respond with ACK
            # to indicate no model is available rather than crashing.
            if not getattr(self.sm, 'cluster_model_ids', None):
                logging.info('Polling: no cluster models available yet; sending ACK')
                ack_msg = generate_ack_message()
                await send_websocket(ack_msg, websocket)
                return

            model_id = self.sm.cluster_model_ids[-1]
            cluster_models = convert_LDict_to_Dict(self.sm.cluster_models)
            gm_msg = generate_cluster_model_dist_message(self.sm.id, model_id, self.sm.round, cluster_models)
            await send_websocket(gm_msg, websocket)
            logging.info(f'--- Global Models Sent to {agent_id} ---')
        else:
            logging.info(f'--- Polling: Global model is not ready yet ---')
            ack_msg = generate_ack_message()
            await send_websocket(ack_msg, websocket)

    async def model_synthesis_routine(self):
        """
        Periodically check the number of stored models and
         execute synthesis if there are enough based on the agreed threshold
        :return:
        """
        while True:
            # Periodic check (frequency is specified in the JSON config file)
            await asyncio.sleep(self.round_interval)

            if self.sm.ready_for_local_aggregation():  # if it has enough models to aggregate
                logging.info(f'Round {self.sm.round}')
                logging.info(f'Current agents: {self.sm.agent_set}')

                # --- Local aggregation process --- #
                # Local models --> An cluster model #
                # Create a cluster model from local models
                self.agg.aggregate_local_models()

                # Push cluster model to DB
                await self._push_cluster_models()
                # Broadcast rotation and choose next aggregator
                await self._choose_and_broadcast_new_aggregator()

                if self.is_polling == False:
                    await self._send_cluster_models_to_all()

                # increment the aggregation round number
                self.sm.increment_round()

    async def _send_cluster_models_to_all(self):
        """
        Send out cluster models to all agents under this aggregator
        :return:
        """
        # Defensive: if no cluster models yet, nothing to send
        if not getattr(self.sm, 'cluster_model_ids', None):
            logging.info('_send_cluster_models_to_all: no cluster models to distribute')
            return

        model_id = self.sm.cluster_model_ids[-1]
        cluster_models = convert_LDict_to_Dict(self.sm.cluster_models)

        msg = generate_cluster_model_dist_message(self.sm.id, model_id, self.sm.round, cluster_models)
        for agent in self.sm.agent_set:
            try:
                await send(msg, agent['agent_ip'], agent['socket'])
                logging.info(f'--- Global Models Sent to {agent["agent_id"]} ---')
            except Exception as e:
                logging.error(f'Failed to send cluster models to {agent.get("agent_id")} : {e}')

    async def _push_local_models(self, agent_id: str, model_id: str, local_models: Dict[str, np.array],\
                                 gene_time: float, performance: Dict[str, float]) -> List[Any]:
        """
        Pushing a given set of local models to DB
        :param agent_id: str - ID of the agent that created this local model
        :param model_id: str - Model ID passed from the agent
        :param local_models: Dict[str,np.array] - Local models
        :param gene_time: float - the time at which the models were generated
        :param performance: Dict[str,float] - Each entry is a pair of model ID and its performance metric
        :return: Response message (List)
        """
        logging.debug(f'The local models to send: {local_models}')
        return await self._push_models(agent_id, ModelType.local, local_models, model_id, gene_time, performance)

    async def _push_cluster_models(self) -> List[Any]:
        """
        Pushing the cluster models to DB
        :return: Response message (List)
        """
        logging.debug(f'My cluster models to send: {self.sm.cluster_models}')
        model_id = self.sm.cluster_model_ids[-1]  # the latest ID
        models = convert_LDict_to_Dict(self.sm.cluster_models)
        meta_dict = dict({"num_samples" : self.sm.own_cluster_num_samples})
        return await self._push_models(self.sm.id, ModelType.cluster, models, model_id, time.time(), meta_dict)

    async def _choose_and_broadcast_new_aggregator(self):
        # Collect candidate agents (connected)
        agents = list(self.sm.agent_set)
        if not agents:
            rows = self.dbhandler.get_all_agents()
            if not rows:
                logging.info("No agents available for rotation.")
                return
            agents = [{'agent_id': aid, 'agent_ip': ip, 'socket': int(sock)} for (aid, ip, sock) in rows]

        # Generate random scores (including self)
        scores = {a['agent_id']: random.randint(1, 10) for a in agents}
        scores[self.sm.id] = random.randint(1, 10)

        winner, winner_score = max(scores.items(), key=lambda kv: (kv[1], kv[0]))

        # Determine winner address
        if winner == self.sm.id:
            winner_ip = self.aggr_ip
            winner_sock = int(self.reg_socket)
        else:
            winner_ip, winner_sock = None, None
            for agent in agents:
                if agent['agent_id'] == winner:
                    winner_ip = agent['agent_ip']
                    winner_sock = int(agent['socket'])
                    break
        if winner_ip is None:
            logging.error("Rotation aborted: winner IP/socket not found")
            return

        model_id = self.sm.cluster_model_ids[-1] if self.sm.cluster_model_ids else ''
        models = convert_LDict_to_Dict(self.sm.cluster_models)
        rot_msg = generate_rotation_message(winner, winner_ip, winner_sock, model_id, self.sm.round, models, scores)

        # In polling mode, store rotation message for delivery via next poll
        if self.is_polling:
            self.pending_rotation_msg = rot_msg
            self.rotation_notified_agents = set()  # Reset tracking
            logging.info(f'Rotation prepared for polling delivery. Winner: {winner} ({winner_ip}:{winner_sock}) score {winner_score}')
            logging.info(f'Waiting for all {len(self.sm.agents)} agents to poll and receive rotation...')
            # Exit will happen in _process_polling after all agents notified
            return
        else:
            # Push mode: actively send rotation to agents
            async def _send_rotation_direct(msg, ip, socket_num):
                wsaddr = f'ws://{ip}:{socket_num}'
                try:
                    async with websockets.connect(wsaddr, ping_interval=None) as websocket:
                        await websocket.send(pickle.dumps(msg))
                    return True
                except Exception as e:
                    logging.debug(f'Rotation send attempt failed to {ip}:{socket_num} -> {e}')
                    return False

            winner_delivered = False
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                logging.info(f'Rotation broadcast attempt {attempt}/{max_attempts}')
                for agent in agents:
                    delivered = await _send_rotation_direct(rot_msg, agent['agent_ip'], int(agent['socket']))
                    if delivered:
                        logging.info(f'Rotation message delivered to {agent["agent_id"]} at {agent["agent_ip"]}:{agent["socket"]}')
                    else:
                        logging.warning(f'Rotation message NOT delivered to {agent["agent_id"]} at {agent["agent_ip"]}:{agent["socket"]}')
                    if agent['agent_id'] == winner and delivered:
                        winner_delivered = True
                if winner_delivered:
                    break
                await asyncio.sleep(2)

            if not winner_delivered:
                logging.error('Rotation failed: winner did not receive rotation message after retries; keeping current role.')
                return

        # Persist config changes for this node (demote self)
        try:
            cfg_agent_file = set_config_file('agent')
            cfg_agent = read_config(cfg_agent_file)
            cfg_agent['role'] = 'agent'
            write_config(cfg_agent_file, cfg_agent)

            cfg_aggr_file = set_config_file('aggregator')
            cfg_aggr = read_config(cfg_aggr_file)
            cfg_aggr['aggr_ip'] = winner_ip
            cfg_aggr['reg_socket'] = str(winner_sock)
            cfg_aggr['role'] = 'agent'
            write_config(cfg_aggr_file, cfg_aggr)
        except Exception as e:
            logging.error(f'Failed to persist local config change after rotation: {e}')

        logging.info(f'Rotation completed. New aggregator {winner} ({winner_ip}:{winner_sock}) score {winner_score}; exiting to yield role.')
        os._exit(0)


    async def _push_models(self,
                           component_id: str,
                           model_type: ModelType,
                           models: Dict[str, np.array],
                           model_id: str,
                           gene_time: float,
                           performance_dict: Dict[str, float]) -> List[Any]:
        """
        Push a given set of models to DB
        :param component_id:
        :param models: LimitedDict - models
        :param model_type: model type
        :param model_id: str - model ID
        :param gene_time: float - the time at which the models were generated
        :param performance_dict: Dict[str, float] - Each entry is a pair of model id and its performance metric
        :return: Response message (List)
        """
        msg = generate_db_push_message(component_id, self.sm.round, model_type, models, model_id, gene_time, performance_dict)
        resp = await send(msg, self.db_ip, self.db_socket)
        logging.info(f'--- Models pushed to DB: Response {resp} ---')

        return resp


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    s = Server()
    logging.info("--- Aggregator Started ---")

    # Start FL server and background routines (model synthesis + agent waiter)
    # Bind to 0.0.0.0 inside container for reachability, but keep
    # `s.aggr_ip` as the advertised address used in messages.
    bind_ip = '0.0.0.0'
    init_fl_server(s.register,
                   s.receive_msg_from_agent,
                   s.model_synthesis_routine(),
                   bind_ip, s.reg_socket, s.recv_socket,
                   s._wait_for_agents_routine())
