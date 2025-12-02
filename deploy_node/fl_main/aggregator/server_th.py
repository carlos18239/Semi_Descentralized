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
     ModelType, AgentMsgType, DBMsgType
from fl_main.lib.util.metrics_logger import AggregatorMetricsLogger
# Removed SQLiteDBHandler - aggregator uses in-memory state only, PseudoDB handles persistence
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
        # read the config file (use agent config since we're on a node)
        config_file = set_config_file("agent")
        self.config = read_config(config_file)

        # functional components
        self.sm = StateManager()
        self.agg = Aggregator(self.sm)  # aggregation functions

        # Aggregator uses in-memory state only
        # All persistence (models, agent registry) handled by centralized PseudoDB

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
        self.reg_socket = self.config.get('reg_socket', 8765)
        self.recv_socket = self.config.get('recv_socket', self.config.get('exch_port', 4321))
        self.exch_socket = self.config.get('exch_socket', self.config.get('exch_port', 4321))

        # Set up DB info to connect with DB
        self.db_ip = self.config.get('db_ip', '127.0.0.1')
        self.db_socket = self.config.get('db_port', 9017)

        # thresholds
        self.round_interval = self.config.get('round_interval', 5)
        self.sm.agg_threshold = self.config.get('aggregation_threshold', 2)

        self.is_polling = bool(self.config.get('polling', 1))
        # Interval between agent reachability checks (seconds) to avoid log spam
        self.agent_wait_interval = int(self.config.get('agent_wait_interval', 10))
        # TTL (in seconds) to consider DB agent entries stale and eligible for cleanup
        self.agent_ttl_seconds = int(self.config.get('agent_ttl_seconds', 300))
        # Rotation control: minimum rounds before allowing rotation
        self.rotation_min_rounds = int(self.config.get('rotation_min_rounds', 1))
        # Rotation control: rounds between rotations (default 1 round = rotate every round)
        self.rotation_interval = int(self.config.get('rotation_interval', 1))
        logging.info(f'🔄 Intervalo de rotación configurado: cada {self.rotation_interval} ronda(s)')
        # Last round when rotation occurred
        self.last_rotation_round = 0
        # Pending rotation message (for polling mode)
        self.pending_rotation_msg = None
        # Track rotation winner ID
        self.rotation_winner_id = None
        # Track which agents have received rotation (set of agent_ids)
        self.rotation_notified_agents = set()
        # Delay before sending rotation (seconds) - give agents time to sync (1 minuto)
        self.rotation_delay = int(self.config.get('rotation_delay', 10))
        logging.info(f'🔄 Delay de rotación configurado: {self.rotation_delay}s')
        # Aggregation timeout (seconds) - max time to wait for models
        self.aggregation_timeout = int(self.config.get('aggregation_timeout', 30))
        self.aggregation_start_time = None
        logging.info(f'⏱️  Timeout de agregación configurado: {self.aggregation_timeout}s')
        
        # Termination judges
        self.max_rounds = int(self.config.get('max_rounds', 100))
        self.early_stopping_patience = int(self.config.get('early_stopping_patience', 120))
        self.early_stopping_min_delta = float(self.config.get('early_stopping_min_delta', 0.0001))
        self.best_global_recall = 0.0
        self.last_global_recall = None  # Most recent global recall calculated
        self.rounds_without_improvement = 0
        self.current_round_recalls = {}  # agent_id -> recall_value
        self.global_recall_history = []  # history of global recalls
        self.training_terminated = False
        self.termination_reason = None
        self.pending_termination_msg = None
        
        # Initialize metrics logger for aggregator
        self.metrics_logger = AggregatorMetricsLogger(log_dir="./metrics")
        logging.info(f'📊 Aggregator Metrics CSV: {self.metrics_logger.get_csv_path()}')
        
        # Metrics tracking for current round
        self.round_bytes_received = 0
        self.round_bytes_sent = 0
        self.round_models_received = 0
        self.aggregation_start_time = None
        
        # Aggregator starts fresh at round 0
        # Agents register themselves on startup
        self.sm.round = 0
        logging.info(f"Aggregator initialized at round {self.sm.round}")
    
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
        logging.info(f"register(): agent {agent_id} added to memory (ip={addr}, socket={es})")

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
        
        # Track bytes sent for metrics
        try:
            msg_bytes = len(pickle.dumps(reply))
            self.round_bytes_sent += msg_bytes
        except Exception as e:
            logging.warning(f"Could not calculate message bytes: {e}")

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
            
        elif msg[0] == AgentMsgType.recall_upload:
            await self._process_recall_upload(msg)

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
        
        # Track bytes received for metrics
        try:
            model_bytes = len(pickle.dumps(lmodels))
            self.round_bytes_received += model_bytes
            self.round_models_received += 1
        except Exception as e:
            logging.warning(f"Could not calculate model bytes: {e}")

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

    async def _process_recall_upload(self, msg):
        """
        Process recall metric uploaded from agents (Juez 1: Early Stopping)
        :param msg: [AgentMsgType.recall_upload, recall_value, round, agent_id]
        """
        from fl_main.lib.util.states import RecallUpMSGLocation
        
        recall_value = float(msg[int(RecallUpMSGLocation.recall_value)])
        round_no = int(msg[int(RecallUpMSGLocation.round)])
        agent_id = msg[int(RecallUpMSGLocation.agent_id)]
        
        logging.info(f'--- Recall Upload Received: agent={agent_id}, recall={recall_value:.4f}, round={round_no} ---')
        
        # Store recall for this agent in current round
        self.current_round_recalls[agent_id] = recall_value
        
        # Check if we have received recalls from ALL registered agents
        num_agents = len(self.sm.agent_set)
        if len(self.current_round_recalls) >= num_agents and num_agents > 0:
            # Calculate global recall (average)
            global_recall = sum(self.current_round_recalls.values()) / len(self.current_round_recalls)
            self.global_recall_history.append(global_recall)
            self.last_global_recall = global_recall  # Store for metrics logging
            
            logging.info(f'=== GLOBAL RECALL (Round {self.sm.round}): {global_recall:.4f} ===')
            logging.info(f'Individual recalls: {self.current_round_recalls}')
            
            # Check for improvement
            if global_recall > self.best_global_recall + self.early_stopping_min_delta:
                improvement = global_recall - self.best_global_recall
                logging.info(f'✓ Global recall improved by {improvement:.4f} (new best: {global_recall:.4f})')
                self.best_global_recall = global_recall
                self.rounds_without_improvement = 0
            else:
                self.rounds_without_improvement += 1
                logging.info(f'✗ No improvement for {self.rounds_without_improvement} rounds (best: {self.best_global_recall:.4f})')
            
            # Reset current round recalls for next round
            self.current_round_recalls = {}
            
            # Check termination conditions
            self._check_termination_judges()

    def _check_termination_judges(self):
        """
        Check both termination judges:
        Juez 1: Early stopping (no improvement for `early_stopping_patience` rounds)
        Juez 2: Maximum rounds limit
        """
        if self.training_terminated:
            return
        
        # Juez 2: Maximum rounds
        if self.sm.round >= self.max_rounds:
            self.training_terminated = True
            self.termination_reason = f"max_rounds_reached"
            from fl_main.lib.util.messengers import generate_termination_msg
            self.pending_termination_msg = generate_termination_msg(
                reason=f"Reached maximum rounds limit ({self.max_rounds})",
                final_round=self.sm.round,
                final_recall=self.best_global_recall
            )
            logging.warning(f'🛑 TRAINING TERMINATED: Reached max rounds ({self.max_rounds})')
            logging.info(f'Final global recall: {self.best_global_recall:.4f}')
            return
        
        # Juez 1: Early stopping
        if self.rounds_without_improvement >= self.early_stopping_patience:
            self.training_terminated = True
            self.termination_reason = f"early_stopping"
            from fl_main.lib.util.messengers import generate_termination_msg
            self.pending_termination_msg = generate_termination_msg(
                reason=f"No improvement for {self.early_stopping_patience} rounds (patience exhausted)",
                final_round=self.sm.round,
                final_recall=self.best_global_recall
            )
            logging.warning(f'🛑 TRAINING TERMINATED: Early stopping triggered')
            logging.info(f'No improvement for {self.rounds_without_improvement} rounds')
            logging.info(f'Best global recall: {self.best_global_recall:.4f}')
            return

    async def _process_polling(self, msg, websocket):
        """
        Process the polling message from agents
        :param msg: message received from the agent
        :param websocket:
        :return:
        """
        logging.debug(f'--- AgentMsgType.polling ---')
        agent_id = msg[int(PollingMSGLocation.agent_id)]
        
        # Priority 0: Check for pending termination message (highest priority)
        if self.pending_termination_msg is not None:
            await send_websocket(self.pending_termination_msg, websocket)
            logging.info(f'--- Termination message sent to {agent_id} via polling ---')
            return
        
        # Priority 1: Check for pending rotation message
        if self.pending_rotation_msg is not None:
            # Use in-memory agent set (no DB needed)
            all_agent_ids = {a['agent_id'] for a in self.sm.agent_set}
            
            # Safety check: if no agents in memory, cancel rotation
            if len(all_agent_ids) == 0:
                logging.warning("No agents in memory during rotation - cancelling rotation")
                self.pending_rotation_msg = None
                self.rotation_notified_agents = set()
                return
            
            # Send rotation message to this agent if not already notified
            if agent_id not in self.rotation_notified_agents:
                await send_websocket(self.pending_rotation_msg, websocket)
                logging.info(f'🔄 Rotation message sent to {agent_id} via polling')
                self.rotation_notified_agents.add(agent_id)
            else:
                # Agent already got rotation, send again (idempotent)
                await send_websocket(self.pending_rotation_msg, websocket)
                logging.info(f'🔄 Rotation message re-sent to {agent_id} (already notified)')
            
            # Check: Have all current DB agents been notified?
            if all_agent_ids.issubset(self.rotation_notified_agents):
                logging.info(f'All {len(all_agent_ids)} agents notified of rotation.')
                
                winner_info = self.pending_rotation_msg
                winner_id = winner_info[int(RotationMSGLocation.new_aggregator_id)]
                winner_ip = winner_info[int(RotationMSGLocation.new_aggregator_ip)]
                winner_sock = winner_info[int(RotationMSGLocation.new_aggregator_reg_socket)]
                
                # Check if THIS aggregator is the winner
                if self.sm.id == winner_id:
                    logging.info(f'✅ Este agregador GANÓ la rotación. Continúa como agregador.')
                    # Clear rotation state and continue as aggregator
                    self.pending_rotation_msg = None
                    self.rotation_winner_id = None
                    self.rotation_notified_agents = set()
                    return
                else:
                    logging.info(f'🔄 Este agregador PERDIÓ la rotación. Cambiando a rol AGENT.')
                    logging.info(f'   Nuevo agregador: {winner_id[:8]}... en {winner_ip}:{winner_sock}')
                    
                    # IMPORTANTE: Guardar métricas finales antes de salir
                    try:
                        logging.info(f'💾 Guardando métricas finales del agregador...')
                        self.metrics_logger.log_round(
                            round_num=self.sm.round,
                            num_agents=len(self.sm.agent_set),
                            global_recall=self.last_global_recall,
                            aggregation_time=0.0,  # No hay agregación en esta salida
                            models_received=0,
                            bytes_received=0,
                            bytes_sent=0,
                            rounds_without_improvement=self.rounds_without_improvement,
                            best_recall=self.best_global_recall if self.best_global_recall > 0 else None
                        )
                        logging.info(f'✅ Métricas guardadas en {self.metrics_logger.get_csv_path()}')
                    except Exception as e:
                        logging.error(f'⚠️  Error guardando métricas finales: {e}')
                    
                    # Persist config changes before exiting - change to agent
                    try:
                        cfg_agent_file = set_config_file('agent')
                        cfg_agent = read_config(cfg_agent_file)
                        cfg_agent['role'] = 'agent'
                        cfg_agent['aggr_ip'] = winner_ip
                        # NOTE: reg_socket must stay at 8765 (registration port), don't change it
                        write_config(cfg_agent_file, cfg_agent)
                        logging.info(f'✅ Config persistida: ahora agent apuntando a {winner_ip}')
                    except Exception as e:
                        logging.error(f'❌ Error persistiendo config: {e}')
                    
                    logging.info(f'👋 Saliendo del proceso agregador...')
                    os._exit(0)
            else:
                remaining = all_agent_ids - self.rotation_notified_agents
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
            
            # Track bytes sent for metrics
            try:
                msg_bytes = len(pickle.dumps(gm_msg))
                self.round_bytes_sent += msg_bytes
            except Exception as e:
                logging.warning(f"Could not calculate message bytes: {e}")
        else:
            logging.info(f'--- Polling: Global model is not ready yet ---')
            ack_msg = generate_ack_message()
            await send_websocket(ack_msg, websocket)

    async def model_synthesis_routine(self):
        """
        Rutina de agregación con BARRERAS DISTRIBUIDAS para sincronización perfecta
        """
        while True:
            await asyncio.sleep(self.round_interval)
            
            num_agents = len(self.sm.agent_set)
            
            # BARRERA 1: Inicializar barrera de ronda en DB
            if num_agents == 0:
                if int(time.time()) % 10 == 0:  # Log cada 10s
                    logging.info("⏳ Esperando que agentes se registren...")
                continue
            
            # Inicializar barrera en DB para esta ronda
            await self._init_db_barrier(self.sm.round, num_agents, 'waiting_models')
            logging.info(f"🚦 BARRERA 1: Esperando {num_agents} modelos (round {self.sm.round})")
            
            # BARRERA 2: Esperar modelos con timeout
            models_ready = await self._wait_for_models_barrier(num_agents)
            
            if not models_ready:
                logging.error("❌ Timeout esperando modelos - saltando esta ronda")
                await self._reset_db_barrier()
                continue
            
            # FASE AGREGACIÓN: Solo el agregador ejecuta
            logging.info(f"⚙️  AGREGANDO: Round {self.sm.round} con {num_agents} modelos")
            logging.info(f'Current agents: {self.sm.agent_set}')
            
            aggregation_start = time.time()
            self.agg.aggregate_local_models()
            aggregation_time = time.time() - aggregation_start
            
            # Guardar en DB
            await self._update_db_barrier_state('distributing')
            await self._push_cluster_models()
            
            # Incrementar ronda
            self.sm.increment_round()
            
            # Log metrics
            self.metrics_logger.log_round(
                round_num=self.sm.round,
                num_agents=len(self.sm.agent_set),
                global_recall=self.last_global_recall,
                aggregation_time=aggregation_time,
                models_received=self.round_models_received,
                bytes_received=self.round_bytes_received,
                bytes_sent=self.round_bytes_sent,
                rounds_without_improvement=self.rounds_without_improvement,
                best_recall=self.best_global_recall if self.best_global_recall > 0 else None
            )
            
            self.round_bytes_received = 0
            self.round_bytes_sent = 0
            self.round_models_received = 0
            
            # BARRERA 3: Verificar rotación
            rounds_since_last_rotation = self.sm.round - self.last_rotation_round
            should_rotate = (
                self.sm.round >= self.rotation_min_rounds and
                rounds_since_last_rotation >= self.rotation_interval and
                len(self.sm.agent_set) > 0
            )
            
            logging.info(f"🔍 Verificando rotación: ronda={self.sm.round}, última_rotación={self.last_rotation_round}, ")
            logging.info(f"   desde_última={rounds_since_last_rotation}, intervalo={self.rotation_interval}, debe_rotar={should_rotate}")
            
            if should_rotate:
                logging.info(f"🔄 BARRERA 3: INICIANDO ROTACIÓN en ronda {self.sm.round}")
                logging.info(f"   Última rotación: ronda {self.last_rotation_round}")
                logging.info(f"   Agentes activos: {len(self.sm.agent_set)}")
                await self._update_db_barrier_state('rotation')
                logging.info(f"⏳ Esperando {self.rotation_delay}s antes de ejecutar rotación...")
                await asyncio.sleep(self.rotation_delay)
                logging.info(f"🎲 Ejecutando rotación coordinada...")
                await self._coordinated_rotation()
                self.last_rotation_round = self.sm.round
                logging.info(f"✅ Rotación completada. Próxima rotación en ronda {self.sm.round + self.rotation_interval}")
            else:
                logging.debug(f"⏭️  Sin rotación esta ronda (próxima en ronda {self.last_rotation_round + self.rotation_interval})")
                # Resetear barrera para próxima ronda
                await self._reset_db_barrier()
    
    async def _init_db_barrier(self, round_num: int, threshold: int, state: str):
        """Inicializa barrera en DB"""
        msg = [DBMsgType.init_barrier.value, round_num, threshold, self.sm.id, state]
        await send(msg, self.db_ip, self.db_socket)
    
    async def _update_db_barrier_state(self, state: str):
        """Actualiza estado de la barrera en DB"""
        msg = [DBMsgType.update_barrier_state.value, state]
        await send(msg, self.db_ip, self.db_socket)
    
    async def _reset_db_barrier(self):
        """Resetea agentes listos en la barrera"""
        msg = [DBMsgType.reset_barrier.value]
        await send(msg, self.db_ip, self.db_socket)
    
    async def _wait_for_models_barrier(self, num_expected: int) -> bool:
        """
        Espera hasta que todos los agentes envíen sus modelos (barrera distribuida)
        """
        timeout = self.aggregation_timeout
        start_time = time.time()
        last_log_time = start_time
        
        while True:
            num_models = len(self.sm.local_model_buffers[self.sm.mnames[0]]) if self.sm.mnames else 0
            
            # Verificar si todos los modelos llegaron
            if num_models >= num_expected:
                elapsed = time.time() - start_time
                logging.info(f"✅ BARRERA COMPLETADA: {num_models}/{num_expected} modelos en {elapsed:.1f}s")
                return True
            
            # Verificar timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logging.warning(f"⏱️  TIMEOUT: Solo {num_models}/{num_expected} modelos en {timeout}s")
                # Proceder con agregación parcial si hay al menos 1 modelo
                return num_models > 0
            
            # Log progreso cada 10s
            if time.time() - last_log_time >= 10:
                remaining = timeout - elapsed
                logging.info(f"⏳ [{int(elapsed)}s] Modelos: {num_models}/{num_expected} (quedan {int(remaining)}s)")
                last_log_time = time.time()
            
            await asyncio.sleep(2)
    
    async def _coordinated_rotation(self):
        """
        Rotación coordinada con barrera distribuida
        """
        logging.info(f"🎯 _coordinated_rotation: INICIO")
        agents = list(self.sm.agent_set)
        if not agents:
            logging.warning("⚠️  No hay agentes para rotación - abortando")
            return
        
        logging.info(f"👥 Agentes participantes en elección: {len(agents)}")
        logging.info(f"📋 IDs: {[a['agent_id'][:8] + '...' for a in agents]}")
        
        # Elegir nuevo agregador
        scores = {a['agent_id']: random.randint(1, 100) for a in agents}
        scores[self.sm.id] = random.randint(1, 100)
        logging.info(f"🎲 Scores generados: {[(k[:8] + '...', v) for k, v in scores.items()]}")
        
        winner_id, winner_score = max(scores.items(), key=lambda x: (x[1], x[0]))
        logging.info(f"🏆 Ganador: {winner_id[:8]}... con score {winner_score}")
        
        # Determinar IP del ganador
        if winner_id == self.sm.id:
            winner_ip = self.aggr_ip
            winner_sock = int(self.reg_socket)
        else:
            winner_ip, winner_sock = None, None
            for agent in agents:
                if agent['agent_id'] == winner_id:
                    winner_ip = agent['agent_ip']
                    winner_sock = int(agent['socket'])
                    break
        
        if not winner_ip:
            logging.error("❌ Rotación abortada: IP del ganador no encontrada")
            return
        
        logging.info(f"✅ Nuevo agregador determinado: {winner_id[:8]}... en {winner_ip}:{winner_sock} (score: {winner_score})")
        
        # Preparar mensaje de rotación
        model_id = self.sm.cluster_model_ids[-1] if self.sm.cluster_model_ids else ''
        models = convert_LDict_to_Dict(self.sm.cluster_models)
        rot_msg = generate_rotation_message(winner_id, winner_ip, winner_sock, model_id, self.sm.round, models, scores)
        
        logging.info(f"📦 Mensaje de rotación creado (model_id: {model_id[:16] if model_id else 'N/A'}...)")
        
        if self.is_polling:
            # Modo polling: guardar mensaje para entrega vía polling
            self.pending_rotation_msg = rot_msg
            self.rotation_winner_id = winner_id
            self.rotation_notified_agents = set()
            logging.info(f"📋 ✅ Mensaje de rotación guardado para entrega vía POLLING")
            logging.info(f"⏳ Esperando que {len(agents)} agentes lo reciban via polling...")
            # El exit ocurrirá en _process_polling después de que todos confirmen
        else:
            # Modo push: enviar directamente (no usado típicamente)
            logging.warning(f"⚠️  Modo push detectado - enviando rotación directamente")
            os._exit(0)

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

    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging to both file and console
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # File handler - persistent log
    file_handler = logging.FileHandler('logs/aggregator.log')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logging.info("=== AGGREGATOR SERVER STARTING ===")

    try:
        s = Server()
        logging.info("--- Aggregator Started ---")

        # Start FL server and background routine (model synthesis only)
        # Bind to 0.0.0.0 inside container for reachability, but keep
        # `s.aggr_ip` as the advertised address used in messages.
        bind_ip = '0.0.0.0'
        init_fl_server(s.register,
                       s.receive_msg_from_agent,
                       s.model_synthesis_routine(),
                       bind_ip, s.reg_socket, s.recv_socket)
    except Exception as e:
        logging.error(f"=== AGGREGATOR CRASHED ===")
        logging.error(f"Exception type: {type(e).__name__}")
        logging.error(f"Exception message: {str(e)}")
        import traceback
        logging.error(f"Traceback:\n{traceback.format_exc()}")
        raise
