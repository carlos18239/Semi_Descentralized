# 🚨 SOLUCIÓN AL PROBLEMA: Role Supervisor No Corriendo

## ❌ PROBLEMA IDENTIFICADO

Los logs muestran que **`role_supervisor.py` NO está corriendo** en ningún nodo:
```bash
ps aux | grep role_supervisor
# Solo devuelve el propio grep, NO el proceso supervisor
```

**Esto explica todos los síntomas**:
- ✅ Elección funciona correctamente
- ✅ Agregador inicia y escucha en puerto 8765
- ❌ Agentes perdedores hacen `os._exit(0)` después de rotación
- ❌ **NO hay supervisor para reiniciarlos**
- ❌ Agentes mueren y nunca se re-registran
- ❌ Agregador espera eternamente con 0 agentes registrados

---

## ✅ SOLUCIÓN INMEDIATA

### Paso 1: Detener TODO en todos los nodos

Ejecutar en **cada Raspberry Pi** (r1, r2, R3, r4):

```bash
cd ~/Carlos/Semi_Descentralized/deploy_node
bash scripts/stop.sh
```

### Paso 2: Sincronizar scripts mejorados desde PC central

Ejecutar en tu **PC (Fedora)**:

```bash
cd /home/carlos/Downloads/deployment_desentralizado-20251202T150031Z-1-001/deployment_desentralizado/Federated-Learning
bash sync_to_nodes.sh
```

Esto actualizará en todos los nodos:
- `start.sh` - Con verificación de supervisor y modo daemon
- `stop.sh` - Para detener limpiamente
- `status.sh` - Para monitorear estado
- Código Python actualizado

### Paso 3: Hacer scripts ejecutables en cada nodo

En **cada Raspberry Pi**:

```bash
cd ~/Carlos/Semi_Descentralized/deploy_node/scripts
chmod +x start.sh stop.sh status.sh
```

### Paso 4: Iniciar nodos en modo DAEMON

En **cada Raspberry Pi**, ejecutar:

```bash
cd ~/Carlos/Semi_Descentralized/deploy_node
bash scripts/start.sh
# Seleccionar opción 2 (Modo daemon)
```

Esto iniciará el supervisor en **background persistente** que:
- Sobrevive al cierre de terminal SSH
- Reinicia automáticamente agents/aggregators después de `os._exit(0)`
- Guarda logs en `logs/node_supervisor.log`
- Crea archivo PID en `logs/supervisor.pid`

### Paso 5: Verificar que supervisor está corriendo

En **cada nodo**:

```bash
ps aux | grep role_supervisor
# Debe mostrar: python3 -m fl_main.agent.role_supervisor
```

O usar el script de monitoreo:

```bash
bash scripts/status.sh
```

---

## 🔍 VERIFICACIÓN POST-INICIO

### 1. Verificar procesos activos

```bash
bash scripts/status.sh
```

Debe mostrar:
```
✅ role_supervisor  (PID: XXXX, desde: HH:MM)
✅ tabular_engine   (PID: YYYY, desde: HH:MM)  # o server_th si es agregador
```

### 2. Monitorear logs en tiempo real

```bash
tail -f logs/node_supervisor.log
```

Deberías ver:
```
🔑 Agent ID loaded from setups/.agent_id: <ID_ÚNICO>
📊 Esperando 10s para que otros agentes se registren...
✅ Todos los X agentes tienen scores - procediendo a elección
🏆 Confirmed: I am the elected aggregator!  # Solo en el ganador
📊 Another node won the election: 172.23.211.XXX:8765  # En perdedores
--- AgentMsgType.participate Message Received ---  # En agregador
```

### 3. Verificar puertos en uso

```bash
lsof -i :8765  # Puerto de registro (debe estar en el agregador)
lsof -i :4321  # Puerto de intercambio (debe estar en el agregador)
```

---

## 📊 FLUJO CORRECTO ESPERADO

Con el supervisor corriendo:

1. **Inicio**: `start.sh` (modo daemon) → lanza `role_supervisor.py`
2. **Supervisor** lee `role='agent'` → ejecuta `tabular_engine.py`
3. **Agente** se registra en DB, participa en elección
4. **Ganador**: `os._exit(0)` → Supervisor detecta → lee `role='aggregator'` → ejecuta `server_th.py`
5. **Perdedores**: esperan 10s → envían mensaje `participate` al agregador → inician FL
6. **Durante rotación**: Todos hacen `os._exit(0)` → **Supervisor reinicia automáticamente**
7. **Repetir desde paso 2** ✅

---

## 🛠️ COMANDOS ÚTILES DE GESTIÓN

### En cada nodo:

```bash
# Ver estado completo
bash scripts/status.sh

# Ver logs en vivo
tail -f logs/node_supervisor.log

# Reiniciar nodo (sin detenerlo primero)
bash scripts/stop.sh && bash scripts/start.sh
# Seleccionar modo 2 (daemon)

# Detener nodo completamente
bash scripts/stop.sh

# Ver procesos FL activos
ps aux | grep fl_main
```

### Desde PC central:

```bash
# Sincronizar código actualizado
bash sync_to_nodes.sh

# Ver estado de todos los nodos (requiere SSH)
for node in r1@172.23.211.138 r2@172.23.211.117 R3@172.23.211.121 r4@172.23.211.247; do
    echo "=== $node ==="
    ssh $node "cd Carlos/Semi_Descentralized/deploy_node && bash scripts/status.sh"
done
```

---

## ⚠️ ERRORES COMUNES Y SOLUCIONES

### Error: "Ya hay un role_supervisor corriendo"
**Causa**: Supervisor anterior no se detuvo correctamente  
**Solución**: 
```bash
bash scripts/stop.sh
# Luego reiniciar
bash scripts/start.sh
```

### Error: "Address already in use" (puerto ocupado)
**Causa**: Proceso anterior no liberó el puerto  
**Solución**:
```bash
# Identificar proceso
lsof -i :8765
# Matar proceso
kill -9 <PID>
# O usar stop.sh que lo hace automáticamente
bash scripts/stop.sh
```

### Error: Logs muestran "Connection refused" al agregador
**Causa**: Agregador aún no terminó de arrancar  
**Solución**: ✅ **Auto-corregido** - Los agentes tienen 12 reintentos con backoff (hasta 120s total)

### Error: Agentes con diferentes scores en cada reinicio
**Causa**: IDs no persistentes (ya solucionado)  
**Verificación**:
```bash
cat setups/.agent_id  # Debe existir y no cambiar entre reinicios
```

---

## 📝 MEJORAS IMPLEMENTADAS

### 1. Script `start.sh` mejorado
- ✅ Detecta si supervisor ya está corriendo
- ✅ Ofrece modo interactivo (debug) vs daemon (producción)
- ✅ En modo daemon: crea PID file y logs persistentes
- ✅ Resetea configuración antes de iniciar

### 2. Nuevo script `stop.sh`
- ✅ Detiene procesos usando PID file
- ✅ Limpia procesos huérfanos
- ✅ Libera puertos ocupados
- ✅ Opción de force-kill si es necesario

### 3. Nuevo script `status.sh`
- ✅ Muestra configuración actual (role, IPs)
- ✅ Lista procesos FL activos
- ✅ Verifica puertos en uso
- ✅ Valida PID file
- ✅ Muestra últimas líneas de logs

### 4. `sync_to_nodes.sh` actualizado
- ✅ Incluye los nuevos scripts de gestión
- ✅ Aplica permisos ejecutables automáticamente

---

## 🎯 CHECKLIST DE DEPLOYMENT

Antes de considerar el sistema operacional:

- [ ] Supervisor corriendo en TODOS los nodos (`ps aux | grep role_supervisor`)
- [ ] Archivos `.agent_id` existen en cada nodo (`ls -la setups/.agent_id`)
- [ ] Todos los nodos tienen `role='agent'` al inicio (`cat setups/config_agent.json`)
- [ ] DB server corriendo en 172.23.211.109:9017
- [ ] Logs muestran elección exitosa en todos los nodos
- [ ] Agregador muestra "AgentMsgType.participate Message Received" para cada agente
- [ ] Agentes muestran "Global Model Received" (no solo ACKs)
- [ ] Métricas guardándose en `metrics/metrics_<agent_name>.csv`

---

## 🔗 SIGUIENTE PASO

**Una vez que el supervisor esté corriendo en todos los nodos**, ejecuta este comando en cada uno para confirmar:

```bash
bash scripts/status.sh
```

Si todo está correcto, verás:
```
✅ role_supervisor  (PID: XXXX, desde: HH:MM)
✅ tabular_engine   (PID: YYYY, desde: HH:MM)
```

Luego monitorea logs durante 2-3 minutos para verificar que:
1. Elección ocurre correctamente
2. Agentes se registran con agregador
3. Primera ronda completa (Round 1)
4. Rotación funciona (después de N rondas según `rotation_interval`)
