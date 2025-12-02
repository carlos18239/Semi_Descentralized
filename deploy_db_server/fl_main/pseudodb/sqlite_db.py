import sqlite3
import datetime
import logging

# Message type between aggregators and DB
from fl_main.lib.util.states import ModelType

class SQLiteDBHandler:
    """
        SQLiteDB Handler class that creates and initialize SQLite DB,
        and inserts models to the SQLiteDB
    """

    def __init__(self, db_file):
        self.db_file = db_file

    def initialize_DB(self):
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS local_models(
                        model_id TEXT,
                        generation_time TEXT,
                        agent_id TEXT,
                        round INTEGER,
                        performance REAL,
                        num_samples INTEGER)''')

        c.execute('''CREATE TABLE IF NOT EXISTS cluster_models(
                        model_id TEXT,
                        generation_time TEXT,
                        aggregator_id TEXT,
                        round INTEGER,
                        num_samples INTEGER)''')

        c.execute('''CREATE TABLE IF NOT EXISTS agents(
                        agent_id TEXT PRIMARY KEY,
                        ip TEXT,
                        socket INTEGER,
                        score INTEGER,
                        last_seen TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS current_aggregator(
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        aggregator_id TEXT,
                        ip TEXT,
                        socket INTEGER,
                        updated_at TEXT)''')

        conn.commit()
        conn.close()

    def insert_an_entry(self,
                         component_id: str,
                         r: int,
                         mt: ModelType,
                         model_id: str,
                         gtime: float,
                         local_prfmc: float,
                         num_samples: int
                        ):

        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        t = datetime.datetime.fromtimestamp(gtime)
        gene_time = t.strftime('%m/%d/%Y %H:%M:%S')

        if mt == ModelType.local:
            c.execute('''INSERT INTO local_models VALUES (?, ?, ?, ?, ?, ?);''', (model_id, gene_time, component_id, r, local_prfmc, num_samples))
            logging.info(f"--- Local Models are saved ---")

        elif mt == ModelType.cluster:
            c.execute('''INSERT INTO cluster_models VALUES (?, ?, ?, ?, ?);''', (model_id, gene_time, component_id, r, num_samples))
            logging.info(f"--- Cluster Models are saved ---")

        else:
            logging.info(f"--- Nothing saved ---")

        conn.commit()
        conn.close()
    
    def get_max_round(self, model_type: ModelType) -> int:

        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        # Elegimos tabla según tipo de modelo
        if model_type == ModelType.local:
            table = "local_models"
        elif model_type == ModelType.cluster:
            table = "cluster_models"
        else:
            logging.warning("ModelType desconocido al pedir max round, se usa 0.")
            conn.close()
            return 0

        try:
            c.execute(f"SELECT MAX(round) FROM {table}")
            row = c.fetchone()
        except Exception as e:
            logging.error(f"Error leyendo MAX(round) de {table}: {e}")
            conn.close()
            return 0

        conn.close()

        # row[0] será None si no hay datos
        if row is None or row[0] is None:
            return 0
        return int(row[0])
    
    def upsert_agent(self, agent_id: str, ip: str, socket: int, score: int = 50):
        """
        Inserta o actualiza un agente con su ip, puerto (socket) y score.
        Si el agent_id ya existe, actualiza ip, socket, score y last_seen.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        now = datetime.datetime.utcnow().isoformat()

        try:
            # First, check whether there is already a row for this (ip, socket).
            # If so, update that row's agent_id to avoid creating duplicate
            # entries when an agent restarts and generates a new id but keeps
            # the same network address.
            c.execute('SELECT agent_id FROM agents WHERE ip = ? AND socket = ?;', (ip, socket))
            row = c.fetchone()
            if row is not None:
                existing_id = row[0]
                if existing_id != agent_id:
                    # Update the existing record with the new agent_id, score and last_seen
                    c.execute('''
                        UPDATE agents SET agent_id = ?, last_seen = ?, ip = ?, socket = ?, score = ?
                        WHERE ip = ? AND socket = ?;
                    ''', (agent_id, now, ip, socket, score, ip, socket))
                    conn.commit()
                    logging.info(f"upsert_agent: updated existing row for ip={ip}, socket={socket} -> agent_id={agent_id}, score={score}")
                    return True

            # Otherwise, perform insert with upsert on agent_id (existing behaviour)
            c.execute('''
                INSERT INTO agents(agent_id, ip, socket, score, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    ip = excluded.ip,
                    socket = excluded.socket,
                    score = excluded.score,
                    last_seen = excluded.last_seen;
            ''', (agent_id, ip, socket, score, now))
            conn.commit()
            return True
        except Exception as e:
            logging.error(f"Error en upsert_agent para {agent_id}: {e}")
            return False
        finally:
            try:
                conn.close()
            except:
                pass

    def get_all_agents(self):
        """
        Devuelve una lista de (agent_id, ip, socket) para todos los agentes
        registrados en la tabla agents.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        try:
            c.execute('SELECT agent_id, ip, socket FROM agents')
            rows = c.fetchall()
        except Exception as e:
            logging.error(f"Error leyendo agentes desde DB: {e}")
            rows = []
        finally:
            conn.close()

        return rows

    def cleanup_old_agents(self, ttl_seconds: int):
        """
        Elimina agentes cuya columna `last_seen` sea anterior a (UTC now - ttl_seconds).
        Esta función ayuda a quitar entradas stale de la tabla `agents`.
        :param ttl_seconds: Tiempo de vida (segundos). Las entradas más viejas serán borradas.
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()

            cutoff = (datetime.datetime.utcnow() - datetime.timedelta(seconds=int(ttl_seconds))).isoformat()

            # Delete rows where last_seen is NULL or older than cutoff
            c.execute("DELETE FROM agents WHERE last_seen IS NULL OR last_seen < ?;", (cutoff,))
            deleted = c.rowcount
            conn.commit()
            # Reduce log noise: only INFO if something was deleted, otherwise DEBUG
            if deleted > 0:
                logging.info(f"SQLiteDBHandler: cleanup_old_agents removed {deleted} stale agents older than {ttl_seconds}s")
            else:
                logging.debug(f"SQLiteDBHandler: cleanup_old_agents found 0 stale agents (ttl={ttl_seconds}s)")
        except Exception as e:
            logging.error(f"Error during cleanup_old_agents: {e}")
        finally:
            try:
                conn.close()
            except:
                pass
    
    def get_all_agents(self):
        """
        Obtiene todos los agentes registrados en la tabla agents con sus scores.
        :return: Lista de tuplas (agent_id, ip, socket, score)
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("SELECT agent_id, ip, socket, score FROM agents")
            rows = c.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logging.error(f"Error retrieving agents: {e}")
            return []
    
    def update_current_aggregator(self, aggregator_id: str, ip: str, socket: int):
        """
        Update the current active aggregator in DB (for agent discovery after rotation)
        :param aggregator_id: ID of the current aggregator
        :param ip: IP address of the aggregator
        :param socket: Port number of the aggregator
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            # Use INSERT OR REPLACE to ensure only one row exists
            c.execute('''INSERT OR REPLACE INTO current_aggregator (id, aggregator_id, ip, socket, updated_at)
                         VALUES (1, ?, ?, ?, ?)''', (aggregator_id, ip, socket, now))
            conn.commit()
            logging.info(f"Updated current aggregator: {aggregator_id} at {ip}:{socket}")
        except Exception as e:
            logging.error(f"Error updating current aggregator: {e}")
        finally:
            conn.close()
    
    def get_current_aggregator(self):
        """
        Get the current active aggregator from DB
        :return: tuple (aggregator_id, ip, socket) or None if not found
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        
        try:
            c.execute('SELECT aggregator_id, ip, socket FROM current_aggregator WHERE id = 1')
            row = c.fetchone()
            conn.close()
            
            if row:
                return row  # (aggregator_id, ip, socket)
            else:
                return None
        except Exception as e:
            logging.error(f"Error getting current aggregator: {e}")
            conn.close()
            return None
    
    def clear_current_aggregator(self):
        """
        Clear the current aggregator entry from DB.
        Used when detecting a stale/unreachable aggregator.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        
        try:
            c.execute('DELETE FROM current_aggregator WHERE id = 1')
            conn.commit()
            logging.info("Cleared current aggregator from DB")
        except Exception as e:
            logging.error(f"Error clearing current aggregator: {e}")
        finally:
            conn.close()

