#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from fl_main.lib.util.helpers import set_config_file, read_config

# Usage: role_supervisor_aggregator.py <simulation_flag> <port> <agent_name>
# It runs the aggregator server. If the server exits and the
# config `role` becomes 'agent', the supervisor will exec the agent
# client with the provided args. Otherwise it restarts the aggregator.

AGG_MODULE = ['python3', '-m', 'fl_main.aggregator.server_th']
CLIENT_MODULE = ['python3', '-m', 'fl_main.agent.client']

# Store client args from command line (for when we need to switch to agent)
if len(sys.argv) >= 4:
    client_args = sys.argv[1:4]  # [simulation_flag, port, agent_name]
else:
    # Default fallback
    client_args = ['1', '50001', 'agent_default']
    print(f"role_supervisor_aggregator: Using default client args: {client_args}")

while True:
    # read role
    try:
        cfg_file = set_config_file('aggregator')
        cfg = read_config(cfg_file)
        role = cfg.get('role', 'aggregator')
    except Exception:
        role = 'aggregator'

    if role == 'agent':
        # Switch to agent client
        print(f"role_supervisor_aggregator: role is 'agent', switching to client with args {client_args}...")
        os.execvp(CLIENT_MODULE[0], CLIENT_MODULE + client_args)

    # run the aggregator (blocking)
    try:
        print("role_supervisor_aggregator: Starting aggregator...")
        proc = subprocess.run(AGG_MODULE)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        # Sleep and retry on unexpected errors
        print(f"role_supervisor_aggregator: aggregator run failed: {e}")
        time.sleep(1)
        continue

    # aggregator exited; re-check role and loop. If the aggregator demoted itself it
    # should have written role='agent' into the config, so the next loop
    # will exec the client.
    time.sleep(0.5)
