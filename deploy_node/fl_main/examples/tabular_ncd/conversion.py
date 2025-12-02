"""
Conversion utilities for Tabular NCD models.

Convierte entre modelos PyTorch (MLP) y diccionarios de numpy arrays
para transmisión en Federated Learning.
"""
from typing import Dict
import numpy as np
import torch

from .mlp import MLP


class Converter:
    """
    Convierte modelos MLP entre formato PyTorch y numpy arrays.
    Implementa patrón Singleton.
    """
    _singleton_cvtr = None
    
    @classmethod
    def cvtr(cls, in_features: int = None):
        """
        Obtiene o crea el converter singleton.
        
        Args:
            in_features: Dimensión de entrada del MLP (requerido en primera llamada)
        """
        if cls._singleton_cvtr is None:
            if in_features is None:
                raise ValueError("in_features requerido para inicializar Converter")
            cls._singleton_cvtr = cls(in_features)
        return cls._singleton_cvtr
    
    @classmethod
    def reset(cls):
        """Reinicia el singleton."""
        cls._singleton_cvtr = None

    def __init__(self, in_features: int):
        self.in_features = in_features

    def convert_nn_to_dict_nparray(self, net: MLP) -> Dict[str, np.ndarray]:
        """
        Convierte un modelo MLP a diccionario de numpy arrays.
        
        Args:
            net: Modelo MLP de PyTorch
            
        Returns:
            Dict con pesos y biases como numpy arrays
        """
        state_dict = net.state_dict()
        return {key: value.cpu().numpy() for key, value in state_dict.items()}

    def convert_dict_nparray_to_nn(self, models: Dict[str, np.ndarray]) -> MLP:
        """
        Convierte diccionario de numpy arrays a modelo MLP.
        
        Args:
            models: Dict con pesos y biases como numpy arrays
            
        Returns:
            Modelo MLP con los pesos cargados
        """
        # Crear nueva instancia del modelo
        net = MLP(in_features=self.in_features)
        
        # Convertir numpy arrays a tensors y cargar
        state_dict = {key: torch.tensor(value) for key, value in models.items()}
        net.load_state_dict(state_dict)
        
        return net
