# Semi-Decentralized Federated Learning - Deployment Guide

## Architecture Overview

This system implements **semi-decentralized federated learning** with **dynamic aggregator election**:

- ✅ **No dedicated aggregator** - All nodes start as agents
- ✅ **First node auto-promotes** - Becomes aggregator if none exists
- ✅ **Rotation** - Aggregator role rotates every N rounds
- ✅ **Centralized DB** - Single PseudoDB server for persistence (your PC)
- ✅ **Stateless aggregators** - No local DB files on Raspberry Pis

## Network Setup

### Components

| Component | Device | IP Address | Purpose |
|-----------|--------|------------|---------|
| PseudoDB | Your PC (r0) | 172.23.211.109:9017 | Centralized database |
| Node 1 | Raspberry Pi (r1) | 172.23.211.138:50001 | Agent/Aggregator |
| Node 2 | Raspberry Pi (r2) | 172.23.211.117:8765 | Agent/Aggregator |
| Node 3 | Raspberry Pi (r3) | 172.23.211.121:50003 | Agent/Aggregator |
| Node 4 | Raspberry Pi (r4) | 172.23.211.247:50004 | Agent/Aggregator |

## Quick Start (Fresh Federation)

### 1. On Your PC (DB Server)

```bash
# Navigate to repository
cd simple-fl

# Reset federation state (clears current_aggregator)
./scripts/reset_federation.sh

# Start PseudoDB server
python -m fl_main.pseudodb.pseudo_db
```

**Keep this running** - it's the centralized database server.

### 2. On Each Raspberry Pi (Parallel)

```bash
# Navigate to repository
cd simple-fl

# Make sure device config is set
# Run this ONCE per device to generate correct config:
./setups/setup_device_config.sh <r1|r2|r3|r4>

# Start federation node
./scripts/start_federation.sh
```

**What happens:**
- All nodes start as **agents**
- First node to connect becomes **aggregator automatically**
- Other nodes discover aggregator and join as agents
- Training starts when all agents connected

## How It Works

### Initial Aggregator Election

```
Time 0s: All nodes start as agents, try to connect to aggregator
         ↓
         No aggregator exists yet
         ↓
Time 5s: Node 1 reaches connection timeout, PROMOTES itself
         ↓
         Node 1 becomes Aggregator, writes to config
         ↓
         role_supervisor restarts Node 1 as Aggregator
         ↓
Time 10s: Nodes 2,3,4 discover Node 1 as aggregator
         ↓
         Training begins
```

### Rotation Process

```
Round 1: Node 1 is aggregator
         ↓
Round 4: Rotation triggered (rotation_interval=3)
         ↓
         Random election: Node 3 wins
         ↓
         ALL nodes receive rotation message
         ↓
         All processes exit (os._exit(0))
         ↓
         role_supervisors restart appropriate role
         ↓
Round 5: Node 3 is now aggregator
         ↓
         Training continues...
```

## Configuration

### Per-Device Setup

Each Raspberry Pi MUST have its own `device_ip` configured. Use the setup script:

```bash
# On r1 (172.23.211.138)
./setups/setup_device_config.sh r1

# On r2 (172.23.211.117)  
./setups/setup_device_config.sh r2

# On r3 (172.23.211.121)
./setups/setup_device_config.sh r3

# On r4 (172.23.211.247)
./setups/setup_device_config.sh r4
```

This sets the correct `device_ip`, `reg_socket`, and `agent_name` in both:
- `setups/config_agent.json`
- `setups/config_aggregator.json`

### Key Parameters

**`setups/config_aggregator.json`:**
```json
{
  "rotation_min_rounds": 1,        // Allow rotation after round 1
  "rotation_interval": 3,          // Rotate every 3 rounds (1,4,7,10...)
  "rotation_delay": 20,            // Wait 20s before activating rotation
  "aggregation_threshold": 1.0,    // STRICT: require ALL agents (100%)
  "aggregation_timeout": 120,      // Wait max 2min for models
  "max_rounds": 100,               // Terminate after 100 rounds
  "early_stopping_patience": 120,  // Stop if no improvement for 120 rounds
  "agent_ttl_seconds": 600         // Agent considered stale after 10min
}
```

## Monitoring

### Check Federation Status

```bash
# Shows current aggregator, registered agents, training progress
python scripts/check_federation_status.py
```

Example output:
```
============================================================
🔍 FEDERATION STATUS
============================================================

📡 Current Aggregator:
------------------------------------------------------------
  ID:      e7a3f9b1...
  Address: 172.23.211.138:50001
  Updated: 2025-12-01 15:30:45

👥 Registered Agents:
------------------------------------------------------------
  a1b2c3d4...  172.23.211.138:50001  (last seen: 2025-12-01 15:35:12)
  e5f6g7h8...  172.23.211.121:50003  (last seen: 2025-12-01 15:35:11)
  i9j0k1l2...  172.23.211.247:50004  (last seen: 2025-12-01 15:35:10)

  Total: 3 agents

📊 Training Progress:
------------------------------------------------------------
  Latest round: 7
  Recent activity:
    Round 7: 3 local models
    Round 6: 3 local models
    Round 5: 3 local models
============================================================
```

### Check Logs

**Aggregator logs (current aggregator node):**
```bash
tail -f /tmp/aggregator.log
```

**Agent logs (on each node):**
```bash
tail -f /tmp/agent_<name>.log
```

### Metrics CSV Files

Training metrics are saved in `./metrics/`:
- `metrics_aggregator.csv` - Global metrics (aggregator only)
- `metrics_a1.csv` - Agent a1 metrics
- `metrics_a3.csv` - Agent a3 metrics  
- `metrics_a4.csv` - Agent a4 metrics

Each CSV contains:
```
round,accuracy,precision,recall,f1_score,loss,training_time,num_samples,bytes_sent,bytes_received,models_aggregated,global_recall,local_recall
```

## Troubleshooting

### "No response from aggregator after retries"

**Cause:** No aggregator exists yet, or aggregator not reachable.

**Solution:** 
1. Check if any node promoted itself to aggregator: `python scripts/check_federation_status.py`
2. If no aggregator, manually promote first node to start federation
3. Check network connectivity between nodes

### "Aggregation Threshold: 1.0 (need 3/3 agents)"

**Cause:** Strict threshold requires ALL agents to submit models before aggregation.

**Solution:**
- This is CORRECT behavior for threshold=1.0
- Wait for all agents to connect
- If an agent is stuck, check its logs
- Consider lowering threshold to 0.75 (75%) if you want partial aggregation

### "Database architecture" - Multiple DB files

**Cause:** Old code created local DB files on each Raspberry Pi.

**Solution:**
```bash
# On each Raspberry Pi, remove stale DB files
rm -rf ./db/sample_data.db

# Only the PseudoDB server (your PC) should have ./db/sample_data.db
```

### Rotation stuck / not happening

**Check:**
1. Current round >= `rotation_min_rounds` (default: 1)
2. Round is at rotation boundary: `(round - rotation_min_rounds) % rotation_interval == 0`
3. With defaults: rotation at rounds 1, 4, 7, 10, ...
4. Check aggregator logs for rotation messages

### All agents have identical metrics

**Cause:** Data not partitioned - all agents training on same data.

**Solution:** Already fixed in current version. Each agent gets unique data subset:
- Agent a1: CIFAR-10 samples 0-12,499
- Agent a2: CIFAR-10 samples 12,500-24,999  
- Agent a3: CIFAR-10 samples 25,000-37,499
- Agent a4: CIFAR-10 samples 37,500-49,999

### Model accuracy stuck at 10%

**Cause:** Old training loop used random sparse batches.

**Solution:** Already fixed. Training now uses consecutive batches for proper convergence.

## Advanced: Manual Aggregator Promotion

If automatic promotion fails, you can manually promote a node:

```bash
# On the node you want to be aggregator (e.g., r1)
cd simple-fl

# Edit config
python3 << EOF
import json
with open('setups/config_agent.json', 'r') as f:
    cfg = json.load(f)
cfg['role'] = 'aggregator'
with open('setups/config_agent.json', 'w') as f:
    json.dump(cfg, f, indent=2)
EOF

# Restart (role_supervisor will start aggregator)
pkill -f role_supervisor
./scripts/start_federation.sh
```

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Your PC (DB Server)                     │
│                                                             │
│  PseudoDB Server (172.23.211.109:9017)                     │
│  ├─ SQLite Database (./db/sample_data.db)                  │
│  ├─ Model Storage (./db/models/)                           │
│  └─ Tables: agents, current_aggregator, *_models           │
│                                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ WebSocket (model push, queries)
                         │
        ┌────────────────┴────────────────────┐
        │                                     │
┌───────▼──────────┐              ┌──────────▼────────┐
│ Raspberry Pi r1  │              │  Raspberry Pi r3  │
│ (Node 1)         │              │  (Node 3)         │
│                  │              │                   │
│ role_supervisor  │              │  role_supervisor  │
│ ├─ Agent (init)  │◄────────────►│  ├─ Agent (init) │
│ └─ Aggregator    │   Rotation   │  └─ Aggregator   │
│    (after elect) │   Messages   │     (after elect)│
└──────────────────┘              └───────────────────┘
        │                                     │
        │         ┌──────────────────┐        │
        └────────►│ Raspberry Pi r2  │◄───────┘
        │         │ (Node 2)         │        │
        │         │                  │        │
        │         │ role_supervisor  │        │
        │         │ └─ Agent         │        │
        │         └──────────────────┘        │
        │                  │                  │
        │         ┌────────▼────────┐         │
        └────────►│ Raspberry Pi r4 │◄────────┘
                  │ (Node 4)        │
                  │                 │
                  │ role_supervisor │
                  │ └─ Agent        │
                  └─────────────────┘
```

## Files and Directories

```
simple-fl/
├── scripts/
│   ├── start_federation.sh         # Start a federation node
│   ├── reset_federation.sh         # Clear federation state (DB server)
│   └── check_federation_status.py  # Query federation status
├── setups/
│   ├── setup_device_config.sh      # Generate device-specific configs
│   ├── config_agent.json           # Agent configuration
│   ├── config_aggregator.json      # Aggregator configuration
│   └── config_db.json              # Database configuration
├── fl_main/
│   ├── agent/
│   │   ├── client.py               # Agent client logic
│   │   └── role_supervisor.py      # Supervisor (agent↔aggregator)
│   ├── aggregator/
│   │   └── server_th.py            # Aggregator server (stateless)
│   ├── pseudodb/
│   │   ├── pseudo_db.py            # PseudoDB server
│   │   └── sqlite_db.py            # SQLite operations
│   └── examples/
│       └── image_classification/   # CIFAR-10 training example
├── data/
│   └── agents/                     # Per-agent local state
│       ├── a1/                     # lms.binaryfile, gms.binaryfile, state
│       ├── a3/
│       └── a4/
├── metrics/                        # Training metrics CSVs
└── db/                             # Database (PseudoDB server only!)
    ├── sample_data.db              # SQLite database
    └── models/                     # Serialized model files
```

## References

- **Rotation Details**: See `.github/copilot-instructions.md`
- **Device Setup**: Each device needs unique `device_ip` configured
- **Data Partitioning**: Each agent trains on non-overlapping CIFAR-10 subset
- **Termination**: Training stops at `max_rounds` OR early stopping triggered

---

**Last Updated:** December 1, 2025
