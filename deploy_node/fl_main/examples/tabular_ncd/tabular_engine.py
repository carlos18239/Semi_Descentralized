"""
Tabular Classification Engine for Federated Learning.

Motor principal para entrenamiento federado de clasificación binaria
con datos tabulares de defunciones por ENT (Enfermedades No Transmisibles).

Uso:
    python -m fl_main.examples.tabular_ncd.tabular_engine

Compatible con la arquitectura semi-descentralizada (auto-promoción de agregador).
"""
import logging
import os
import sys
import time
import pickle
import re
from typing import Dict

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from .mlp import MLP
from .conversion import Converter
from .tabular_training import DataManager, execute_tabular_training, compute_metrics

from fl_main.agent.client import Client
from fl_main.lib.util.helpers import set_config_file, read_config
from fl_main.lib.util.metrics_logger import MetricsLogger
import subprocess


# Verificar si este nodo debe ser agregador
cfg = read_config(set_config_file('agent'))
role = cfg.get('role', 'agent')
if role == 'aggregator':
    logging.info('Starting aggregator server on this node (role==aggregator)')
    subprocess.Popen(["python", "-m", "fl_main.aggregator.server_th"])
    sys.exit(0)


class TrainingMetaData:
    """Metadatos de entrenamiento compartidos."""
    num_training_data = 500  # Samples por ronda
    agent_name = None        # Se configura en runtime


def get_agent_num(agent_name: str) -> str:
    """Extrae el número del nombre del agente (a1 -> 1, a2 -> 2, etc.)."""
    if agent_name:
        match = re.search(r'\d+', agent_name)
        if match:
            return match.group()
    return "1"


def init_models() -> Dict[str, np.ndarray]:
    """
    Retorna templates de modelos para indicar la estructura al agregador.
    El modelo no necesita estar entrenado.
    """
    # Inicializar DataManager para obtener input_dim
    agent_name = TrainingMetaData.agent_name or "a1"
    dm = DataManager.dm(cutoff_th=10, agent_name=agent_name)
    
    # Inicializar Converter con la dimensión correcta
    Converter.reset()  # Reset para asegurar dimensión correcta
    cvtr = Converter.cvtr(in_features=dm.input_dim)
    
    # Crear modelo inicial
    net = MLP(in_features=dm.input_dim)
    
    return cvtr.convert_nn_to_dict_nparray(net)


def training(models: Dict[str, np.ndarray], init_flag: bool = False) -> Dict[str, np.ndarray]:
    """
    Función de entrenamiento principal.
    
    Args:
        models: Modelos globales (diccionario de numpy arrays)
        init_flag: True si es paso inicial (solo retorna templates)
        
    Returns:
        Modelos entrenados localmente
    """
    agent_name = TrainingMetaData.agent_name or "a1"
    
    if init_flag:
        # Inicializar DataManager
        cutoff = max(1, int(TrainingMetaData.num_training_data / 32))  # batches
        DataManager.dm(cutoff_th=cutoff, agent_name=agent_name)
        return init_models()

    logging.info(f'--- Training (Agent: {agent_name}) ---')
    
    dm = DataManager.dm()
    cvtr = Converter.cvtr()
    
    # Convertir modelos globales a red neuronal
    net = cvtr.convert_dict_nparray_to_nn(models)
    
    # Configurar entrenamiento
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(net.parameters(), lr=0.001)
    
    # Entrenar
    trained_net = execute_tabular_training(dm, net, criterion, optimizer)
    
    # Convertir de vuelta a diccionario
    return cvtr.convert_nn_to_dict_nparray(trained_net)


def compute_performance(models: Dict[str, np.ndarray], testdata, is_local: bool) -> float:
    """
    Evalúa el modelo en el conjunto de test.
    
    Args:
        models: Modelo a evaluar
        testdata: No usado (DataManager ya tiene los datos)
        is_local: True si es modelo local, False si es global
        
    Returns:
        Accuracy del modelo
    """
    dm = DataManager.dm()
    cvtr = Converter.cvtr()
    
    # Convertir a red
    net = cvtr.convert_dict_nparray_to_nn(models)
    net.eval()
    
    # Calcular métricas
    metrics = compute_metrics(net, dm.testloader)
    
    model_type = 'Local' if is_local else 'Global'
    
    logging.info(f'{model_type} Model Performance:')
    logging.info(f'  Accuracy:  {metrics["accuracy"]:.4f}')
    logging.info(f'  Precision: {metrics["precision"]:.4f}')
    logging.info(f'  Recall:    {metrics["recall"]:.4f}')
    logging.info(f'  F1-Score:  {metrics["f1"]:.4f}')
    
    return metrics['accuracy']


def compute_recall(models: Dict[str, np.ndarray]) -> float:
    """Calcula el recall para early stopping."""
    dm = DataManager.dm()
    cvtr = Converter.cvtr()
    net = cvtr.convert_dict_nparray_to_nn(models)
    net.eval()
    metrics = compute_metrics(net, dm.testloader)
    return metrics['recall']


def judge_termination(training_count: int = 0, gm_arrival_count: int = 0) -> bool:
    """
    Decide si continuar entrenando.
    
    Args:
        training_count: Número de entrenamientos realizados
        gm_arrival_count: Número de modelos globales recibidos
        
    Returns:
        True para continuar, False para terminar
    """
    MAX_ROUNDS = 50  # Límite de rondas (ajustar según necesidad)
    
    if training_count >= MAX_ROUNDS:
        logging.info(f'--- Reached maximum training rounds ({MAX_ROUNDS}), terminating ---')
        return False
    
    return True


def prep_test_data():
    """Placeholder para compatibilidad."""
    return None


if __name__ == '__main__':
    # Crear directorio de logs si no existe
    os.makedirs('logs', exist_ok=True)
    
    # Configurar logging a archivo Y consola
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Handler para archivo
    file_handler = logging.FileHandler('logs/agent.log')
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)
    
    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)
    
    # Configurar logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.info('=== Tabular NCD Federated Learning Client ===')
    logging.info('Dataset: Defunciones por Enfermedades No Transmisibles')
    
    # Inicializar cliente FL
    fl_client = Client()
    logging.info(f'Agent IP: {fl_client.agent_ip}')
    
    # Configurar nombre del agente
    TrainingMetaData.agent_name = fl_client.agent_name
    logging.info(f'Agent Name: {TrainingMetaData.agent_name}')
    
    # Determinar número de datos de entrenamiento
    agent_name = TrainingMetaData.agent_name or "a1"
    
    # Inicializar métricas logger
    metrics_logger = MetricsLogger(log_dir="./metrics", agent_name=fl_client.agent_name)
    logging.info(f'📊 Metrics CSV: {metrics_logger.get_csv_path()}')
    
    # Crear modelos iniciales (templates)
    initial_models = training(dict(), init_flag=True)
    
    # Actualizar num_training_data con el tamaño real
    dm = DataManager.dm()
    TrainingMetaData.num_training_data = dm.num_train_samples
    logging.info(f'Training samples: {TrainingMetaData.num_training_data}')
    
    # Enviar modelos iniciales
    fl_client.send_initial_model(initial_models)
    
    # Iniciar cliente FL
    fl_client.start_fl_client()
    
    training_count = 0
    gm_arrival_count = 0
    
    while judge_termination(training_count, gm_arrival_count):
        # Iniciar timer de ronda
        metrics_logger.start_round()
        wait_start_time = time.time()
        num_messages_round = 0
        
        # Esperar modelo global
        global_models = fl_client.wait_for_global_model()
        latency_wait_global = time.time() - wait_start_time
        gm_arrival_count += 1
        num_messages_round += 1
        
        # Calcular bytes del modelo global
        bytes_global = len(pickle.dumps(global_models))
        
        # Evaluar modelo global
        global_model_performance = compute_performance(global_models, prep_test_data(), False)
        global_recall = compute_recall(global_models)
        
        # Entrenar localmente
        models = training(global_models)
        training_count += 1
        logging.info(f'--- Training Round {training_count} Complete ---')
        
        # Evaluar modelo local
        local_accuracy = compute_performance(models, prep_test_data(), True)
        local_recall = compute_recall(models)
        
        # Calcular bytes del modelo local
        bytes_local = len(pickle.dumps(models))
        
        # Enviar modelo entrenado
        fl_client.send_trained_model(
            models, 
            int(TrainingMetaData.num_training_data), 
            local_accuracy
        )
        num_messages_round += 1
        
        # Enviar métrica de recall para early stopping
        fl_client.send_recall_metric(local_recall)
        num_messages_round += 1
        
        # Registrar métricas
        metrics_logger.log_round(
            round_num=training_count,
            global_accuracy=global_model_performance,
            local_accuracy=local_accuracy,
            global_recall=global_recall,
            local_recall=local_recall,
            num_messages=num_messages_round,
            bytes_global=bytes_global,
            bytes_local=bytes_local,
            latency_wait_global=latency_wait_global
        )
    
    logging.info('=== Training Complete ===')
    logging.info(f'Total rounds: {training_count}')
