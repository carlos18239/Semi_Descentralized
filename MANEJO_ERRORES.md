# 🛡️ Guía de Manejo de Errores - Federated Learning

## ⏱️ Timeouts Configurados

### 📋 Resumen de Tiempos

| **Fase** | **Timeout** | **Propósito** | **Configurable en** |
|----------|-------------|---------------|---------------------|
| **Registro Inicial** | 30 segundos | Esperar que todos los nodos se registren | `registration_grace_period` |
| **Agregación de Modelos** | 120 segundos (2 min) | Esperar modelos locales de todos los nodos | `aggregation_timeout` |
| **Rotación de Agregador** | 60 segundos (1 min) | Dar tiempo antes de elegir nuevo agregador | `rotation_delay` |

---

## 🔄 Flujo Completo con Timeouts

```
┌──────────────────────────────────────────────────────────────┐
│  FASE 1: REGISTRO INICIAL (30 segundos)                     │
└──────────────────────────────────────────────────────────────┘
T=0s    🗄️  Servidor DB inicia
T=2s    🏥 Nodo A se registra → score=85
T=5s    🏥 Nodo B se registra → score=42
T=10s   🏥 Nodo C se registra → score=91
        ⏱️  [10s/30s] 3 agentes registrados (quedan 20s)
        
✅ SI expected_num_agents=3 → SALIDA TEMPRANA
❌ SI expected_num_agents=0 → ESPERA COMPLETA 30s

T=30s   ✅ Periodo de registro completado

┌──────────────────────────────────────────────────────────────┐
│  FASE 2: ELECCIÓN DE AGREGADOR (3 segundos)                 │
└──────────────────────────────────────────────────────────────┘
T=30s   🗳️  Elección con 3 agentes registrados
        📋 Candidatos: ['agent_1', 'agent_2', 'agent_3']
        🎲 Scores: {'agent_1': 85, 'agent_2': 42, 'agent_3': 91}
T=33s   🏆 Ganador: agent_3 (score: 91)
        🔄 agent_3 reinicia como agregador

┌──────────────────────────────────────────────────────────────┐
│  FASE 3: ENTRENAMIENTO Y AGREGACIÓN (120 segundos)          │
└──────────────────────────────────────────────────────────────┘
T=40s   📡 Agentes conectan al agregador
T=45s   🧠 Cada nodo inicia entrenamiento local

        ⏳ Esperando modelos de 3 agentes...
        ⏱️  Timeout máximo: 120s (2 minutos)

T=60s   📤 Nodo A envía modelo local (1/3)
        ⏱️  [15s] Modelos: 1/3 (quedan 105s)

T=75s   📤 Nodo B envía modelo local (2/3)
        ⏱️  [30s] Modelos: 2/3 (quedan 90s)

T=90s   📤 Nodo C envía modelo local (3/3)
        ✅ Suficientes modelos recolectados. ¡Iniciando agregación!

T=92s   🔄 FedAvg completado
        📊 Modelo global distribuido a todos

┌──────────────────────────────────────────────────────────────┐
│  ESCENARIO DE ERROR: UN NODO SE CUELGA                       │
└──────────────────────────────────────────────────────────────┘
T=60s   📤 Nodo A envía modelo (1/3)
T=75s   📤 Nodo B envía modelo (2/3)
T=90s   ⏱️  [45s] Modelos: 2/3 (quedan 75s)
T=120s  ⏱️  [75s] Modelos: 2/3 (quedan 45s)
T=150s  ⏱️  [105s] Modelos: 2/3 (quedan 15s)
T=165s  ⏱️  ¡TIMEOUT! Límite de 120s excedido
        ⏱️  Esperado: 3 modelos | Recibido: 2 modelos
        ⏱️  Tiempo total de espera: 125.3s
        ⚠️  Procediendo con AGREGACIÓN PARCIAL

T=167s  ✅ Agregación completada con 2/3 modelos
        📊 Modelo global distribuido
```

---

## 🚨 Errores Comunes y Soluciones

### Error 1: "No hay agentes registrados"

**Síntoma:**
```
❌ No se puede agregar: No hay agentes registrados en agent_set
```

**Causa:** Los nodos no se registraron en el servidor DB

**Solución:**
```bash
# 1. Verificar que el servidor DB esté corriendo
cd deploy_db_server
ps aux | grep pseudo_db

# 2. Verificar conectividad
ping <IP_SERVIDOR>

# 3. Revisar configuración de los nodos
cat deploy_node/setups/config_agent.json
# Verificar que db_ip y db_port sean correctos

# 4. Revisar logs del servidor DB
tail -f deploy_db_server/logs/*.log
```

---

### Error 2: "Timeout de agregación excedido"

**Síntoma:**
```
⏱️  ¡TIMEOUT! Límite de 120s excedido
⏱️  Esperado: 4 modelos | Recibido: 2 modelos
⚠️  Procediendo con AGREGACIÓN PARCIAL
```

**Causa:** Algunos nodos son lentos o se colgaron

**Solución 1 - Aumentar timeout:**
```json
// En config_agent.json
{
  "aggregation_timeout": 180  // 3 minutos en lugar de 2
}
```

**Solución 2 - Reducir threshold:**
```json
{
  "aggregation_threshold": 0.75  // Permitir 75% de nodos (3/4)
}
```

**Solución 3 - Identificar nodo lento:**
```bash
# Monitorear logs del agregador
cd deploy_node
tail -f logs/aggregator.log | grep "Modelo local recibido"

# Ver qué nodo NO envió su modelo
```

---

### Error 3: "Elección múltiple de agregadores"

**Síntoma:**
```
🗳️  Elección con 1 agentes registrados  # ⚠️ Debería ser más
⚠️  Solo 1 agentes registrados (mínimo: 2)
```

**Causa:** Los nodos no esperaron suficiente tiempo

**Solución:**
```json
// Aumentar periodo de gracia
{
  "registration_grace_period": 45,  // 45s en lugar de 30s
  "expected_num_agents": 4          // Especificar cantidad exacta
}
```

---

### Error 4: "Connection lost to agent"

**Síntoma:**
```
❌ Connection lost to the agent: 192.168.1.100
--- Message NOT Sent ---
```

**Causa:** Problemas de red o firewall

**Solución:**
```bash
# 1. Verificar firewall
sudo ufw status
sudo ufw allow 9017/tcp  # Puerto servidor
sudo ufw allow 4321/tcp  # Puerto nodos
sudo ufw allow 8765/tcp  # Puerto registro

# 2. Verificar conectividad directa
nc -zv 192.168.1.100 4321

# 3. Verificar que el nodo esté ejecutándose
ssh pi@192.168.1.100
ps aux | grep role_supervisor
```

---

### Error 5: "Dimension mismatch en modelos"

**Síntoma:**
```
RuntimeError: mat1 and mat2 shapes cannot be multiplied (32x20 and 25x120)
```

**Causa:** Preprocessors diferentes o datos con distintas features

**Solución:**
```bash
# 1. Verificar que TODOS usen el mismo preprocessor
md5sum deploy_node/artifacts/preprocessor_global.joblib
# Debe ser IDÉNTICO en todos los nodos

# 2. Si es diferente, copiar desde el servidor central
scp deploy_node/artifacts/preprocessor_global.joblib pi@nodo2:~/deploy_node/artifacts/
scp deploy_node/artifacts/preprocessor_global.joblib pi@nodo3:~/deploy_node/artifacts/

# 3. Reiniciar TODOS los nodos
./scripts/start.sh
```

---

## 📊 Configuración Recomendada por Escenario

### ⚡ Escenario 1: Red Rápida (LAN)
```json
{
  "expected_num_agents": 4,
  "registration_grace_period": 20,
  "election_min_agents": 3,
  "aggregation_timeout": 90,
  "aggregation_threshold": 1.0,
  "rotation_delay": 30
}
```
**Uso:** Desarrollo local, todos en misma red

---

### 🌐 Escenario 2: Red Lenta (WiFi/Internet)
```json
{
  "expected_num_agents": 0,
  "registration_grace_period": 45,
  "election_min_agents": 2,
  "aggregation_timeout": 180,
  "aggregation_threshold": 0.75,
  "rotation_delay": 60
}
```
**Uso:** Raspberry Pis distribuidas, conexión variable

---

### 🏥 Escenario 3: Producción Multi-Hospital
```json
{
  "expected_num_agents": 10,
  "registration_grace_period": 60,
  "election_min_agents": 8,
  "aggregation_timeout": 300,
  "aggregation_threshold": 0.8,
  "rotation_delay": 90
}
```
**Uso:** Despliegue real con alta disponibilidad

---

## 🔍 Monitoreo en Tiempo Real

### Ver logs de todos los componentes:

```bash
# Terminal 1: Servidor DB
cd deploy_db_server
tail -f logs/*.log 2>/dev/null || python3 -m fl_main.pseudodb.pseudo_db 2>&1 | tee logs/server.log

# Terminal 2: Nodo 1
cd deploy_node
tail -f logs/*.log 2>/dev/null || ./scripts/start.sh 2>&1 | tee logs/node1.log

# Terminal 3: Estado de la base de datos
watch -n 5 'sqlite3 deploy_db_server/db/sample_data.db "SELECT * FROM agents;" && echo "" && sqlite3 deploy_db_server/db/sample_data.db "SELECT * FROM current_aggregator;"'
```

---

## 🧪 Comandos de Diagnóstico

```bash
# 1. Verificar puertos en uso
sudo lsof -i -P -n | grep LISTEN | grep -E "4321|8765|9017"

# 2. Ver cantidad de modelos guardados
ls -lh deploy_db_server/db/models/*.binaryfile | wc -l

# 3. Consultar último modelo en DB
sqlite3 deploy_db_server/db/sample_data.db "SELECT model_id, generation_time, round FROM cluster_models ORDER BY round DESC LIMIT 1;"

# 4. Ver agentes registrados
sqlite3 deploy_db_server/db/sample_data.db "SELECT agent_id, ip, socket, last_seen FROM agents;"

# 5. Ver agregador actual
sqlite3 deploy_db_server/db/sample_data.db "SELECT * FROM current_aggregator;"

# 6. Limpiar todo y reiniciar
pkill -f "pseudo_db"
pkill -f "role_supervisor"
rm -f deploy_db_server/db/sample_data.db
./deploy_db_server/scripts/start.sh &
sleep 5
./deploy_node/scripts/start.sh &
```

---

## 📈 Interpretación de Logs

### ✅ Logs Normales (Todo OK)

```
⏳ Esperando 30s para que otros agentes se registren...
   ⏱️  [3s/30s] 1 agentes registrados (quedan 27s)
   ⏱️  [6s/30s] 2 agentes registrados (quedan 24s)
   ⏱️  [9s/30s] 3 agentes registrados (quedan 21s)
   ✅ ¡Todos los 3 agentes esperados se registraron!
   🚀 Continuando antes de tiempo (ahorro: 21s)
✅ Periodo de registro completado (9s)

🗳️  Elección con 3 agentes registrados
📋 Candidatos: ['agent_1', 'agent_2', 'agent_3']
🏆 Election result: 192.168.1.102:8765 (score: 91)

⏳ Esperando modelos de 3 agentes...
⏱️  Timeout máximo: 120s (2 minutos)
📥 Modelos locales recibidos: 1/3
📥 Modelos locales recibidos: 2/3
📥 Modelos locales recibidos: 3/3
✅ Suficientes modelos recolectados. ¡Iniciando agregación!
```

---

### ⚠️ Logs de Advertencia (Atención)

```
⚠️  Solo 2 agentes registrados (mínimo: 3)
⏳ Esperando 5s adicionales para más agentes...

⏱️  [90s] Modelos: 2/3 (quedan 30s)
⏱️  [120s] Modelos: 2/3 (quedan 0s)
⏱️  ¡TIMEOUT! Límite de 120s excedido
⚠️  Procediendo con AGREGACIÓN PARCIAL (algunos nodos no respondieron)
```

---

### ❌ Logs de Error (Problema Crítico)

```
❌ No hay agentes registrados para elegir agregador
❌ No se puede agregar: No hay agentes registrados en agent_set
❌ Connection lost to the agent: 192.168.1.100
❌ Election failed - cannot proceed
```

---

## 🎯 Checklist de Resolución de Problemas

Cuando algo falla, seguir este orden:

- [ ] **1. Verificar servidor DB está corriendo** → `ps aux | grep pseudo_db`
- [ ] **2. Verificar conectividad de red** → `ping <IP>`
- [ ] **3. Verificar configuración IPs** → `cat config_agent.json`
- [ ] **4. Verificar firewall** → `sudo ufw status`
- [ ] **5. Revisar logs del servidor** → `tail -f deploy_db_server/logs/*.log`
- [ ] **6. Revisar logs de los nodos** → `tail -f deploy_node/logs/*.log`
- [ ] **7. Verificar preprocessor idéntico** → `md5sum preprocessor_global.joblib`
- [ ] **8. Limpiar y reiniciar** → `pkill -f role_supervisor && ./scripts/start.sh`

---

## 📞 Soporte Adicional

Si el problema persiste después de seguir esta guía:

1. **Capturar logs completos:**
```bash
./scripts/start.sh 2>&1 | tee debug.log
```

2. **Revisar la documentación:**
- `README_DESPLIEGUE.md` - Guía de despliegue
- `.github/copilot-instructions.md` - Arquitectura del sistema

3. **Verificar configuración completa:**
```bash
cat setups/config_agent.json | jq .
```
