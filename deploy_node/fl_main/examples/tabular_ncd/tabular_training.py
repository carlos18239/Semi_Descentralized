"""
Tabular Training Module for NCD Federated Learning.

Proporciona:
- TabularDataset: Dataset PyTorch para datos tabulares
- DataManager: Singleton que maneja train/val/test loaders
- execute_tabular_training: Función de entrenamiento

Compatible con la arquitectura semi-descentralizada de FL.
"""
import os
import logging
from typing import Tuple

import torch
from torch.utils.data import DataLoader, Dataset
import pandas as pd
import numpy as np


class TabularDataset(Dataset):
    """Dataset tabular compatible con PyTorch."""
    
    def __init__(self, dataframe: pd.DataFrame, target_col: str = "target"):
        # Excluir columnas que empiecen con 'id_' también
        feature_cols = [c for c in dataframe.columns 
                       if c != target_col and not c.startswith('id_')]
        
        self.X = dataframe[feature_cols].values.astype("float32")
        self.y = dataframe[target_col].values.astype("float32")
        
    def __len__(self):
        return len(self.X)
    
    def __getitem__(self, idx):
        return (
            torch.tensor(self.X[idx], dtype=torch.float32),
            torch.tensor(self.y[idx], dtype=torch.float32)
        )


class DataManager:
    """
    Maneja datasets y DataLoaders para datos tabulares.
    Implementa patrón Singleton.
    """
    _singleton_dm = None

    @classmethod
    def dm(cls, cutoff_th: int = 0, agent_name: str = "a1"):
        if cls._singleton_dm is None and cutoff_th > 0:
            cls._singleton_dm = cls(cutoff_th, agent_name)
        return cls._singleton_dm
    
    @classmethod
    def reset(cls):
        """Reinicia el singleton (útil para testing)."""
        cls._singleton_dm = None

    def __init__(self, cutoff_th: int, agent_name: str = "a1"):
        """
        Inicializa el DataManager.
        
        Args:
            cutoff_th: Número de batches para entrenar por ronda
            agent_name: Nombre del agente (identificador, no afecta el archivo de datos)
        """
        self.agent_name = agent_name
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        
        # deploy_node/fl_main/examples/tabular_ncd/ -> deploy_node/
        deploy_root = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))
        
        # Directorio de datos procesados (único por nodo)
        data_dir = os.path.join(deploy_root, "data", "processed")
        
        # Verificar si existen los CSVs procesados
        train_path = os.path.join(data_dir, "train.csv")
        val_path = os.path.join(data_dir, "val.csv")
        test_path = os.path.join(data_dir, "test.csv")
        
        if not all([os.path.exists(p) for p in [train_path, val_path, test_path]]):
            logging.info(f"⚠️ CSVs procesados no encontrados.")
            logging.info(f"→ Ejecutando preprocesamiento automático...")
            self._run_preprocessing(BASE_DIR, agent_name)
        
        # Cargar CSVs procesados
        logging.info(f"📂 Cargando datos de: {data_dir}")
        train_df = pd.read_csv(train_path)
        val_df = pd.read_csv(val_path)
        test_df = pd.read_csv(test_path)

        # Detectar dimensión de entrada
        target_col = "target"
        feature_cols = [c for c in train_df.columns 
                       if c != target_col and not c.startswith('id_')]
        self.input_dim = len(feature_cols)
        
        logging.info(f"✓ Datos cargados: {len(train_df)} train, {len(val_df)} val, {len(test_df)} test")
        logging.info(f"✓ Input dimension: {self.input_dim} features")

        # Crear datasets
        trainset = TabularDataset(train_df, target_col=target_col)
        valset = TabularDataset(val_df, target_col=target_col)
        testset = TabularDataset(test_df, target_col=target_col)

        # Crear DataLoaders
        self.trainloader = DataLoader(trainset, batch_size=32, shuffle=True)
        self.valloader = DataLoader(valset, batch_size=32, shuffle=False)
        self.testloader = DataLoader(testset, batch_size=32, shuffle=False)

        self.cutoff_threshold = cutoff_th
        self.num_train_samples = len(train_df)
        self.num_val_samples = len(val_df)
        self.num_test_samples = len(test_df)

    def _run_preprocessing(self, base_dir: str, agent_name: str):
        """Ejecuta preprocesamiento si no existen los CSVs."""
        from .data_preparation import get_default_config, run_preprocessing
        
        cfg = get_default_config(base_dir, agent_name)
        
        # Verificar archivos necesarios
        if not os.path.exists(cfg['raw_data_path']):
            raise FileNotFoundError(
                f"No se encontró el archivo de datos: {cfg['raw_data_path']}\n"
                f"Asegúrate de tener data.csv en deploy_node/data/"
            )
        
        if not os.path.exists(cfg['preprocessor_path']):
            raise FileNotFoundError(
                f"No se encontró el preprocessor: {cfg['preprocessor_path']}\n"
                f"Asegúrate de tener preprocessor_global.joblib en deploy_node/artifacts/"
            )
        
        run_preprocessing(cfg)

    def get_random_batch(self, is_train: bool = True) -> Tuple[torch.Tensor, torch.Tensor]:
        """Retorna un batch aleatorio para demos."""
        loader = self.trainloader if is_train else self.testloader
        features, labels = next(iter(loader))
        return features, labels


def execute_tabular_training(dm: DataManager, net, criterion, optimizer) -> torch.nn.Module:
    """
    Rutina de entrenamiento para datos tabulares.
    
    Args:
        dm: DataManager con los datos
        net: Red neuronal (MLP)
        criterion: Función de pérdida (BCEWithLogitsLoss)
        optimizer: Optimizador
        
    Returns:
        Red entrenada
    """
    net.train()
    running_loss = 0.0
    num_trained_batches = 0
    
    for epoch in range(1):  # 1 epoch por ronda de FL
        for i, (inputs, labels) in enumerate(dm.trainloader):
            # Detener después de cutoff_threshold batches
            if num_trained_batches >= dm.cutoff_threshold:
                break
            
            # Zero gradients
            optimizer.zero_grad()
            
            # Forward
            outputs = net(inputs).squeeze()
            loss = criterion(outputs, labels)
            
            # Backward
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item()
            num_trained_batches += 1
            
            if num_trained_batches % 50 == 0:
                avg_loss = running_loss / num_trained_batches
                logging.info(f'[Batch {num_trained_batches}] avg loss: {avg_loss:.4f}')
    
    final_loss = running_loss / max(num_trained_batches, 1)
    logging.info(f'Entrenamiento completado: {num_trained_batches} batches, loss: {final_loss:.4f}')
    
    return net


def compute_metrics(net, dataloader) -> dict:
    """
    Calcula métricas de clasificación binaria.
    
    Returns:
        dict con accuracy, precision, recall, f1
    """
    net.eval()
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for inputs, labels in dataloader:
            outputs = net(inputs).squeeze()
            probs = torch.sigmoid(outputs)
            preds = (probs >= 0.5).float()
            
            all_preds.extend(preds.numpy())
            all_labels.extend(labels.numpy())
    
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    # Calcular métricas
    tp = np.sum((all_preds == 1) & (all_labels == 1))
    fp = np.sum((all_preds == 1) & (all_labels == 0))
    tn = np.sum((all_preds == 0) & (all_labels == 0))
    fn = np.sum((all_preds == 0) & (all_labels == 1))
    
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'f1': f1
    }
