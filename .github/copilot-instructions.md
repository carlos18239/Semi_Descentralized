# Federated Learning - Semi-Decentralized Tabular Classification

## Architecture Overview

**Semi-decentralized FL system** with dynamic aggregator election for hospital mortality prediction (NCD classification).

### Three-tier architecture:
1. **PseudoDB Server** (`deploy_db_server/`) - Central SQLite coordinator storing models/metadata
2. **Agent Nodes** (`deploy_node/`) - Hospital clients that train locally and can become aggregators
3. **Dynamic Aggregator** - One agent auto-promotes to aggregate models via election protocol

```
┌─────────────┐         ┌──────────────┐
│  PseudoDB   │◄────────┤  Agent Node  │ (Hospital 1)
│  (Server)   │         │  + Dataset   │
│  SQLite DB  │         └──────────────┘
└──────┬──────┘         
       │                ┌──────────────┐
       ├────────────────┤  Agent Node  │ (Hospital 2)  
       │                │  AGGREGATOR  │ ← Elected leader
       │                └──────────────┘
       │
       └────────────────┤  Agent Node  │ (Hospital 3)
                        └──────────────┘
```

**Key Pattern**: Nodes dynamically elect an aggregator via score-based election in DB. The aggregator role rotates using `role_supervisor.py` which switches between agent/aggregator modes.

## Project Structure

### deploy_db_server/ (Central Server)
- `fl_main/pseudodb/pseudo_db.py` - WebSocket server handling model pushes, agent registration, aggregator election
- `fl_main/pseudodb/sqlite_db.py` - DB schema: `local_models`, `cluster_models`, `agents`, `current_aggregator`
- `setups/config_db.json` - Server IP/port configuration
- **Run**: `./scripts/start.sh` or `python -m fl_main.pseudodb.pseudo_db`

### deploy_node/ (Client Nodes - Raspberry Pi)
- `fl_main/agent/client.py` - Agent client implementing FL protocol
- `fl_main/aggregator/` - FedAvg aggregation logic (`aggregation.py`), state management
- `fl_main/examples/tabular_ncd/` - **Domain-specific training engine**:
  - `tabular_engine.py` - Main entry point with `training()`, `compute_performance()` hooks
  - `mlp.py` - PyTorch MLP model (3-layer: Input→120→84→1)
  - `data_preparation.py` - Preprocesses CSV using shared `preprocessor_global.joblib`
  - `conversion.py` - Converts PyTorch models ↔ numpy arrays for network transmission
- `setups/config_agent.json` - Node configuration: `device_ip`, `db_ip`, `role` (agent/aggregator)
- **Run**: `./scripts/start.sh` → launches `fl_main.agent.role_supervisor`

## Communication Protocol

All communication via **WebSockets** + **pickle serialization**:

### Message Types (see `fl_main/lib/util/states.py`):
- `DBMsgType` - DB operations: `push`, `register_agent`, `elect_aggregator`, `get_aggregator`
- `AgentMsgType` - Agent→Aggregator: `participate`, `update`, `polling`
- `AggMsgType` - Aggregator→Agent: `welcome`, `update`, `rotation`, `termination`

### Communication Flow:
1. **Agent registers with DB**: `[DBMsgType.register_agent, agent_id, ip, socket, score]`
2. **Registration grace period**: Agents wait `registration_grace_period` seconds (default: 20s) for others to register
   - Polls DB every 2s to check agent count: `[DBMsgType.get_agents_count]`
   - Exits early if `expected_num_agents` reached
3. **Agent queries current aggregator**: `[DBMsgType.get_aggregator]` → receives `[aggregator_id, ip, socket]`
4. **If no aggregator, triggers election**: 
   - Queries ALL registered agents: `[DBMsgType.get_all_agents]` → receives `{agent_id: score}`
   - Sends election request: `[DBMsgType.elect_aggregator, {all_scores}]`
   - DB selects winner (highest score, tie-break by agent_id)
5. **Winner becomes aggregator**, updates `role='aggregator'` in config
6. **Agents send local models**: `[AgentMsgType.update, agent_id, model_id, models_dict, ...]`
7. **Aggregator performs FedAvg**, pushes to DB, distributes global model

**Timeout Protection**: Aggregator waits up to `aggregation_timeout` (default: 120s) for models before forcing partial aggregation.

**Code utilities**: `fl_main/lib/util/communication_handler.py` - `send()`, `receive()`, `init_fl_server()`

## Key Development Patterns

### 1. Role Switching (Agent ↔ Aggregator)
Nodes switch roles dynamically via `role_supervisor.py`:
```python
# Reads config['role'] in loop
if role == 'aggregator':
    subprocess.run(['python3', '-m', 'fl_main.aggregator.server_th'])
else:  # agent
    subprocess.run(['python3', '-m', 'fl_main.examples.tabular_ncd.tabular_engine'])
```
**Critical**: Always update `config_agent.json` when changing roles, not just in-memory state.

### 2. Model Conversion (PyTorch ↔ Numpy)
FL requires serializable formats for network transmission:
```python
from fl_main.examples.tabular_ncd.conversion import Converter
cvtr = Converter.cvtr()
models_dict = cvtr.convert_nn_to_dict_nparray(pytorch_model)  # For sending
pytorch_model = cvtr.convert_dict_nparray_to_nn(models_dict)  # For training
```
**Pattern**: `Converter` is a singleton tracking model architecture (`in_features`).

### 3. Data Loading (Tabular NCD Dataset)
Each node has ONE file: `data/data.csv` with 22 columns including `is_premature_ncd` (binary target).
```python
from fl_main.examples.tabular_ncd.tabular_training import DataManager
dm = DataManager.dm(cutoff_th=10, agent_name='a1')  # Singleton
# Automatically loads from config['dataset_path'], applies preprocessor
trainloader = dm.trainloader
testloader = dm.testloader
```
**Important**: Preprocessor (`artifacts/preprocessor_global.joblib`) must be shared across all nodes for consistent feature encoding.

### 4. FedAvg Aggregation
Weighted average in `fl_main/aggregator/aggregation.py`:
```python
def _average_aggregate(self, buffer: List[np.array], num_samples: List[int]):
    denominator = sum(num_samples)
    model = (num_samples[0] / denominator) * buffer[0]
    for i in range(1, len(buffer)):
        model += (num_samples[i] / denominator) * buffer[i]
    return model
```
**Each layer aggregated separately** - `mnames` = model layer names (e.g., `['fc1.weight', 'fc1.bias', ...]`).

### 5. Logging & Metrics
- **System logs**: `logging.info()` throughout codebase (no centralized config, defaults to console)
- **Training metrics**: `fl_main/lib/util/metrics_logger.py` - CSV output to `metrics/metrics_{agent_name}.csv`
  - Tracks: accuracy, recall, bytes, latency per round
  - Usage: `logger = MetricsLogger(agent_name='a1')` → `logger.log_round(round_num, ...)`

## Configuration Management

### deploy_db_server/setups/config_db.json
```json
{
  "db_ip": "172.23.211.160",  // Change to server's actual IP
  "db_socket": "9017",
  "db_name": "sample_data",
  "db_model_path": "./db/models"
}
```

### deploy_node/setups/config_agent.json
```json
{
  "device_ip": "CHANGE_ME",  // MUST SET: Node's IP
  "db_ip": "172.23.211.160", // Server IP
  "role": "agent",           // Dynamic: "agent" or "aggregator"
  "dataset_path": "data/data.csv",
  "target_column": "is_premature_ncd",
  "local_epochs": 5,
  "batch_size": 32,
  
  // Synchronization & Election Settings
  "expected_num_agents": 0,           // 0=no limit, N=wait for N agents
  "registration_grace_period": 30,    // Seconds to wait for agent registration
  "election_min_agents": 1,           // Minimum agents required for election
  "aggregation_timeout": 120,         // Max wait time for model aggregation (seconds)
  "aggregation_threshold": 1.0,       // Models needed: <1.0=fraction, ≥1=absolute (1.0=100%)
  
  // Rotation Settings
  "rotation_interval": 10,            // Rounds between rotations (default: 10)
  "rotation_delay": 60                // Seconds to wait before rotation (default: 60s)
}
```
**Critical**: 
- `device_ip` cannot be "CHANGE_ME" - scripts check and fail early
- `aggregation_threshold`: 
  - **1.0** = espera al 100% de agentes registrados (síncrono total)
  - **0.5** = espera al 50% de agentes (tolerante a fallos)
  - **2** (≥1) = espera exactamente 2 modelos (número absoluto)
- `rotation_interval` controls frequency: 10 = rotate every 10 rounds
- `rotation_delay` gives agents time to process final model before rotation

## Development Workflows

### Starting the System
1. **Server**: `cd deploy_db_server && ./scripts/start.sh`
   - Creates SQLite DB at `db/sample_data.db`
   - Listens on port 9017
2. **Nodes**: `cd deploy_node && ./scripts/start.sh`
   - Verifies dependencies (torch, pandas, websockets)
   - Kills old processes on ports 4321, 7890, 8765
   - Launches `role_supervisor.py` which starts training engine

### Adding New Training Logic
Modify `deploy_node/fl_main/examples/tabular_ncd/tabular_engine.py`:
```python
def training(models: Dict[str, np.ndarray], init_flag: bool) -> Dict[str, np.ndarray]:
    # 1. Convert numpy → PyTorch: cvtr.convert_dict_nparray_to_nn(models)
    # 2. Train locally with your logic
    # 3. Convert back: cvtr.convert_nn_to_dict_nparray(trained_net)
    return models_dict
```
**Hook into Client**: `client.py` calls `training()` after receiving global model.

### Debugging Communication
Check WebSocket message traces:
```bash
# In any Python file
logging.basicConfig(level=logging.DEBUG)  # Enables detailed logs
# Messages are pickled lists - check states.py for index meanings
```
**Common issue**: Port conflicts → scripts kill processes automatically but verify with `lsof -i:9017`.

### Testing Locally (Simulation Mode)
Nodes support simulation flag to override sockets:
```bash
python -m fl_main.examples.tabular_ncd.tabular_engine 1 50001 agent1
# Args: simulation_flag, socket, agent_name
```

## Critical Constraints

1. **Single aggregator at a time** - DB enforces via `current_aggregator` table (id=1 constraint)
2. **Model architecture must match** - All nodes must use same `MLP(in_features=N)` dimension
3. **Synchronization via grace period** - `registration_grace_period` (default: 30s) ensures all nodes register before election
4. **Timeout-based aggregation** - Aggregator waits `aggregation_timeout` (default: 120s) before forcing partial aggregation
5. **Rotation frequency** - Aggregator rotates every `rotation_interval` rounds (default: 10 rounds)
6. **Quorum requirement** - Aggregation requires `min_agents_for_aggregation` agents (default: 1)
7. **Binary protocol** - All messages use pickle; cannot inspect with plain text tools
8. **No TLS** - WebSockets are unencrypted (ws:// not wss://)

## Common Pitfalls

- **"Connection lost to agent"** → Check firewall rules, verify IPs in config files match `ifconfig` output
- **Dimension mismatch errors** → Ensure `preprocessor_global.joblib` matches training data features
- **Election loops** → If aggregator crashes repeatedly, `role_supervisor.py` reverts to agent after 3 failures
- **Stale aggregator** → DB cleanup happens on new elections; manually clear: `DELETE FROM current_aggregator WHERE id=1`
- **Timeout de agregación** → Si los nodos son lentos, aumentar `aggregation_timeout` (default 120s → 180s o 300s)

**📚 Ver guía completa:** `MANEJO_ERRORES.md` para diagnóstico detallado, configuración por escenario y solución de problemas

## File Naming Conventions

- `*_th.py` suffixes indicate threaded/async components (e.g., `server_th.py`)
- `.binaryfile` extension for serialized models in `db/models/` (SHA256 hash filenames)
- Config files always in `setups/` directory
- Startup scripts always named `start.sh` in `scripts/`
