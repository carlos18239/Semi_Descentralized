import asyncio
import time
import logging
import sys
import os
from typing import Dict, Any
from threading import Thread
import subprocess, sys
import shutil

from fl_main.lib.util.communication_handler import init_client_server, send, receive
from fl_main.lib.util.helpers import read_config, init_loop, \
     save_model_file, load_model_file, read_state, write_state, generate_id, \
     set_config_file, get_ip, compatible_data_dict_read, generate_model_id, \
     create_data_dict_from_models, create_meta_data_dict
from fl_main.lib.util.states import IDPrefix, ClientState, AggMsgType, ParticipateConfirmationMSGLocation, GMDistributionMsgLocation, PollingMSGLocation, RotationMSGLocation
from fl_main.lib.util.messengers import generate_lmodel_update_message, generate_agent_participation_message, generate_polling_message
from fl_main.lib.util.helpers import write_config,set_config_file,read_config
class Client:
    """
    Client class instance provides the communication interface
    between Agent's ML logic and an aggregator
    """

    def __init__(self):

        time.sleep(2)
        logging.info(f"--- Agent initialized ---")

        self.agent_name = 'default_agent'

        # Unique ID in the system
        self.id = generate_id()

        # Getting IP Address of the agent itself
        self.agent_ip = get_ip()

        # Check command line argvs
        self.simulation_flag = False
        if len(sys.argv) > 1:
            # if sys.argv[1] == '1', it's in simulation mode
            self.simulation_flag = bool(int(sys.argv[1]))

        # Read config
        config_file = set_config_file("agent")
        self.config = read_config(config_file)
        
        # Read DB config from agent config (db_ip and db_port are in config_agent.json)
        self.db_ip = self.config.get('db_ip', '127.0.0.1')
        self.db_socket = self.config.get('db_port', 9017)

        # Comm. info to join the FL platform
        self.aggr_ip = self.config['aggr_ip']
        self.reg_socket = self.config['reg_socket']
        self.msend_socket = 0  # later updated based on welcome message
        self.exch_socket = 0 
        
        # Log the aggregator IP for debugging
        logging.info(f"📡 Configured aggregator IP: '{self.aggr_ip}'")
        logging.info(f"🔌 Configured registration socket: {self.reg_socket}")
        logging.info(f"🗄️  Database server: {self.db_ip}:{self.db_socket}")

        if self.simulation_flag:
            # if it's simulation, use the manual socket number and agent name
            self.exch_socket = int(sys.argv[2])
            self.agent_name = sys.argv[3]

        # Local file location        
        self.model_path = f'{self.config["model_path"]}/{self.agent_name}'

        # if there is no directory to save models
        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)

        # Ensure local model files exist; if not, try to copy defaults from
        # `models/default_agent` in the repository so agents can start in tests.
        try:
            lm_path = os.path.join(self.model_path, self.lmfile)
            gm_path = os.path.join(self.model_path, self.gmfile)
            if not os.path.exists(lm_path) or not os.path.exists(gm_path):
                repo_default_dir = os.path.join(os.getcwd(), 'models', 'default_agent')
                src_lm = os.path.join(repo_default_dir, self.lmfile)
                src_gm = os.path.join(repo_default_dir, self.gmfile)
                if os.path.exists(src_lm):
                    try:
                        shutil.copyfile(src_lm, lm_path)
                    except Exception:
                        pass
                if os.path.exists(src_gm):
                    try:
                        shutil.copyfile(src_gm, gm_path)
                    except Exception:
                        pass
        except Exception:
            # Non-fatal; agent can still try to proceed and will fail later if truly missing
            pass

        self.lmfile = self.config['local_model_file_name']
        self.gmfile = self.config['global_model_file_name']
        self.statefile = self.config['state_file_name']

        # Aggregation round - later updated by the info from the aggregator
        self.round = 0
        
        # Initialization
        self.init_weights_flag = bool(self.config['init_weights_flag'])

        # Polling Method
        self.is_polling = bool(self.config['polling'])
        
        # Counter for consecutive polling failures (to detect dead aggregator)
        self.polling_failures = 0
        self.max_polling_failures = 6  # After 6 failures (~30s), restart to find new aggregator

    async def participate(self):
        """
        Send the first message to join an aggregator and
        Receive state/comm. info from the aggregator.
        
        NEW PROTOCOL:
        1. Register in DB with random score (1-100)
        2. Wait for registration grace period (for other agents)
        3. Query DB for existing aggregator
        4. If no aggregator exists, trigger election via DB (using ALL registered agents)
        5. Connect to the elected aggregator
        :return:
        """
        # Step 1: Register in DB
        my_id, my_score = await self._register_in_db()
        
        # Step 2: Wait for registration grace period to allow other agents to register
        grace_period = self.config.get('registration_grace_period', 30)  # 30s por defecto
        expected_agents = self.config.get('expected_num_agents', 0)
        
        logging.info(f'⏳ Esperando {grace_period}s para que otros agentes se registren...')
        if expected_agents > 0:
            logging.info(f'   📊 Agentes esperados: {expected_agents}')
        else:
            logging.info(f'   📊 Sin límite de agentes (modo dinámico)')
        
        # Wait in intervals and check DB for registered agents
        check_interval = 3  # Revisar cada 3 segundos
        elapsed = 0
        while elapsed < grace_period:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            
            # Query DB for current registered agents count
            try:
                from fl_main.lib.util.states import DBMsgType
                msg = [DBMsgType.get_agents_count.value]
                resp = await send(msg, self.db_ip, self.db_socket)
                if resp and len(resp) > 1:
                    current_count = resp[1]
                    remaining = grace_period - elapsed
                    logging.info(f'   ⏱️  [{elapsed}s/{grace_period}s] {current_count} agentes registrados (quedan {remaining}s)')
                    
                    # If we reached expected count, can proceed early
                    if expected_agents > 0 and current_count >= expected_agents:
                        logging.info(f'   ✅ ¡Todos los {expected_agents} agentes esperados se registraron!')
                        logging.info(f'   🚀 Continuando antes de tiempo (ahorro: {remaining}s)')
                        break
            except Exception as e:
                logging.warning(f'   ⚠️  No se pudo consultar cantidad de agentes: {e}')
                # Continuar esperando aunque falle la consulta
        
        logging.info(f'✅ Periodo de registro completado ({elapsed}s)')
        
        # Step 2: Discover aggregator from DB (NO verify_alive - trust connection retries)
        agg_ip, agg_socket = await self._discover_aggregator_from_db(verify_alive=False)
        
        # Step 3: If no aggregator, trigger election with ALL registered agents
        if not agg_ip:
            logging.info('⚡ No existe agregador - iniciando elección democrática...')
            
            # Query DB for ALL registered agents to ensure fair election
            all_agents = await self._get_all_registered_agents_from_db()
            election_min = self.config.get('election_min_agents', 1)
            
            if len(all_agents) < election_min:
                logging.warning(f'⚠️  Solo {len(all_agents)} agentes registrados (mínimo: {election_min})')
                logging.info(f'⏳ Esperando 3s adicionales para más agentes...')
                await asyncio.sleep(3)
                all_agents = await self._get_all_registered_agents_from_db()
            
            if len(all_agents) == 0:
                logging.error('❌ No hay agentes registrados para elegir agregador')
                return
            
            logging.info(f'🗳️  Elección con {len(all_agents)} agentes registrados')
            logging.info(f'📋 Candidatos: {list(all_agents.keys())}')
            logging.info(f'🎲 Scores: {all_agents}')
            
            # Collect scores from ALL agents (use existing scores from registration)
            scores = all_agents  # Dict[agent_id: score]
            election_result = await self._elect_aggregator_via_db(scores)
            
            # IMPORTANT: After election, re-query DB to get the ACTUAL winner
            # This handles race conditions where multiple agents request election
            # NOTE: verify_alive=False because winner hasn't started aggregator yet
            await asyncio.sleep(2)  # Wait for election to settle
            actual_agg_ip, actual_agg_socket = await self._discover_aggregator_from_db(verify_alive=False)
            
            if actual_agg_ip:
                # Check if I'm actually the winner by comparing my IP
                device_ip = self.config.get('device_ip', self.agent_ip)
                if device_ip == 'CHANGE_ME':
                    device_ip = self.agent_ip
                    
                if actual_agg_ip == device_ip:
                    logging.info(f'🏆 Confirmed: I am the elected aggregator!')
                    self._promote_to_aggregator()
                    os._exit(0)  # Exit to restart as aggregator
                else:
                    logging.info(f'📊 Another node won the election: {actual_agg_ip}:{actual_agg_socket}')
                    agg_ip, agg_socket = actual_agg_ip, actual_agg_socket
                    # Wait longer for winner to start aggregator (10 seconds)
                    logging.info(f'⏳ Waiting 10s for aggregator {agg_ip} to start...')
                    await asyncio.sleep(10)
            else:
                logging.error('❌ Election failed - cannot proceed')
                return
        
        # Update connection info
        self.aggr_ip = agg_ip
        self.reg_socket = int(agg_socket)
        
        # Step 4: Connect to aggregator (existing logic)
        # Read the local models to tell the structure to the aggregator
        # (not necessarily trained)
        data_dict, performance_dict = load_model_file(self.model_path, self.lmfile)

        _, gene_time, models, model_id = compatible_data_dict_read(data_dict)

        logging.debug(models)

        msg = generate_agent_participation_message(
                self.agent_name, self.id, model_id, models, self.init_weights_flag, self.simulation_flag,
                self.exch_socket, gene_time, performance_dict, self.agent_ip)
        # Send participation message with retries if aggregator doesn't reply
        # Aggressively retry registration since aggregator may be still
        # starting. Increase retries to tolerate startup races in compose.
        max_retries = 12
        resp = None
        for attempt in range(1, max_retries + 1):
            resp = await send(msg, self.aggr_ip, self.reg_socket)
            logging.debug(msg)
            logging.info(f"--- Init Response (attempt {attempt}): {resp} ---")
            if resp is None:
                # Backoff before retrying (increasing delay)
                await asyncio.sleep(min(1 * attempt, 10))
                continue
            break

        if resp is None:
            logging.warning('No response from aggregator after retries')
            sys.stdout.flush()
            
            # The aggregator in DB is not responding - it might be dead
            # Clear it and trigger new election
            logging.info(f'🔄 Aggregator {self.aggr_ip}:{self.reg_socket} not responding - triggering re-election...')
            await self._clear_aggregator_from_db()
            
            # Check if I should become the aggregator
            device_ip = self.config.get('device_ip', self.agent_ip)
            if device_ip == 'CHANGE_ME':
                device_ip = self.agent_ip
            
            # Re-register with a new score and trigger election
            my_id, my_score = await self._register_in_db()
            scores = {my_id: my_score}
            await self._elect_aggregator_via_db(scores)
            
            # Check who won
            await asyncio.sleep(2)
            new_agg_ip, new_agg_socket = await self._discover_aggregator_from_db(verify_alive=False)
            
            if new_agg_ip == device_ip:
                logging.info('🏆 I won the re-election - promoting to aggregator!')
                self._promote_to_aggregator()
                os._exit(0)
            else:
                logging.info(f'📊 New aggregator elected: {new_agg_ip}:{new_agg_socket}')
                # Wait for new aggregator to start, then retry participate
                await asyncio.sleep(10)
                self.aggr_ip = new_agg_ip
                self.reg_socket = int(new_agg_socket)
                # Recursive retry (limited by role_supervisor restarts)
                return await self.participate()

        # Parse the response message (guard against unexpected format)
        try:
            self.round = resp[int(ParticipateConfirmationMSGLocation.round)]
            self.exch_socket = resp[int(ParticipateConfirmationMSGLocation.exch_socket)]
            self.msend_socket = resp[int(ParticipateConfirmationMSGLocation.recv_socket)]
            self.id = resp[int(ParticipateConfirmationMSGLocation.agent_id)]

            # Receiving the welcome message
            logging.info(f'--- {resp[int(ParticipateConfirmationMSGLocation.msg_type)]} Message Received ---')

            self.save_model_from_message(resp, ParticipateConfirmationMSGLocation)
        except Exception as e:
            logging.error(f'Unexpected participate() response format: {e} | resp={resp}')
            return

        # If running in simulation mode, immediately prepare/send local model
        # so aggregator receives local updates for testing rotation.
        if self.simulation_flag:
            try:
                logging.info('Simulation mode: scheduling initial local model send')
                # send initial models (this writes local model file and sets state)
                self.send_initial_model(models, num_samples=1, perf_val=0.0)
            except Exception as e:
                logging.error(f'Failed to schedule initial model send: {e}')

    async def model_exchange_routine(self):
        """
        Check the progress of training and send the updated models
        once the training is done
        :return:
        """
        while True:
            # Periodically check the state
            await asyncio.sleep(5)
            state = read_state(self.model_path, self.statefile)

            if state == ClientState.sending: 
                # Ready to send the local model
                await self.send_models()

            elif state == ClientState.waiting_gm:
                # Waiting for global models
                if self.is_polling == True:
                    await self.process_polling()
                else:
                    # Do nothing
                    logging.info(f'--- Waiting for Global Model ---')

            elif state == ClientState.training:
                # Local model is being trained, do nothing
                logging.info(f'--- Training is happening ---')

            elif state == ClientState.gm_ready:
                # Global model has been received, do nothing
                logging.info(f'--- Global Model is ready ---')

            else:
                logging.error(f'--- State Not Defined ---')
    

    # Push or Polling
    async def wait_models(self, websocket, path):
        """
        Waiting for cluster models from the aggregator
        :param websocket:
        :return:
        """
        gm_msg = await receive(websocket)
        logging.info(f'--- Global Model Received ---')

        logging.debug(f'Models: {gm_msg}')

        # If it's a rotation message
        try:
            msg_type = gm_msg[int(0)]
        except Exception:
            msg_type = None

        if msg_type == AggMsgType.rotation:
            winner = gm_msg[int(RotationMSGLocation.new_aggregator_id)]
            winner_ip = gm_msg[int(RotationMSGLocation.new_aggregator_ip)]
            winner_sock = gm_msg[int(RotationMSGLocation.new_aggregator_reg_socket)]
            model_id = gm_msg[int(RotationMSGLocation.model_id)]
            models = gm_msg[int(RotationMSGLocation.models)]
            scores = gm_msg[int(RotationMSGLocation.rand_scores)]

            logging.info(f'Received rotation: winner={winner} at {winner_ip}:{winner_sock}')

            # IMPORTANT: Compare by IP address, not by ID (IDs can be reassigned)
            device_ip = self.config.get('device_ip', self.agent_ip)
            if device_ip == 'CHANGE_ME':
                device_ip = self.agent_ip
            
            i_am_winner = (device_ip == winner_ip)
            logging.info(f'DEBUG: My IP is {device_ip}, winner IP is {winner_ip}, I am winner? {i_am_winner}')

            # Persist configs: default set everyone to agent; aggregator will set itself next
            try:
                cfg_agent_file = set_config_file('agent')
                cfg_agent = read_config(cfg_agent_file)
                cfg_agent['role'] = 'agent'
                cfg_agent['aggr_ip'] = winner_ip
                # NOTE: reg_socket must stay at 8765 (registration port), don't change it
                write_config(cfg_agent_file, cfg_agent)

                # Skip aggregator config file - we don't use it anymore
            except Exception as e:
                logging.error(f'Failed to persist rotation config: {e}')

            # If this agent is chosen (compare by IP), promote it
            if i_am_winner:
                logging.info('🏆 This agent has been selected as new aggregator. Promoting...')
                try:
                    # set role flags
                    cfg_agent = read_config(set_config_file('agent'))
                    cfg_agent['role'] = 'aggregator'
                    cfg_agent['aggr_ip'] = device_ip
                    write_config(set_config_file('agent'), cfg_agent)
                except Exception:
                    pass

                # Start server_th
                subprocess.Popen(["python3", "-m", "fl_main.aggregator.server_th"])
                # exit agent process to avoid double roles
                os._exit(0)
            else:
                logging.info('📡 Stayed as agent after rotation.')
            return


        self.save_model_from_message(gm_msg, GMDistributionMsgLocation)
    
    async def process_polling(self):
        logging.info(f'--- Polling to see if there is any update ---')

        msg = generate_polling_message(self.round, self.id)
        resp = await send(msg, self.aggr_ip, self.msend_socket)
        # `send` can return None on connection failure or when no reply is sent.
        if resp is None:
            self.polling_failures += 1
            logging.warning(f'No response received from aggregator during polling (failure {self.polling_failures}/{self.max_polling_failures})')
            
            # After too many failures, aggregator is likely dead - restart to find new one
            if self.polling_failures >= self.max_polling_failures:
                logging.error(f'🔴 Aggregator {self.aggr_ip} appears dead after {self.polling_failures} failures')
                logging.info(f'🔄 Restarting to discover/elect new aggregator...')
                # Exit to let role_supervisor restart us
                os._exit(1)
            return
        
        # Reset failure counter on successful response
        self.polling_failures = 0

        # Defensive check: ensure message has expected shape
        try:
            msg_type = resp[int(0)]
            
            # Priority 0: Check for termination message (highest priority)
            if msg_type == AggMsgType.termination:
                from fl_main.lib.util.states import TerminationMsgLocation
                reason = resp[int(TerminationMsgLocation.reason)]
                final_round = resp[int(TerminationMsgLocation.final_round)]
                final_recall = resp[int(TerminationMsgLocation.final_recall)]
                
                logging.warning(f'🛑 TRAINING TERMINATED by aggregator')
                logging.info(f'Reason: {reason}')
                logging.info(f'Final round: {final_round}')
                logging.info(f'Final global recall: {final_recall:.4f}')
                
                # Exit gracefully
                logging.info('Agent exiting due to training termination...')
                os._exit(0)
            
            # Priority 1: Check for rotation message
            elif msg_type == AggMsgType.rotation:
                winner = resp[int(RotationMSGLocation.new_aggregator_id)]
                winner_ip = resp[int(RotationMSGLocation.new_aggregator_ip)]
                winner_sock = resp[int(RotationMSGLocation.new_aggregator_reg_socket)]
                
                logging.info(f'Received rotation via polling: winner={winner} at {winner_ip}:{winner_sock}')
                logging.info(f'DEBUG: My ID is {self.id}, winner ID is {winner}')
                logging.info(f'DEBUG: IDs match? {self.id == winner}')
                
                # IMPORTANT: Compare by IP address, not by ID (IDs can be reassigned)
                device_ip = self.config.get('device_ip', self.agent_ip)
                if device_ip == 'CHANGE_ME':
                    device_ip = self.agent_ip
                
                i_am_winner = (device_ip == winner_ip)
                logging.info(f'DEBUG: My IP is {device_ip}, winner IP is {winner_ip}, I am winner? {i_am_winner}')
                
                # Update configs
                try:
                    cfg_agent_file = set_config_file('agent')
                    cfg_agent = read_config(cfg_agent_file)
                    
                    # If this agent is the winner (compare by IP, not ID)
                    if i_am_winner:
                        # Winner becomes aggregator
                        cfg_agent['role'] = 'aggregator'
                        cfg_agent['aggr_ip'] = device_ip
                        logging.info(f'🏆 This agent has been selected as new aggregator via polling. Promoting with IP {device_ip}...')
                    else:
                        # Loser stays as agent, updates to point to winner
                        cfg_agent['role'] = 'agent'
                        cfg_agent['aggr_ip'] = winner_ip
                        # NOTE: reg_socket must stay at 8765 (registration port), don't change it
                        logging.info(f'📡 Updated aggregator address to {winner_ip}')
                    
                    write_config(cfg_agent_file, cfg_agent)
                    
                    # Skip aggregator config file - we don't use it anymore
                except Exception as e:
                    logging.error(f'Failed to persist rotation config: {e}')
                
                # If promoted, exit to let supervisor restart as aggregator
                if i_am_winner:
                    logging.info('Exiting to restart as aggregator...')
                    os._exit(0)
                else:
                    # Update local aggregator reference
                    self.aggr_ip = winner_ip
                    # NOTE: Don't change reg_socket - it must stay at 8765
                    logging.info(f'This agent lost rotation. Exiting to re-register with new aggregator at {winner_ip}')
                    # Exit to restart and re-register with new aggregator
                    os._exit(0)
                return
            
            elif msg_type == AggMsgType.update:
                logging.info(f'--- Global Model Received ---')
                self.save_model_from_message(resp, GMDistributionMsgLocation)
            else: # AggMsgType is "ack"
                logging.info(f'--- Global Model is NOT ready (ACK) ---')
        except Exception as e:
            logging.error(f'Unexpected polling response format: {e} | resp={resp}')


    # Starting FL client functions
    def start_fl_client(self):
        """
        Starting FL client core functions
        """
        self.register_client()
        if self.is_polling == False:
            self.start_wait_model_server()
        self.start_model_exchange_server()

    def register_client(self):
        """
        Register an agent in aggregator
        """
        time.sleep(0.5)
        asyncio.get_event_loop().run_until_complete(self.participate())
    
    def start_wait_model_server(self):
        """
        Start a thread for waiting for global models
        """
        time.sleep(0.5)
        th = Thread(target = init_client_server, args=[self.wait_models, self.agent_ip, self.exch_socket])
        th.start()

    def start_model_exchange_server(self):
        """
        Start a thread for model exchange routine
        """
        time.sleep(0.5)
        self.agent_running = True
        th = Thread(target = init_loop, args=[self.model_exchange_routine()])
        th.start()

    # Save models from message
    def save_model_from_message(self, msg, MSG_LOC):

        # pass (model_id, models) to an app
        data_dict = create_data_dict_from_models(msg[int(MSG_LOC.model_id)], 
                        msg[int(MSG_LOC.global_models)], msg[int(MSG_LOC.aggregator_id)])
        self.round = msg[int(MSG_LOC.round)]

        # Save the received cluster global models to the local file
        save_model_file(data_dict, self.model_path, self.gmfile)
        logging.info(f'--- Global Models Saved ---')
        
        # State transition to gm_ready
        self.tran_state(ClientState.gm_ready)
        logging.info(f'--- Client State is now gm_ready ---')
    

    # Read and change the client state
    def read_state(self) -> ClientState:
        """
        Read the value in the state file specified by model path
        :return: ClientState - A state indicated in the file
        """
        return read_state(self.model_path, self.statefile)

    def tran_state(self, state: ClientState):
        """
        Change the state of the agent
        State is indicated in local file 'state'
        :param state: ClientState
        :return:
        """
        write_state(self.model_path, self.statefile, state)

    # Sending models
    async def send_models(self):
        # Read the models from the local file
        data_dict, performance_dict = load_model_file(self.model_path, self.lmfile)
        _, _, models, model_id = compatible_data_dict_read(data_dict)
        msg = generate_lmodel_update_message(self.id, model_id, models, performance_dict)

        logging.debug(f'Trained Models: {msg}')

        await send(msg, self.aggr_ip, self.msend_socket)
        logging.info('--- Local Models Sent ---')

        # State transition to waiting_gm
        self.tran_state(ClientState.waiting_gm)
        logging.info(f'--- Client State is now waiting_gm ---')

    def send_initial_model(self, initial_models, num_samples=1, perf_val=0.0):
        self.setup_sending_models(initial_models, num_samples, perf_val)

    def send_trained_model(self, models, num_samples, perf_value):
        # Check the state in case another global models arrived during the training
        state = self.read_state()
        if state == ClientState.gm_ready:
            # Do nothing: Discard the trained local models and adopt the new global models
            logging.info(f'--- The training was too slow. A new set of global models are available. ---')
        else:  # Keep the training results
            # Send models
            self.setup_sending_models(models, num_samples, perf_value)

    def send_recall_metric(self, recall_value):
        """
        Send recall metric to aggregator for early stopping judge
        :param recall_value: float - recall/accuracy metric for this round
        """
        from fl_main.lib.util.messengers import generate_recall_up
        from fl_main.lib.util.communication_handler import send
        
        recall_msg = generate_recall_up(recall_value, self.round, self.id)
        
        # Send recall message to aggregator
        try:
            aggr_ip = self.config['aggr_ip']
            reg_socket = self.config['reg_socket']
            
            resp = send(recall_msg, aggr_ip, int(reg_socket))
            if resp:
                logging.info(f'--- Recall metric ({recall_value:.4f}) sent to aggregator ---')
            else:
                logging.warning(f'--- Failed to send recall metric ---')
        except Exception as e:
            logging.error(f'Error sending recall metric: {e}')

    def setup_sending_models(self, models, num_samples, perf_val):
        """
        Save the trained models to the local file
        :param models: np.array - models
        :param num_samples: int - Number of sample data
        :param perf_val: float - Performance data: accuracy in this case
        :return:
        """
        # Create a model ID
        model_id = generate_model_id(IDPrefix.agent, self.id, time.time())

        # Local Model evaluation (id, accuracy)
        meta_data_dict = create_meta_data_dict(perf_val, num_samples)
        data_dict = create_data_dict_from_models(model_id, models, self.id)
        save_model_file(data_dict, self.model_path, self.lmfile, meta_data_dict)
        logging.info(f'--- Local (Initial/Trained) Models saved ---')

        self.tran_state(ClientState.sending)
        logging.info(f'--- Client State is now sending ---')

    # Waiting models
    def wait_for_global_model(self):

        # Wait for global models (base models)
        while (self.read_state() != ClientState.gm_ready):
            time.sleep(5)

        # load models from the local file
        data_dict, _ = load_model_file(self.model_path, self.gmfile)
        global_models = data_dict['models']
        logging.info(f'--- Global Models read by Agent ---')

        self.tran_state(ClientState.training)
        logging.info(f'--- Client State is now training ---')

        return global_models

    def _promote_to_aggregator(self):
        """
        Promote this agent to aggregator role.
        Updates config file to set role='aggregator' and correct IPs.
        Called when no aggregator exists in the federation.
        """
        try:
            # Determine device IP for this aggregator
            device_ip = self.config.get('device_ip')
            if not device_ip or device_ip == 'CHANGE_ME':
                device_ip = self.agent_ip  # Fall back to detected IP
            
            logging.info(f'Promoting self to aggregator with IP: {device_ip}')
            
            # Update agent config: set role to aggregator
            config_agent_file = set_config_file('agent')
            cfg_agent = read_config(config_agent_file)
            cfg_agent['role'] = 'aggregator'
            cfg_agent['aggr_ip'] = device_ip
            write_config(config_agent_file, cfg_agent)
            logging.info(f'✏️  Updated {config_agent_file}: role=aggregator, aggr_ip={device_ip}')
            
            # No need to update config_aggregator.json - server_th.py now uses config_agent.json
            
        except Exception as e:
            logging.error(f'Failed to promote to aggregator: {e}')
            raise

    async def _update_aggregator_in_db(self, aggr_ip: str, aggr_socket: str):
        """
        Update DB with the correct aggregator FL exchange socket after promotion.
        This ensures other agents connect to the right port (50001, not 8765).
        """
        try:
            from fl_main.lib.util.states import DBMsgType
            msg = [DBMsgType.update_aggregator.value, self.id, aggr_ip, int(aggr_socket)]
            reply = await send(msg, self.db_ip, int(self.db_socket))
            if reply and reply[0] == 'updated':
                logging.info(f'✅ Updated DB with aggregator FL socket: {aggr_ip}:{aggr_socket}')
            else:
                logging.warning(f'⚠️  DB update response: {reply}')
        except Exception as e:
            logging.error(f'Failed to update aggregator in DB: {e}')

    async def _register_in_db(self):
        """
        Register this agent in the centralized DB with a random score for election.
        Returns: (agent_id, score)
        """
        import random
        score = random.randint(1, 100)
        device_ip = self.config.get('device_ip', self.agent_ip)
        if device_ip == 'CHANGE_ME':
            device_ip = self.agent_ip
        
        socket = self.config.get('reg_socket', 8765)
        
        # Message format: [msg_type, agent_id, ip, socket, score]
        from fl_main.lib.util.states import DBMsgType
        msg = [DBMsgType.register_agent.value, self.id, device_ip, int(socket), score]
        
        logging.info(f'🎲 Registering in DB: {device_ip}:{socket} (score: {score})')
        resp = await send(msg, self.db_ip, self.db_socket)
        
        if resp and resp[0] == 'registered':
            logging.info(f'✅ Registered in DB successfully')
            return self.id, score
        else:
            logging.warning(f'⚠️  DB registration response: {resp}')
            return self.id, score

    async def _get_all_registered_agents_from_db(self):
        """
        Query DB for ALL registered agents with their scores.
        Returns: Dict[agent_id: score] or empty dict if error
        """
        from fl_main.lib.util.states import DBMsgType
        
        msg = [DBMsgType.get_all_agents.value]
        resp = await send(msg, self.db_ip, self.db_socket)
        
        if resp and resp[0] == 'agents':
            agents_dict = resp[1]  # Dict[agent_id: score]
            logging.info(f'📋 DB reports {len(agents_dict)} registered agents')
            return agents_dict
        else:
            logging.warning(f'⚠️  Could not get agents from DB: {resp}')
            return {}

    async def _discover_aggregator_from_db(self, verify_alive=True):
        """
        Query DB for current aggregator.
        If verify_alive=True, also checks if the aggregator is reachable.
        Returns: (aggregator_ip, aggregator_socket) or (None, None) if no aggregator
        """
        from fl_main.lib.util.states import DBMsgType
        msg = [DBMsgType.get_aggregator.value]
        
        logging.info(f'🔍 Querying DB for current aggregator...')
        resp = await send(msg, self.db_ip, self.db_socket)
        
        if resp and resp[0] == 'aggregator':
            agg_id, agg_ip, agg_socket = resp[1], resp[2], resp[3]
            logging.info(f'📡 Found aggregator in DB: {agg_ip}:{agg_socket}')
            
            # Verify aggregator is actually reachable (not stale from previous run)
            if verify_alive:
                is_alive = await self._check_aggregator_alive(agg_ip, int(agg_socket))
                if not is_alive:
                    # Check if this is MY IP - if so, I should be the aggregator but haven't started yet
                    device_ip = self.config.get('device_ip', self.agent_ip)
                    if device_ip == 'CHANGE_ME':
                        device_ip = self.agent_ip
                    
                    if agg_ip == device_ip:
                        logging.info(f'🔄 I am the registered aggregator but not running - promoting myself')
                        return agg_ip, agg_socket  # Return my info, participate() will handle promotion
                    
                    logging.warning(f'⚠️  Aggregator {agg_ip}:{agg_socket} in DB is not reachable - clearing stale entry')
                    # Clear stale aggregator from DB
                    await self._clear_aggregator_from_db()
                    # Wait a bit before triggering new election - aggregator might be starting
                    await asyncio.sleep(5)
                    return None, None
                    
            return agg_ip, agg_socket
        else:
            logging.info(f'ℹ️  No aggregator found in DB yet')
            return None, None
    
    async def _check_aggregator_alive(self, agg_ip, agg_socket, timeout=5, max_retries=3):
        """
        Check if aggregator is reachable with retries.
        Uses a simple connection test.
        Retries give time for a newly elected aggregator to start up.
        """
        import websockets
        
        for attempt in range(1, max_retries + 1):
            try:
                uri = f"ws://{agg_ip}:{agg_socket}"
                async with asyncio.timeout(timeout):
                    async with websockets.connect(uri):
                        logging.info(f'✅ Aggregator {agg_ip}:{agg_socket} is alive (attempt {attempt})')
                        return True
            except Exception as e:
                logging.debug(f'Aggregator check attempt {attempt}/{max_retries} failed: {e}')
                if attempt < max_retries:
                    # Wait before retry - gives aggregator time to start
                    await asyncio.sleep(3)
        
        logging.warning(f'❌ Aggregator {agg_ip}:{agg_socket} not reachable after {max_retries} attempts')
        return False
    
    async def _clear_aggregator_from_db(self):
        """
        Clear stale aggregator entry from DB.
        """
        from fl_main.lib.util.states import DBMsgType
        msg = [DBMsgType.clear_aggregator.value]
        logging.info(f'🧹 Clearing stale aggregator from DB...')
        resp = await send(msg, self.db_ip, self.db_socket)
        if resp and resp[0] == 'cleared':
            logging.info(f'✅ Stale aggregator cleared from DB')
        else:
            logging.warning(f'⚠️  Clear aggregator response: {resp}')

    async def _elect_aggregator_via_db(self, all_scores):
        """
        Send election request to DB with all agent scores.
        DB will determine winner and update current_aggregator table.
        Returns: (winner_id, winner_ip, winner_socket, winner_score) or None
        """
        from fl_main.lib.util.states import DBMsgType
        msg = [DBMsgType.elect_aggregator.value, all_scores]
        
        logging.info(f'🗳️  Requesting aggregator election via DB ({len(all_scores)} candidates)...')
        resp = await send(msg, self.db_ip, self.db_socket)
        
        if resp and resp[0] == 'elected':
            winner_id, winner_ip, winner_socket, winner_score = resp[1], resp[2], resp[3], resp[4]
            logging.info(f'🏆 Election result: {winner_ip}:{winner_socket} (score: {winner_score})')
            return winner_id, winner_ip, winner_socket, winner_score
        else:
            logging.error(f'❌ Election failed: {resp}')
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    cl = Client()
    logging.info(f'--- Your IP is {cl.agent_ip} ---')

    cl.start_fl_client()
