#!/usr/bin/env python3
"""
Supervisor for running classification_engine on edge devices (Raspberry Pi).
It starts the classification process and monitors `setups/config_agent.json`.
If this node is promoted to aggregator (role == 'aggregator'), the supervisor
stops the classifier and execs the aggregator (`fl_main.aggregator.server_th`).

Usage: python3 -m fl_main.agent.role_supervisor_classification [sim_flag] [exch_socket] [agent_name]

This mirrors the CLI args expected by `classification_engine` so the supervisor
passes them through.
"""
import time
import os
import sys
import subprocess
import logging

from fl_main.lib.util.helpers import set_config_file, read_config


def read_role():
    try:
        cfg = read_config(set_config_file('agent'))
        return cfg.get('role', 'agent')
    except Exception:
        return 'agent'


def main():
    logging.basicConfig(level=logging.INFO)

    # CLI args are passed to the classification engine
    args = sys.argv[1:]
    cmd = [sys.executable, '-m', 'fl_main.examples.image_classification.classification_engine'] + args

    logging.info(f"Starting classification engine: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)

    try:
        while True:
            time.sleep(2)
            role = read_role()
            if role == 'aggregator':
                logging.info('Role changed to aggregator — promoting this node')
                # terminate classifier
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

                # Exec the aggregator replacing this process
                logging.info('Execing aggregator: fl_main.aggregator.server_th')
                os.execvp(sys.executable, [sys.executable, '-m', 'fl_main.aggregator.server_th'])
            # otherwise continue supervising
    except KeyboardInterrupt:
        logging.info('Supervisor interrupted, stopping child')
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == '__main__':
    main()
