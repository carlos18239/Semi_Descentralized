import time
import numpy as np
from typing import Dict, List, Any
from fl_main.lib.util.states import ModelType, DBMsgType, AgentMsgType, AggMsgType

def generate_db_push_message(component_id: str,
                             round: int,
                             model_type: ModelType,
                             models: Dict[str,np.array],
                             model_id: str,
                             gene_time: float,
                             performance_dict: Dict[str,float]) -> List[Any]:
    msg = list()
    msg.append(DBMsgType.push.value)  # 0 - Use .value for serialization
    msg.append(component_id)  # 1
    msg.append(round)  # 2
    msg.append(model_type)  # 3
    msg.append(models)  # 4
    msg.append(model_id)  # 5
    msg.append(gene_time)  # 6
    msg.append(performance_dict)  # 7
    return msg

def generate_lmodel_update_message(agent_id: str,
                                   model_id: str,
                                   local_models: Dict[str,np.array],
                                   performance_dict: Dict[str,float]) -> List[Any]:
    msg = list()
    msg.append(AgentMsgType.update)  # 0
    msg.append(agent_id)  # 1
    msg.append(model_id)  # 2
    msg.append(local_models)  # 3
    msg.append(time.time())  # 4
    msg.append(performance_dict)  # 5
    return msg

def generate_cluster_model_dist_message(aggregator_id: str,
                                        model_id: str,
                                        round: int,
                                        models: Dict[str,np.array]) -> List[Any]:
    msg = list()
    msg.append(AggMsgType.update)  # 0
    msg.append(aggregator_id)  # 1
    msg.append(model_id)  # 2
    msg.append(round)  # 3
    msg.append(models)  # 4
    return msg

def generate_agent_participation_message(agent_name: str,
                                         agent_id: str,
                                         model_id: str,
                                         models: Dict[str,np.array],
                                         init_weights_flag: bool,
                                         simulation_flag: bool,
                                         exch_socket: str,
                                         gene_time: float,
                                         meta_dict: Dict[str,float],
                                         agent_ip: str) -> List[Any]:
    msg = list()
    msg.append(AgentMsgType.participate)  # 0
    msg.append(agent_id)  # 1
    msg.append(model_id)  # 2
    msg.append(models)  # 3
    msg.append(init_weights_flag)  # 4
    msg.append(simulation_flag)  # 5
    msg.append(exch_socket)  # 6
    msg.append(gene_time)  # 7
    msg.append(meta_dict)  # 8
    msg.append(agent_ip)  # 9
    msg.append(agent_name)  # 9
    return msg

def generate_rotation_message(new_aggregator_id: str,
                              new_aggregator_ip: str,
                              new_aggregator_reg_socket: int,
                              model_id: str,
                              round: int,
                              models: Dict[str, Any],
                              rand_scores: Dict[str,int]) -> List[Any]:
    msg = []
    msg.append(AggMsgType.rotation)            # 0
    msg.append(new_aggregator_id)              # 1
    msg.append(new_aggregator_ip)              # 2
    msg.append(new_aggregator_reg_socket)      # 3
    msg.append(model_id)                       # 4
    msg.append(round)                          # 5
    msg.append(models)                         # 6
    msg.append(rand_scores)                    # 7
    return msg

def generate_ack_message():
    msg = list()
    msg.append(AggMsgType.ack) # 0
    return msg

def generate_agent_participation_confirm_message(aggregator_id: str,
                                                 model_id: str,
                                                 models: Dict[str,Any],
                                                 round: int,
                                                 agent_id: str,
                                                 exch_socket: str,
                                                 recv_socket: str,
                                                 aggregator_ip: str = "") -> List[Any]:
    """
    Welcome/confirm message sent by aggregator to an agent on registration.
    Fields:
     0: AggMsgType.welcome
     1: aggregator_id
     2: model_id
     3: models (dict)
     4: round
     5: agent_id (assigned/confirmed id)
     6: exch_socket (port for exchange)
     7: recv_socket (port for polling/recv)
     8: aggregator_ip (optional, for rotation)
    """
    msg = list()
    msg.append(AggMsgType.welcome)  # 0
    msg.append(aggregator_id)      # 1
    msg.append(model_id)           # 2
    msg.append(models)             # 3
    msg.append(round)              # 4
    msg.append(agent_id)           # 5
    msg.append(exch_socket)        # 6
    msg.append(recv_socket)        # 7
    msg.append(aggregator_ip)      # 8 (optional)
    return msg

def generate_polling_message(round: int, agent_id: str):
    msg = list()
    msg.append(AgentMsgType.polling) # 0
    msg.append(round) # 1
    msg.append(agent_id) # 2
    return msg

def generate_recall_up(recall_value: float, round: int, agent_id: str):
    """Generate recall upload message from agent to aggregator."""
    msg = list()
    msg.append(AgentMsgType.recall_upload)  # 0
    msg.append(recall_value)  # 1
    msg.append(round)  # 2
    msg.append(agent_id)  # 3
    return msg

def generate_termination_msg(reason: str, final_round: int, final_recall: float):
    """Generate termination message to notify agents that training is complete."""
    msg = list()
    msg.append(AggMsgType.termination)  # 0
    msg.append(reason)  # 1
    msg.append(final_round)  # 2
    msg.append(final_recall)  # 3
    return msg