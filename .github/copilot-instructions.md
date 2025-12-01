# Copilot / AI Agent Instructions for Simple-FL

This file gives focused, actionable guidance for AI coding agents working in this repository.

High-level architecture
- **Components**: three core runtime roles: `Agent` (`fl_main/agent`), `Aggregator` (`fl_main/aggregator`), and `PseudoDB` (`fl_main/pseudodb`).
- **Message layer**: communication is implemented over WebSockets using pickled Python lists (`fl_main/lib/util/communication_handler.py`). Message field positions are defined in `fl_main/lib/util/states.py` and created by helper functions in `fl_main/lib/util/messengers.py`.
- **Data flow**: Agents send local models → Aggregator buffers them → Aggregator aggregates (FedAvg) → Aggregator pushes cluster model to PseudoDB and distributes to Agents. Rotation can promote an Agent to Aggregator.

Essential developer workflows (quick commands)
- Create environment (Linux):
```
conda env create -n federatedenv -f ./setups/federatedenv_linux.yaml
conda activate federatedenv
```
- Run servers (order matters):
```
# 1) Start DB
python -m fl_main.pseudodb.pseudo_db

# 2) Start Aggregator
python -m fl_main.aggregator.server_th

# 3) Start one or more Agents (or use the supervisor)
python -m fl_main.agent.role_supervisor    # preferred: restarts client, handles promotion
# or start client directly (simulation example):
python -m fl_main.agent.client 1 50001 a1
```
- Example minimal MLEngine (simulation):
```
python -m examples.minimal.minimal_MLEngine 1 50001 a1
```

Project-specific conventions & patterns
- Config files live in `setups/` and are loaded via `fl_main.lib.util.helpers.set_config_file()` which builds paths from the current working directory. Always run commands from the repository root.
- Model/state files: agent-local models and state files are saved under the path configured by `config_agent.json` (default `./data/agents/<agent_name>`). Filenames are `lms.binaryfile`, `gms.binaryfile`, and `state`.
- Message format: messages are plain Python lists pickled before sending. The code uses numeric index enums in `states.py` (e.g. `ParticipateMSGLocation`, `ModelUpMSGLocation`, `GMDistributionMsgLocation`). Do not change list order without updating both sender and receiver.
- ID generation: IDs and model IDs are SHA256 hashes (see `helpers.generate_id` & `generate_model_id`). They are non-deterministic in tests unless mocked.
- Atomic config writes: `helpers.write_config()` writes to a `.tmp` then renames — keep this behavior when changing config persistence.

Concurrency & networking notes
- Servers are asyncio-based using `websockets`. Server entrypoints use `communication_handler.init_fl_server/init_db_server/init_client_server`.
- Aggregator background tasks: `Server.model_synthesis_routine()` (periodic aggregation) and `_wait_for_agents_routine()` (attempts to connect agents saved in DB). Both are started as coroutines in `server_th.py`.
- Client uses threads to run an asyncio client loop (`init_loop`) and a background server for receiving global models (`init_client_server`). Be careful when modifying threading/loop interactions.

Important files to reference when changing functionality
- Core runtime: `fl_main/agent/client.py`, `fl_main/agent/role_supervisor.py`, `fl_main/aggregator/server_th.py`, `fl_main/pseudodb/pseudo_db.py`.
- Protocol & helpers: `fl_main/lib/util/states.py`, `fl_main/lib/util/messengers.py`, `fl_main/lib/util/communication_handler.py`, `fl_main/lib/util/helpers.py`, `fl_main/lib/util/data_struc.py`.
- Examples and ML integration: `examples/image_classification/` and `examples/minimal/`.

Testing and debugging tips specific to this repo
- When `communication_handler.send()` returns `None`, it means either there was no response or the connection failed — code frequently treats `None` as "no reply"; when debugging network issues, enable DEBUG logs and confirm socket/port values in `setups/config_*.json`.
- To simulate multiple agents on one machine, run multiple `examples.minimal.minimal_MLEngine` with different `gm_recv_port` and `agent_name` arguments.
- Rotation behavior: aggregator may `os._exit(0)` to yield the role; `role_supervisor.py` will restart appropriate process based on `role` in configs. Avoid in-place edits that assume the process remains running after rotation.
- **Database errors**: "unable to open database file" means the `db_data_path` directory (default `./db`) doesn't exist. The aggregator now auto-creates it, but ensure you run from repo root where `setups/config_*.json` are visible.

Guidance for AI code edits
- Prefer focused, minimal changes. This codebase relies on strict message ordering and pickled objects — refactors that change list orders/types must update both ends and `messengers.py` and `states.py` simultaneously.
- When adding new message fields, update both `messengers.generate_*` helpers and the corresponding `*MSGLocation` enum in `states.py`, and update all readers to use `int(...)` indexing as the codebase does.
- For changes to concurrency (async/threads), add tests exercising a real socket (local `websockets`) or a small integration run: start PseudoDB → Aggregator → Agent(s) in separate terminals or subprocesses.

If anything here is unclear or you'd like me to include more examples (e.g., a minimal unit test skeleton or CI commands), tell me what to expand.
