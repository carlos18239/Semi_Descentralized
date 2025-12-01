"""
Metrics Logger for Federated Learning
Records performance metrics to CSV file for each round
"""
import csv
import os
import time
import logging
from pathlib import Path
from datetime import datetime


class MetricsLogger:
    """
    Logs federated learning metrics to CSV file.
    Tracks: accuracy, messages, bytes, latency, timing per round.
    """
    
    def __init__(self, log_dir="./metrics", agent_name="agent"):
        """
        Initialize metrics logger
        :param log_dir: Directory to store CSV files
        :param agent_name: Name of the agent (for filename)
        """
        self.log_dir = Path(log_dir)
        self.agent_name = agent_name
        
        # Create metrics directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # CSV filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_file = self.log_dir / f"metrics_{agent_name}_{timestamp}.csv"
        
        # CSV headers
        self.headers = [
            'timestamp',
            'round',
            'global_accuracy',
            'local_accuracy',
            'num_messages',
            'bytes_global',
            'bytes_local',
            'bytes_round_total',
            'bytes_cumulative',
            'latency_wait_global',
            'round_time'
        ]
        
        # Cumulative byte counter
        self.cumulative_bytes = 0
        
        # Round start time tracker
        self.round_start_time = None
        
        # Initialize CSV file with headers
        self._init_csv()
        
        logging.info(f"MetricsLogger initialized: {self.csv_file}")
    
    def _init_csv(self):
        """Create CSV file with headers"""
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
    
    def start_round(self):
        """Mark the start of a round for timing"""
        self.round_start_time = time.time()
    
    def log_round(self, 
                  round_num,
                  global_accuracy=None,
                  local_accuracy=None,
                  num_messages=0,
                  bytes_global=0,
                  bytes_local=0,
                  latency_wait_global=0.0):
        """
        Log metrics for a completed round
        
        :param round_num: Round number
        :param global_accuracy: Accuracy of global model (0-1)
        :param local_accuracy: Accuracy of local model (0-1)
        :param num_messages: Number of messages sent/received
        :param bytes_global: Bytes received for global model
        :param bytes_local: Bytes sent for local model
        :param latency_wait_global: Time waiting for global model (seconds)
        """
        # Calculate round time
        round_time = time.time() - self.round_start_time if self.round_start_time else 0.0
        
        # Calculate round total bytes
        bytes_round_total = bytes_global + bytes_local
        
        # Update cumulative bytes
        self.cumulative_bytes += bytes_round_total
        
        # Prepare row data
        row = {
            'timestamp': datetime.now().isoformat(),
            'round': round_num,
            'global_accuracy': f"{global_accuracy:.6f}" if global_accuracy is not None else '',
            'local_accuracy': f"{local_accuracy:.6f}" if local_accuracy is not None else '',
            'num_messages': num_messages,
            'bytes_global': bytes_global,
            'bytes_local': bytes_local,
            'bytes_round_total': bytes_round_total,
            'bytes_cumulative': self.cumulative_bytes,
            'latency_wait_global': f"{latency_wait_global:.4f}",
            'round_time': f"{round_time:.4f}"
        }
        
        # Write to CSV
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writerow(row)
        
        # Log to console
        ga_str = f"{global_accuracy:.4f}" if global_accuracy is not None else "N/A"
        la_str = f"{local_accuracy:.4f}" if local_accuracy is not None else "N/A"
        logging.info(f"📊 Metrics Round {round_num}: "
                    f"GA={ga_str}, "
                    f"LA={la_str}, "
                    f"Msgs={num_messages}, "
                    f"Bytes={bytes_round_total}, "
                    f"Time={round_time:.2f}s")
        
        # Reset round timer
        self.round_start_time = None
    
    def get_csv_path(self):
        """Return the path to the CSV file"""
        return str(self.csv_file)


class AggregatorMetricsLogger:
    """
    Metrics logger specifically for aggregator.
    Tracks aggregate metrics across all agents.
    """
    
    def __init__(self, log_dir="./metrics"):
        """
        Initialize aggregator metrics logger
        :param log_dir: Directory to store CSV files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_file = self.log_dir / f"metrics_aggregator_{timestamp}.csv"
        
        self.headers = [
            'timestamp',
            'round',
            'num_agents',
            'global_recall',
            'aggregation_time',
            'total_models_received',
            'total_bytes_received',
            'total_bytes_sent',
            'rounds_without_improvement',
            'best_recall'
        ]
        
        self.cumulative_models = 0
        self.cumulative_bytes_received = 0
        self.cumulative_bytes_sent = 0
        
        self._init_csv()
        logging.info(f"AggregatorMetricsLogger initialized: {self.csv_file}")
    
    def _init_csv(self):
        """Create CSV file with headers"""
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
    
    def log_round(self,
                  round_num,
                  num_agents,
                  global_recall=None,
                  aggregation_time=0.0,
                  models_received=0,
                  bytes_received=0,
                  bytes_sent=0,
                  rounds_without_improvement=0,
                  best_recall=None):
        """
        Log aggregator metrics for a round
        
        :param round_num: Round number
        :param num_agents: Number of participating agents
        :param global_recall: Global recall/accuracy
        :param aggregation_time: Time spent on aggregation (seconds)
        :param models_received: Number of models received this round
        :param bytes_received: Bytes received this round
        :param bytes_sent: Bytes sent this round
        :param rounds_without_improvement: Counter for early stopping
        :param best_recall: Best recall achieved so far
        """
        self.cumulative_models += models_received
        self.cumulative_bytes_received += bytes_received
        self.cumulative_bytes_sent += bytes_sent
        
        row = {
            'timestamp': datetime.now().isoformat(),
            'round': round_num,
            'num_agents': num_agents,
            'global_recall': f"{global_recall:.6f}" if global_recall is not None else '',
            'aggregation_time': f"{aggregation_time:.4f}",
            'total_models_received': self.cumulative_models,
            'total_bytes_received': self.cumulative_bytes_received,
            'total_bytes_sent': self.cumulative_bytes_sent,
            'rounds_without_improvement': rounds_without_improvement,
            'best_recall': f"{best_recall:.6f}" if best_recall is not None else ''
        }
        
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writerow(row)
        
        recall_str = f"{global_recall:.4f}" if global_recall is not None else "N/A"
        logging.info(f"📊 Aggregator Metrics Round {round_num}: "
                    f"Agents={num_agents}, "
                    f"Recall={recall_str}, "
                    f"Models={self.cumulative_models}")
    
    def get_csv_path(self):
        """Return the path to the CSV file"""
        return str(self.csv_file)
