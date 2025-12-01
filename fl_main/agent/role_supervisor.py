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

CLIENT_MODULE = ['python3', '-m', 'fl_main.examples.image_classification.classification_engine']
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
        # Start aggregator server
        print(f"role_supervisor: role is 'aggregator', starting aggregator...")
        try:
            proc = subprocess.run(AGG_MODULE)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"role_supervisor: aggregator run failed: {e}")
            time.sleep(1)
        # After aggregator exits, loop back to check role again
        time.sleep(0.5)
        continue

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
