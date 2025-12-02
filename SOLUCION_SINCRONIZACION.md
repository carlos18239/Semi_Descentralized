# Solución: Problema de Sincronización en Rotación de Agregador

## 🔴 Problema Detectado (2025-12-02)

### Síntomas Observados
```
12:15:28 - Aggregator started (172.23.211.138)
12:15:29 - Agent 6209a5f3... registered (121)
12:15:38 - Round 1: 1/4 agents ← ¡SOLO 1 AGENTE!
12:15:49 - Round 2: 1/4 agents
12:15:49 - 🔄 Rotation at round 3 ← ¡DEMASIADO PRONTO!
---
17:13:29 - New aggregator started (172.23.211.117)
17:13:34 - Esperando modelos de 0 agentes... ← ¡VACÍO!
17:15:34 - TIMEOUT (120s)
17:15:34 - ERROR: No hay modelos
```

### Causas Raíz

#### 1. **Rotación Prematura**
- Configuración: `rotation_interval = 3` (cada 3 rondas)
- Agregador rotaba después de **solo 2 rondas**
- No daba tiempo a que todos los agentes se registren

#### 2. **Agregador Sin Agentes**
- Nuevo agregador arrancaba sin conocer agentes previos
- Agentes intentaban conectarse al agregador viejo (ya desconectado)
- No había mecanismo de re-registro automático

#### 3. **Pérdida de Conexión**
```
17:14:09 - Found aggregator: 172.23.211.138
17:14:09 - ERROR: Connection lost to 172.23.211.138 ← Ya rotó!
17:14:24 - ERROR: Connection lost (attempt 6)
```

#### 4. **Falta de Quórum**
- Agregador intentaba agregar con 0 agentes
- No había verificación de número mínimo de participantes

## ✅ Solución Implementada

### Cambios en Configuración (`config_agent.json`)
```json
{
  "rotation_interval": 10,             // Aumentado de 3 → 10 rondas
  "min_agents_for_aggregation": 1,     // NUEVO: Quórum mínimo
  "registration_grace_period": 30,     // Período de registro inicial
  "aggregation_timeout": 120,          // Timeout para modelos
  "rotation_delay": 60                 // Delay antes de rotación
}
```

### Cambios en Código (`server_th.py`)

#### 1. Verificación de Quórum
```python
# ANTES: Agregaba inmediatamente si había modelos
if self.sm.ready_for_local_aggregation():
    logging.info(f'Round {self.sm.round}')

# DESPUÉS: Verifica quórum primero
num_registered_agents = len(self.sm.agent_set)
if num_registered_agents < self.min_agents_for_aggregation:
    logging.warning(f'⏳ Esperando quórum: {num_registered_agents}/{self.min_agents_for_aggregation}')
    continue
```

#### 2. Logging Detallado de Rotación
```python
# ANTES: Log simple
logging.info(f"🔄 Initiating rotation at round {self.sm.round}")

# DESPUÉS: Información completa
rounds_since_last_rotation = self.sm.round - self.last_rotation_round
logging.info(f"🔄 Iniciando rotación en ronda {self.sm.round}")
logging.info(f"   Última rotación: ronda {self.last_rotation_round} ({rounds_since_last_rotation} rondas atrás)")
logging.info(f"   Agentes activos: {len(self.sm.agent_set)}")
```

#### 3. Control de Frecuencia
```python
# ANTES: Rotación cada 3 rondas (hardcoded)
rotation_interval = 3

# DESPUÉS: Configurable con default 10
self.rotation_interval = int(self.config.get('rotation_interval', 10))
```

## 📊 Comparativa Antes/Después

| Aspecto | Antes | Después |
|---------|-------|---------|
| **Rondas entre rotaciones** | 3 | 10 (configurable) |
| **Verificación de quórum** | ❌ No | ✅ Sí (`min_agents_for_aggregation`) |
| **Logging de rotación** | Básico | Detallado (rounds, agentes, timing) |
| **Rotación de 4 agentes** | ~15s (3 rounds × 5s) | ~50s (10 rounds × 5s) |

## 🚀 Cómo Usar

### Escenario 1: Sistema con 4 Nodos Estables
```json
{
  "rotation_interval": 10,            // Suficiente tiempo para 10 rondas
  "min_agents_for_aggregation": 4,    // Requiere todos los agentes
  "aggregation_timeout": 60           // Rápido si todos responden
}
```

### Escenario 2: Sistema con Nodos Dinámicos
```json
{
  "rotation_interval": 5,             // Rotaciones más frecuentes
  "min_agents_for_aggregation": 2,    // Quórum = mayoría de 4
  "aggregation_timeout": 180          // Timeout largo para esperar rezagados
}
```

### Escenario 3: Pruebas Rápidas
```json
{
  "rotation_interval": 3,             // Rotación cada 3 rondas
  "min_agents_for_aggregation": 1,    // Solo 1 agente requerido
  "aggregation_timeout": 30           // Timeout corto
}
```

## 🔍 Verificación

### Logs Esperados (Sistema Saludable)
```
12:11:13 - Pseudo DB Server Started
12:11:37 - Agent registration: 94a5ee00... (score: 98) ✓
12:11:39 - Agent registration: 091bd7a8... (score: 4)  ✓
12:11:41 - Agent registration: f5c4b9e8... (score: 86) ✓
12:11:42 - Agent registration: 23b5c443... (score: 92) ✓
12:12:09 - 🏆 Ganador: 94a5ee00... con 98 puntos ✓
---
12:15:29 - Agent 6209a5f3... registered ✓
12:15:38 - Round 1: 1 agent ← CORRECTO para este caso
12:15:49 - Round 2: 1 agent
...
12:XX:XX - Round 10: 1 agent
12:XX:XX - 🔄 Iniciando rotación en ronda 11 ← ¡DESPUÉS DE 10 RONDAS!
12:XX:XX -    Última rotación: ronda 1 (10 rondas atrás)
12:XX:XX -    Agentes activos: 1
```

### Comandos de Diagnóstico
```bash
# Ver agentes registrados en DB
sqlite3 deploy_db_server/db/sample_data.db \
  "SELECT substr(agent_id,1,8), ip, score FROM agents ORDER BY score DESC;"

# Monitorear logs de agregador en tiempo real
tail -f deploy_node/logs/aggregator.log | grep -E "Rotación|Round|agentes"

# Verificar configuración actual
jq '.rotation_interval, .min_agents_for_aggregation' deploy_node/setups/config_agent.json
```

## ⚠️ Problemas Conocidos (Pendientes)

### 1. Re-Conexión Post-Rotación
**Estado**: Parcialmente resuelto
- Agentes detectan agregador caído y re-eligen
- **Falta**: Mecanismo automático de broadcast a todos los agentes

### 2. Historial de Agentes
**Estado**: No implementado
- Nuevo agregador no conoce agentes previos
- **Solución propuesta**: Persistir agentes en DB, no solo en memoria

### 3. Handoff de Estado
**Estado**: No implementado
- Nuevo agregador arranca desde round 0
- **Solución propuesta**: Transferir estado (round, métricas) vía DB

## 📚 Referencias

- **Archivo de configuración**: `deploy_node/setups/config_agent.json`
- **Lógica de rotación**: `deploy_node/fl_main/aggregator/server_th.py:550-580`
- **Detección de agregador**: `deploy_node/fl_main/agent/client.py:participate()`
- **Guía de errores**: `MANEJO_ERRORES.md` - Error 4 (Rotación)

---
**Fecha**: 2025-12-02  
**Versión**: 1.0  
**Autor**: GitHub Copilot
