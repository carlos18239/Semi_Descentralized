import pickle
import logging
import time
import os
from typing import Any, List

from .sqlite_db import SQLiteDBHandler
from fl_main.lib.util.helpers import generate_id, read_config, set_config_file
from fl_main.lib.util.states import DBMsgType, DBPushMsgLocation, ModelType
from fl_main.lib.util.communication_handler import init_db_server, send_websocket, receive 

class PseudoDB:
    """
    Pseudo Database class instance that receives models and their data from an aggregator,
    and pushes them to an actual database
    """

    def __init__(self):

        # Database ID just in case
        self.id = generate_id()

        # read the config file
        config_file = set_config_file("db")
        self.config = read_config(config_file)

        # Initialize DB IP and Port
        self.db_ip = self.config['db_ip']
        self.db_socket = self.config['db_socket']

        # if there is no directory to save models create the dir
        self.data_path = self.config['db_data_path']
        self.db_name = self.config['db_name']
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)

        # Init DB
        self.db_file = f'{self.data_path}/{self.db_name}.db'   # ./db/sample_data.db
        self.dbhandler = SQLiteDBHandler(self.db_file)
        self.dbhandler.initialize_DB()

        # Model save location
        # if there is no directory to save models
        self.db_model_path = self.config['db_model_path']
        if not os.path.exists(self.db_model_path):
            os.makedirs(self.db_model_path)


    async def handler(self, websocket, path):
        """
        Receives all requests from agents/aggregators and returns requested info
        :param websocket:
        :param path:
        :return:
        """
        # receive a request
        msg = await receive(websocket)

        logging.info(f'Request Arrived')
        logging.debug(f'Request: {msg}')

        # Extract the message type
        msg_type = msg[0] if isinstance(msg, list) and len(msg) > 0 else None

        reply = []
        
        if msg_type == DBMsgType.push.value:  # models
            logging.info(f'--- Model pushed: {msg[int(DBPushMsgLocation.model_type)]} ---')
            self._push_all_data_to_db(msg)
            reply.append('confirmation')
            
        elif msg_type == DBMsgType.register_agent.value:  # register agent
            # msg format: [msg_type, agent_id, ip, socket, score]
            agent_id, ip, socket, score = msg[1], msg[2], msg[3], msg[4]
            logging.info(f'--- Agent registration: {agent_id} at {ip}:{socket} (score: {score}) ---')
            self.dbhandler.upsert_agent(agent_id, ip, socket)
            # Store score temporarily for election (could use a separate table)
            reply.append('registered')
            
        elif msg_type == DBMsgType.get_aggregator.value:  # get current aggregator
            logging.info(f'--- Get current aggregator request ---')
            result = self.dbhandler.get_current_aggregator()
            if result:
                agg_id, agg_ip, agg_socket = result
                reply = ['aggregator', agg_id, agg_ip, agg_socket]
                logging.info(f'   Current aggregator: {agg_ip}:{agg_socket}')
            else:
                reply = ['no_aggregator']
                logging.info(f'   No aggregator registered yet')
                
        elif msg_type == DBMsgType.elect_aggregator.value:  # elect new aggregator
            # msg format: [msg_type, {agent_id: score, ...}]
            scores = msg[1] if len(msg) > 1 else {}
            logging.info(f'--- Aggregator election request with {len(scores)} candidates ---')
            
            if scores:
                # Find winner (highest score, tie-break by agent_id)
                winner_id = max(scores.items(), key=lambda x: (x[1], x[0]))[0]
                logging.info(f'   Winner: {winner_id} (score: {scores[winner_id]})')
                
                # Get winner's IP/socket from agents table
                all_agents = self.dbhandler.get_all_agents()
                winner_ip, winner_socket = None, None
                for aid, ip, sock in all_agents:
                    if aid == winner_id:
                        winner_ip, winner_socket = ip, sock
                        break
                
                if winner_ip:
                    self.dbhandler.update_current_aggregator(winner_id, winner_ip, winner_socket)
                    reply = ['elected', winner_id, winner_ip, winner_socket, scores[winner_id]]
                    logging.info(f'   Aggregator elected: {winner_ip}:{winner_socket}')
                else:
                    reply = ['election_failed', 'winner_not_found']
                    logging.error(f'   Election failed: winner not in agents table')
            else:
                reply = ['election_failed', 'no_candidates']
                logging.warning(f'   Election failed: no candidates provided')
                
        elif msg_type == DBMsgType.update_aggregator.value:  # update aggregator FL socket
            # msg format: [msg_type, agent_id, aggr_ip, aggr_socket]
            # This is sent by the winner after promotion to update with FL socket (50001)
            if len(msg) >= 4:
                agent_id, aggr_ip, aggr_socket = msg[1], msg[2], msg[3]
                logging.info(f'--- Aggregator socket update: {aggr_ip}:{aggr_socket} ---')
                self.dbhandler.update_current_aggregator(agent_id, aggr_ip, aggr_socket)
                reply = ['updated']
                logging.info(f'   Updated aggregator to FL socket: {aggr_ip}:{aggr_socket}')
            else:
                reply = ['update_failed', 'invalid_message']
                logging.error(f'   Invalid update_aggregator message format')
        else:
            # Error for undefined message type
            logging.error(f'Undefined DB Access Message Type: {msg_type}')
            reply = ['error', f'unknown_msg_type_{msg_type}']

        # reply to the sender
        await send_websocket(reply, websocket)


    def _push_all_data_to_db(self, msg: List[Any]):
        """
        push data received from the aggregator to database 
        and save models in the file system
        :param msg: Message received
        :return: component id, round, message typr, model id, gene time, local perf, num samples
        """
        pm = self._parse_message(msg)
        self.dbhandler.insert_an_entry(*pm)

        # save models
        model_id = msg[int(DBPushMsgLocation.model_id)]
        models = msg[int(DBPushMsgLocation.models)]
        fname = f'{self.db_model_path}/{model_id}.binaryfile'
        with open(fname, 'wb') as f:
            pickle.dump(models, f)

    def _parse_message(self, msg: List[Any]):
        """
        extract values from the message
        :param msg: Message received
        :return:
        """
        component_id = msg[int(DBPushMsgLocation.component_id)]
        r = msg[int(DBPushMsgLocation.round)]
        mt = msg[int(DBPushMsgLocation.model_type)]
        model_id = msg[int(DBPushMsgLocation.model_id)]
        gene_time = msg[int(DBPushMsgLocation.gene_time)]
        meta_data = msg[int(DBPushMsgLocation.meta_data)]

        # if local model performance is saved
        local_prfmc = 0.0
        if mt == ModelType.local:
            try: local_prfmc = meta_data["accuracy"]
            except: pass

        # Number of samples is saved
        num_samples = 0
        try: num_samples = meta_data["num_samples"]
        except: pass

        return component_id, r, mt, model_id, gene_time, local_prfmc, num_samples


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("--- Pseudo DB Started ---")

    pdb = PseudoDB()
    init_db_server(pdb.handler, pdb.db_ip, pdb.db_socket)
