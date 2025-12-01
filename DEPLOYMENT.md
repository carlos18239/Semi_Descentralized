# Deployment Guide - Raspberry Pi Cluster

## Network Configuration
- **r1** (Agent a2): IP `172.23.198.229`, port `50002`
- **r2** (Aggregator inicial): IP `172.23.197.150`, port `8765`
- **r3** (Agent a3): IP `172.23.198.244`, port `50003`
- **PseudoDB**: IP `172.23.211.109`, port `9017`

## Configuration per Device

### r1 (172.23.198.229) - Agent a2

**setups/config_agent.json:**
```json
{
  "device_ip": "172.23.198.229",
  "aggr_ip": "172.23.197.150",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
```

**setups/config_aggregator.json:**
```json
{
  "device_ip": "172.23.198.229",
  "aggr_ip": "172.23.198.229",
  "db_ip": "172.23.211.109",
  "reg_socket": "50002",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator"
}
```

### r2 (172.23.197.150) - Aggregator inicial

**setups/config_agent.json:**
```json
{
  "device_ip": "172.23.197.150",
  "aggr_ip": "172.23.197.150",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
```

**setups/config_aggregator.json:**
```json
{
  "device_ip": "172.23.197.150",
  "aggr_ip": "172.23.197.150",
  "db_ip": "172.23.211.109",
  "reg_socket": "8765",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator"
}
```

### r3 (172.23.198.244) - Agent a3

**setups/config_agent.json:**
```json
{
  "device_ip": "172.23.198.244",
  "aggr_ip": "172.23.197.150",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
```

**setups/config_aggregator.json:**
```json
{
  "device_ip": "172.23.198.244",
  "aggr_ip": "172.23.198.244",
  "db_ip": "172.23.211.109",
  "reg_socket": "50003",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator"
}
```

## Deployment Steps

### 1. Start PseudoDB (cualquier máquina o servidor dedicado)
```bash
cd /path/to/simple-fl
python -m fl_main.pseudodb.pseudo_db
```

### 2. Start r2 as Initial Aggregator (con supervisor)
```bash
cd /path/to/simple-fl
# Asegúrate que config_aggregator.json tenga device_ip="172.23.197.150"
# El supervisor permite que el aggregator cambie a agent automáticamente
python -m fl_main.aggregator.role_supervisor 1 8765 a_aggregator
```

**Nota**: El supervisor del aggregator necesita los argumentos `<simulation_flag> <port> <agent_name>` para poder reiniciar como cliente si pierde la rotación.

### 3. Start r1 as Agent a2 (con supervisor)
```bash
cd /path/to/simple-fl
# Asegúrate que config_agent.json tenga device_ip="172.23.198.229"
python -m fl_main.agent.role_supervisor 1 50002 a2
```

### 4. Start r3 as Agent a3 (con supervisor)
```bash
cd /path/to/simple-fl
# Asegúrate que config_agent.json tenga device_ip="172.23.198.244"
python -m fl_main.agent.role_supervisor 1 50003 a3
```

## How Rotation Works

1. **Aggregation**: El aggregator recolecta modelos de los agentes y agrega cada `round_interval` segundos
2. **Rotation Decision**: Después de la agregación, el aggregator decide aleatoriamente si rotar basándose en scores
3. **Rotation Message**: El agregador guarda el mensaje de rotación en `pending_rotation_msg`
4. **Message Delivery**: Cuando **todos** los agentes registrados en la DB hacen polling, reciben el mensaje de rotación como prioridad
5. **Winner Promotion**: 
   - El agente ganador actualiza `config_agent.json` y `config_aggregator.json`
   - Cambia `role` a `"aggregator"`
   - Actualiza `aggr_ip` a su propio `device_ip`
   - Actualiza `reg_socket` al puerto específico del dispositivo
   - Llama `os._exit(0)` para que `role_supervisor` lo reinicie como aggregator
6. **Loser Update**:
   - Los agentes perdedores actualizan `self.aggr_ip` y `self.reg_socket` en memoria
   - Se reconectan al nuevo aggregator
   - Continúan operando como agentes
7. **Aggregator Demotion**:
   - Si el aggregator actual **no** ganó la rotación, después de notificar a todos los agentes:
     - Actualiza `config_aggregator.json` y `config_agent.json` cambiando `role` a `"agent"`
     - Actualiza `aggr_ip` y `reg_socket` para apuntar al nuevo aggregator
     - Llama `os._exit(0)` para que `role_supervisor` lo reinicie como cliente
   - Si el aggregator actual **sí** ganó la rotación:
     - Limpia el estado de rotación y continúa operando como aggregator

## Important Notes

- **CRITICAL**: Cada dispositivo DEBE tener su propio `device_ip` configurado correctamente
- **CRITICAL**: Usa `role_supervisor.py` (no ejecutes `client.py` directamente) para que la promoción automática funcione
- **Port Assignment**: Cada dispositivo debe tener un puerto único en `config_aggregator.json` → `reg_socket`
  - r1: `50002`
  - r2: `8765`
  - r3: `50003`
- El aggregator inicial (`r2`) usa puerto `8765`
- Cuando `r1` o `r3` se convierten en aggregator, usan sus puertos específicos (`50002` o `50003`)
- El código en `server_th.py` detectará automáticamente la IP del host si está mal configurada

## Configuration File Update During Rotation

Cuando un agente gana la rotación, el código automáticamente:
1. Lee `config_agent.json` y `config_aggregator.json`
2. Actualiza `role` a `"aggregator"` en `config_agent.json`
3. Actualiza `aggr_ip` a la IP del ganador en ambos archivos
4. Actualiza `reg_socket` al puerto del ganador en ambos archivos
5. Guarda los archivos de vuelta al disco
6. Llama `os._exit(0)` para reinicio

Cuando un agente pierde la rotación:
1. Actualiza `self.aggr_ip` y `self.reg_socket` en memoria
2. Continúa el loop de polling conectándose al nuevo aggregator

## Troubleshooting

### "Connection lost to the agent"
- Verifica que todos los dispositivos tengan `device_ip` configurado correctamente
- Verifica que el puerto en `reg_socket` sea único para cada dispositivo

### Agent no se convierte en aggregator después de ganar
- Asegúrate de usar `role_supervisor.py` en lugar de ejecutar `client.py` directamente
- Verifica que `config_agent.json` y `config_aggregator.json` tengan `device_ip` correcto

### Agents siguen conectándose al aggregator viejo
- Verifica que el código de `client.py` actualice `self.aggr_ip` después de recibir rotación
- Asegúrate de tener la última versión del código (`git pull`)

### "unable to open database file"
- El directorio `db/` se crea automáticamente ahora
- Ejecuta desde el directorio raíz del repositorio donde está `setups/`
