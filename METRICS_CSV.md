# 📊 Sistema de Métricas CSV

Este documento explica el sistema de logging de métricas que registra el rendimiento de cada round en archivos CSV.

## 🎯 Objetivo

Capturar métricas detalladas de cada round de entrenamiento federado para:
- Analizar rendimiento del modelo (accuracy/recall)
- Medir overhead de comunicación (bytes, mensajes)
- Identificar cuellos de botella (latencias, tiempos)
- Generar gráficas y reportes

---

## 📁 Archivos Generados

### **Agentes** (`metrics/metrics_<agent_name>_<timestamp>.csv`)

Ejemplo: `metrics/metrics_a2_20241201_143052.csv`

**Columnas:**
```csv
timestamp,round,global_accuracy,local_accuracy,num_messages,bytes_global,bytes_local,bytes_round_total,bytes_cumulative,latency_wait_global,round_time
```

| Columna | Descripción | Unidad |
|---------|-------------|--------|
| `timestamp` | Timestamp ISO 8601 del registro | datetime |
| `round` | Número de round | int |
| `global_accuracy` | Accuracy del modelo global | 0.0-1.0 |
| `local_accuracy` | Accuracy del modelo local entrenado | 0.0-1.0 |
| `num_messages` | Número de mensajes enviados/recibidos | int |
| `bytes_global` | Bytes recibidos del modelo global | bytes |
| `bytes_local` | Bytes enviados del modelo local | bytes |
| `bytes_round_total` | Bytes totales del round (global + local) | bytes |
| `bytes_cumulative` | Bytes acumulados desde el inicio | bytes |
| `latency_wait_global` | Tiempo esperando el modelo global | seconds |
| `round_time` | Tiempo total del round | seconds |

**Ejemplo de datos:**
```csv
2024-12-01T14:30:52.123456,1,0.125700,0.100000,3,458912,458912,917824,917824,2.3456,45.6789
2024-12-01T14:32:15.789012,2,0.131200,0.099200,3,458912,458912,917824,1835648,3.1234,48.2341
```

### **Agregador** (`metrics/metrics_aggregator_<timestamp>.csv`)

Ejemplo: `metrics/metrics_aggregator_20241201_143052.csv`

**Columnas:**
```csv
timestamp,round,num_agents,global_recall,aggregation_time,total_models_received,total_bytes_received,total_bytes_sent,rounds_without_improvement,best_recall
```

| Columna | Descripción | Unidad |
|---------|-------------|--------|
| `timestamp` | Timestamp ISO 8601 del registro | datetime |
| `round` | Número de round | int |
| `num_agents` | Número de agentes participantes | int |
| `global_recall` | Recall/accuracy global (promedio) | 0.0-1.0 |
| `aggregation_time` | Tiempo de agregación (FedAvg) | seconds |
| `total_models_received` | Total acumulado de modelos recibidos | int |
| `total_bytes_received` | Total acumulado de bytes recibidos | bytes |
| `total_bytes_sent` | Total acumulado de bytes enviados | bytes |
| `rounds_without_improvement` | Contador para early stopping | int |
| `best_recall` | Mejor recall alcanzado | 0.0-1.0 |

**Ejemplo de datos:**
```csv
2024-12-01T14:30:52.123456,1,2,0.125700,0.2345,2,917824,917824,0,0.125700
2024-12-01T14:32:15.789012,2,2,0.131200,0.2198,4,1835648,1835648,0,0.131200
```

---

## 🔄 Flujo de Logging

### **En los Agentes** (`classification_engine.py`)

```python
# Inicialización
metrics_logger = MetricsLogger(log_dir="./metrics", agent_name=agent_name)

while training_loop:
    # 1. Iniciar timer del round
    metrics_logger.start_round()
    wait_start = time.time()
    
    # 2. Esperar modelo global
    global_models = fl_client.wait_for_global_model()
    latency_wait = time.time() - wait_start
    bytes_global = len(pickle.dumps(global_models))
    
    # 3. Evaluar modelo global
    global_acc = compute_performance(global_models, testdata, False)
    
    # 4. Entrenar modelo local
    local_models = training(global_models)
    
    # 5. Evaluar modelo local
    local_acc = compute_performance(local_models, testdata, True)
    bytes_local = len(pickle.dumps(local_models))
    
    # 6. Enviar modelo y recall
    fl_client.send_trained_model(local_models, ...)
    fl_client.send_recall_metric(local_acc)
    num_messages = 3  # received GM + sent LM + sent recall
    
    # 7. Registrar métricas
    metrics_logger.log_round(
        round_num=round_num,
        global_accuracy=global_acc,
        local_accuracy=local_acc,
        num_messages=num_messages,
        bytes_global=bytes_global,
        bytes_local=bytes_local,
        latency_wait_global=latency_wait
    )
```

### **En el Agregador** (`server_th.py`)

```python
# Inicialización
self.metrics_logger = AggregatorMetricsLogger(log_dir="./metrics")

# En cada round de agregación
async def model_synthesis_routine():
    while True:
        if ready_for_aggregation():
            # 1. Medir tiempo de agregación
            agg_start = time.time()
            self.agg.aggregate_local_models()
            agg_time = time.time() - agg_start
            
            # 2. Registrar métricas
            self.metrics_logger.log_round(
                round_num=self.sm.round,
                num_agents=len(self.sm.agent_set),
                global_recall=self.best_global_recall,
                aggregation_time=agg_time,
                models_received=self.round_models_received,
                bytes_received=self.round_bytes_received,
                bytes_sent=self.round_bytes_sent,
                rounds_without_improvement=self.rounds_without_improvement,
                best_recall=self.best_global_recall
            )
            
            # 3. Resetear contadores del round
            self.round_bytes_received = 0
            self.round_bytes_sent = 0
            self.round_models_received = 0

# Al recibir modelo local
async def _process_lmodel_upload(msg):
    model_bytes = len(pickle.dumps(lmodels))
    self.round_bytes_received += model_bytes
    self.round_models_received += 1

# Al enviar modelo global
async def _send_updated_global_model(...):
    msg_bytes = len(pickle.dumps(reply))
    self.round_bytes_sent += msg_bytes
```

---

## 📈 Análisis de Métricas

### **Cargar CSV en Python**

```python
import pandas as pd
import matplotlib.pyplot as plt

# Cargar métricas de un agente
df_agent = pd.read_csv('metrics/metrics_a2_20241201_143052.csv')
df_agent['timestamp'] = pd.to_datetime(df_agent['timestamp'])

# Cargar métricas del agregador
df_agg = pd.read_csv('metrics/metrics_aggregator_20241201_143052.csv')
df_agg['timestamp'] = pd.to_datetime(df_agg['timestamp'])
```

### **Gráficas Útiles**

#### 1. **Evolución de Accuracy**
```python
plt.figure(figsize=(10, 6))
plt.plot(df_agent['round'], df_agent['global_accuracy'], label='Global')
plt.plot(df_agent['round'], df_agent['local_accuracy'], label='Local')
plt.xlabel('Round')
plt.ylabel('Accuracy')
plt.title('Model Accuracy Evolution')
plt.legend()
plt.grid(True)
plt.savefig('accuracy_evolution.png')
```

#### 2. **Bytes Transferidos por Round**
```python
plt.figure(figsize=(10, 6))
plt.bar(df_agent['round'], df_agent['bytes_round_total'] / 1024 / 1024)
plt.xlabel('Round')
plt.ylabel('MB')
plt.title('Data Transferred per Round')
plt.grid(True)
plt.savefig('bytes_per_round.png')
```

#### 3. **Bytes Acumulados**
```python
plt.figure(figsize=(10, 6))
plt.plot(df_agent['round'], df_agent['bytes_cumulative'] / 1024 / 1024)
plt.xlabel('Round')
plt.ylabel('MB')
plt.title('Cumulative Data Transferred')
plt.grid(True)
plt.savefig('cumulative_bytes.png')
```

#### 4. **Latencia de Espera**
```python
plt.figure(figsize=(10, 6))
plt.plot(df_agent['round'], df_agent['latency_wait_global'])
plt.xlabel('Round')
plt.ylabel('Seconds')
plt.title('Latency Waiting for Global Model')
plt.grid(True)
plt.savefig('latency_wait.png')
```

#### 5. **Tiempo por Round**
```python
plt.figure(figsize=(10, 6))
plt.plot(df_agent['round'], df_agent['round_time'])
plt.xlabel('Round')
plt.ylabel('Seconds')
plt.title('Round Time Evolution')
plt.grid(True)
plt.savefig('round_time.png')
```

#### 6. **Early Stopping Monitor**
```python
plt.figure(figsize=(10, 6))
plt.plot(df_agg['round'], df_agg['global_recall'], label='Current')
plt.plot(df_agg['round'], df_agg['best_recall'], label='Best', linestyle='--')
plt.xlabel('Round')
plt.ylabel('Recall')
plt.title('Global Recall with Best Recall Tracking')
plt.legend()
plt.grid(True)
plt.savefig('early_stopping.png')
```

---

## 🔍 Casos de Uso

### **1. Detectar Overhead de Comunicación**
```python
# Comparar bytes vs tiempo de round
df_agent['bytes_MB'] = df_agent['bytes_round_total'] / 1024 / 1024
correlation = df_agent[['bytes_MB', 'round_time']].corr()
print(f"Correlation bytes vs time: {correlation.iloc[0,1]:.3f}")
```

### **2. Identificar Rounds Lentos**
```python
slow_rounds = df_agent[df_agent['round_time'] > df_agent['round_time'].mean() + df_agent['round_time'].std()]
print("Slow rounds:")
print(slow_rounds[['round', 'round_time', 'latency_wait_global']])
```

### **3. Analizar Eficiencia de Early Stopping**
```python
# Rounds sin mejora antes de terminar
final_patience = df_agg['rounds_without_improvement'].iloc[-1]
print(f"Final patience counter: {final_patience}")

# Mejora promedio cuando hay mejora
improvements = df_agg[df_agg['rounds_without_improvement'] == 0]
if len(improvements) > 1:
    recall_diffs = improvements['global_recall'].diff().dropna()
    print(f"Average improvement: {recall_diffs.mean():.6f}")
```

### **4. Comparar Agentes**
```python
df_a2 = pd.read_csv('metrics/metrics_a2_*.csv')
df_a3 = pd.read_csv('metrics/metrics_a3_*.csv')

plt.figure(figsize=(10, 6))
plt.plot(df_a2['round'], df_a2['local_accuracy'], label='Agent a2')
plt.plot(df_a3['round'], df_a3['local_accuracy'], label='Agent a3')
plt.xlabel('Round')
plt.ylabel('Local Accuracy')
plt.title('Agent Performance Comparison')
plt.legend()
plt.grid(True)
plt.savefig('agent_comparison.png')
```

---

## 📊 Logs en Consola

Durante la ejecución, verás logs como:

**Agente:**
```
INFO:root:📊 Metrics CSV: ./metrics/metrics_a2_20241201_143052.csv
INFO:root:📊 Metrics Round 1: GA=0.1257, LA=0.1000, Msgs=3, Bytes=917824, Time=45.68s
INFO:root:📊 Metrics Round 2: GA=0.1312, LA=0.0992, Msgs=3, Bytes=917824, Time=48.23s
```

**Agregador:**
```
INFO:root:📊 Aggregator Metrics CSV: ./metrics/metrics_aggregator_20241201_143052.csv
INFO:root:📊 Aggregator Metrics Round 1: Agents=2, Recall=0.1257, Models=2
INFO:root:📊 Aggregator Metrics Round 2: Agents=2, Recall=0.1312, Models=4
```

---

## 🚀 Cómo Usar

### 1. **Las métricas se activan automáticamente**
No necesitas configuración adicional. Al ejecutar el sistema, se crean automáticamente los archivos CSV en `./metrics/`.

### 2. **Ubicación de archivos**
```
./metrics/
├── metrics_a2_20241201_143052.csv        ← Agente a2
├── metrics_a3_20241201_143052.csv        ← Agente a3
├── metrics_aggregator_20241201_143052.csv ← Agregador
└── ...
```

### 3. **Analizar después del experimento**
```bash
# Ver última línea de cada archivo (resumen final)
tail -n 1 metrics/metrics_a2_*.csv
tail -n 1 metrics/metrics_aggregator_*.csv

# Copiar métricas a laptop para análisis
scp r2:~/fl/*/metrics/*.csv ./local_analysis/
```

### 4. **Generar reportes**
```python
# Script de análisis completo
import pandas as pd
import matplotlib.pyplot as plt

# Cargar todos los CSVs
agent_files = ['metrics/metrics_a2_*.csv', 'metrics/metrics_a3_*.csv']
agg_file = 'metrics/metrics_aggregator_*.csv'

# Generar dashboard con todas las gráficas
generate_dashboard(agent_files, agg_file, output='report.html')
```

---

## 🎯 Ventajas del Sistema

1. **✅ Sin overhead**: Logging asíncrono, no bloquea entrenamiento
2. **✅ Completo**: Captura accuracy, bytes, latencias, tiempos
3. **✅ Persistente**: CSV sobrevive a crashes y reincicios
4. **✅ Portable**: Formato estándar, fácil de analizar
5. **✅ Automático**: No requiere configuración manual
6. **✅ Incremental**: Se actualiza en cada round
7. **✅ Timestamped**: Permite análisis temporal preciso

---

## 🐛 Troubleshooting

**Problema**: No se crean archivos CSV
- **Causa**: Directorio `./metrics/` no tiene permisos de escritura
- **Solución**: `mkdir -p ./metrics && chmod 755 ./metrics`

**Problema**: Bytes siempre son 0
- **Causa**: Error al serializar modelos con pickle
- **Solución**: Verifica que los modelos sean numpy arrays o tensores serializables

**Problema**: CSVs enormes (GB)
- **Causa**: Experimento con muchos rounds
- **Solución**: Normal para entrenamientos largos. Usa compresión: `gzip metrics/*.csv`

**Problema**: Timestamps inconsistentes
- **Causa**: Relojes desincronizados entre Pis
- **Solución**: Sincroniza con NTP: `sudo ntpdate -s time.nist.gov`
