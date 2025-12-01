#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from fl_main.lib.util.helpers import set_config_file, read_config

# Usage: role_supervisor.py [<client args>...]
# It runs the agent client with provided args. If the client exits and the
# config `role` becomes 'aggregator', the supervisor will exec the aggregator
# server (replacing itself). Otherwise it restarts the client.

CLIENT_MODULE = ['python3', '-m', 'fl_main.agent.client']
AGG_MODULE = ['python3', '-m', 'fl_main.aggregator.server_th']

client_args = sys.argv[1:]

while True:
    # read role
    try:
        cfg_file = set_config_file('agent')
        cfg = read_config(cfg_file)
        role = cfg.get('role', 'agent')
    except Exception:
        role = 'agent'

    if role == 'aggregator':
        # replace this process with the aggregator server
        os.execvp(AGG_MODULE[0], AGG_MODULE + [])

    # run the client (blocking)
    try:
        proc = subprocess.run(CLIENT_MODULE + client_args)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        # Sleep and retry on unexpected errors
        print(f"role_supervisor: client run failed: {e}")
        time.sleep(1)
        continue

    # client exited; re-check role and loop. If the client promoted itself it
    # should have written role='aggregator' into the config, so the next loop
    # will exec the aggregator.
    time.sleep(0.5)
