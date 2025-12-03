#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import signal
from fl_main.lib.util.helpers import set_config_file, read_config

# Usage: role_supervisor.py [<client args>...]
# It runs the agent client with provided args. If the client exits and the
# config `role` becomes 'aggregator', the supervisor will exec the aggregator
# server (replacing itself). Otherwise it restarts the client.

# Motor de clasificación tabular para datos de defunciones hospitalarias
# Usar conda run para ejecutar en el entorno correcto
CLIENT_MODULE = ['conda', 'run', '-n', 'federatedenv2', '--no-capture-output', 'python3', '-m', 'fl_main.examples.tabular_ncd.tabular_engine']
AGG_MODULE = ['conda', 'run', '-n', 'federatedenv2', '--no-capture-output', 'python3', '-m', 'fl_main.aggregator.server_th']

client_args = sys.argv[1:]

# Contador de errores consecutivos para evitar loop infinito
agg_error_count = 0
MAX_AGG_ERRORS = 3

def kill_port_processes(ports):
    """Matar procesos que estén usando los puertos especificados"""
    for port in ports:
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            print(f"role_supervisor: killed process {pid} on port {port}")
                        except:
                            pass
        except:
            pass

while True:
    # read role
    try:
        cfg_file = set_config_file('agent')
        cfg = read_config(cfg_file)
        role = cfg.get('role', 'agent')
    except Exception:
        role = 'agent'

    if role == 'aggregator':
        # Verificar contador de errores
        if agg_error_count >= MAX_AGG_ERRORS:
            print(f"role_supervisor: aggregator failed {MAX_AGG_ERRORS} times, reverting to agent role...")
            # Revertir a agent
            try:
                cfg['role'] = 'agent'
                cfg['aggr_ip'] = ''
                import json
                with open(cfg_file, 'w') as f:
                    json.dump(cfg, f, indent=2)
            except:
                pass
            agg_error_count = 0
            time.sleep(2)
            continue
        
        # Matar procesos anteriores en los puertos del aggregator
        kill_port_processes([4321, 7890, 8765])
        time.sleep(1)
        
        # Start aggregator server
        print(f"role_supervisor: role is 'aggregator', starting aggregator...")
        try:
            proc = subprocess.run(AGG_MODULE)
            if proc.returncode != 0:
                agg_error_count += 1
                print(f"role_supervisor: aggregator exited with code {proc.returncode} (error {agg_error_count}/{MAX_AGG_ERRORS})")
            else:
                agg_error_count = 0  # Reset on success
        except KeyboardInterrupt:
            raise
        except Exception as e:
            agg_error_count += 1
            print(f"role_supervisor: aggregator run failed: {e} (error {agg_error_count}/{MAX_AGG_ERRORS})")
        
        # After aggregator exits, wait before retry
        time.sleep(2)
        continue

    # Reset error count when in agent mode
    agg_error_count = 0

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
