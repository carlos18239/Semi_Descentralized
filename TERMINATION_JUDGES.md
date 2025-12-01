# Jueces de Terminación del Entrenamiento Federado

Este documento explica los dos jueces (judges) que controlan cuándo termina el entrenamiento federado distribuido.

## 📊 Resumen

El sistema implementa **dos condiciones de terminación independientes** para detener el entrenamiento cuando:
1. **Juez 1 (Early Stopping)**: El recall global no mejora durante muchos rounds
2. **Juez 2 (Max Rounds)**: Se alcanza un límite máximo de rounds

Cualquiera de los dos puede terminar el entrenamiento. El agregador notifica a todos los agentes via polling y todo el sistema se detiene de manera coordinada.

---

## 🎯 Juez 1: Early Stopping por Recall Global

### Concepto
Termina el entrenamiento si el **recall global** no mejora significativamente durante un período prolongado (paciencia).

### Parámetros (en `config_aggregator.json`)
```json
{
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
```

- **`early_stopping_patience`**: Número de rounds sin mejora antes de terminar (default: 120)
- **`early_stopping_min_delta`**: Mejora mínima para considerar que hubo progreso (default: 0.0001)

### Funcionamiento

#### 1. Los agentes envían recall local
Después de cada round de entrenamiento, cada agente:
```python
# En classification_engine.py
accuracy = compute_performance(models, prep_test_data(), True)
fl_client.send_recall_metric(accuracy)  # ← Envía recall al agregador
```

#### 2. El agregador calcula recall global
El agregador espera hasta recibir recall de **TODOS** los agentes registrados:
```python
# En server_th.py: _process_recall_upload()
if len(self.current_round_recalls) >= num_agents:
    # Promedio de todos los recalls
    global_recall = sum(self.current_round_recalls.values()) / len(self.current_round_recalls)
```

#### 3. El agregador verifica mejora
```python
if global_recall > self.best_global_recall + self.early_stopping_min_delta:
    # ✓ Hubo mejora
    self.best_global_recall = global_recall
    self.rounds_without_improvement = 0
else:
    # ✗ No hubo mejora
    self.rounds_without_improvement += 1
```

#### 4. Terminación si se agota la paciencia
```python
if self.rounds_without_improvement >= self.early_stopping_patience:
    # 🛑 TERMINAR: No mejora en 120 rounds
    self.pending_termination_msg = generate_termination_msg(
        reason=f"No improvement for {self.early_stopping_patience} rounds",
        final_round=self.sm.round,
        final_recall=self.best_global_recall
    )
```

### Ejemplo
```
Round 1: Recall=0.65 → best=0.65, sin_mejora=0
Round 2: Recall=0.67 → best=0.67, sin_mejora=0  (mejoró +0.02)
Round 3: Recall=0.66 → best=0.67, sin_mejora=1  (no mejoró)
Round 4: Recall=0.66 → best=0.67, sin_mejora=2
...
Round 122: Recall=0.67 → best=0.67, sin_mejora=120
🛑 TRAINING TERMINATED: Early stopping triggered
```

---

## 🔢 Juez 2: Límite Máximo de Rounds

### Concepto
Termina el entrenamiento si se alcanza un número máximo de rounds, independientemente del rendimiento.

### Parámetros (en `config_aggregator.json`)
```json
{
  "max_rounds": 100
}
```

- **`max_rounds`**: Número máximo de rounds de entrenamiento (default: 100)

### Funcionamiento

El agregador verifica en cada round:
```python
# En server_th.py: _check_termination_judges()
if self.sm.round >= self.max_rounds:
    # 🛑 TERMINAR: Alcanzó el límite
    self.pending_termination_msg = generate_termination_msg(
        reason=f"Reached maximum rounds limit ({self.max_rounds})",
        final_round=self.sm.round,
        final_recall=self.best_global_recall
    )
```

### Ejemplo
```
Round 98: Agregación OK
Round 99: Agregación OK
Round 100: Agregación OK
🛑 TRAINING TERMINATED: Reached max rounds (100)
```

---

## 🔄 Flujo de Terminación

### 1. Detección de Condición de Terminación
```
Agregador (server_th.py)
  ↓
_check_termination_judges()
  ↓
[Juez 1: rounds_without_improvement >= 120?]
[Juez 2: sm.round >= 100?]
  ↓
Si alguno es True:
  → self.training_terminated = True
  → self.pending_termination_msg = generate_termination_msg(...)
```

### 2. Notificación a Agentes via Polling
```
Agente hace polling → Client.process_polling()
  ↓
Agregador responde → _process_polling()
  ↓
if self.pending_termination_msg is not None:
  → Envía AggMsgType.termination
```

### 3. Agente Recibe y Termina
```python
# En client.py: process_polling()
if msg_type == AggMsgType.termination:
    reason = resp[TerminationMsgLocation.reason]
    final_round = resp[TerminationMsgLocation.final_round]
    final_recall = resp[TerminationMsgLocation.final_recall]
    
    logging.warning(f'🛑 TRAINING TERMINATED by aggregator')
    logging.info(f'Reason: {reason}')
    logging.info(f'Final round: {final_round}')
    logging.info(f'Final global recall: {final_recall:.4f}')
    
    os._exit(0)  # ← Salida limpia
```

---

## 📝 Logs Esperados

### En el Agregador
```
INFO:root:--- Recall Upload Received: agent=abc123, recall=0.6543, round=45 ---
INFO:root:=== GLOBAL RECALL (Round 45): 0.6512 ===
INFO:root:Individual recalls: {'abc123': 0.6543, 'def456': 0.6480}
INFO:root:✓ Global recall improved by 0.0023 (new best: 0.6512)
```

```
INFO:root:✗ No improvement for 118 rounds (best: 0.6789)
INFO:root:✗ No improvement for 119 rounds (best: 0.6789)
INFO:root:✗ No improvement for 120 rounds (best: 0.6789)
WARNING:root:🛑 TRAINING TERMINATED: Early stopping triggered
INFO:root:No improvement for 120 rounds
INFO:root:Best global recall: 0.6789
```

### En los Agentes
```
INFO:root:--- Recall metric (0.6543) sent to aggregator ---
INFO:root:--- Polling to see if there is any update ---
WARNING:root:🛑 TRAINING TERMINATED by aggregator
INFO:root:Reason: No improvement for 120 rounds (patience exhausted)
INFO:root:Final round: 145
INFO:root:Final global recall: 0.6789
INFO:root:Agent exiting due to training termination...
```

---

## ⚙️ Configuración Recomendada

### Para Testing Rápido
```json
{
  "max_rounds": 10,
  "early_stopping_patience": 5,
  "early_stopping_min_delta": 0.01
}
```
Termina en ~10 rounds o si no mejora en 5 rounds.

### Para Entrenamiento Real (CIFAR-10)
```json
{
  "max_rounds": 100,
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
```
Permite hasta 100 rounds, pero termina antes si no mejora en 120 rounds.

### Para Entrenamiento Largo
```json
{
  "max_rounds": 500,
  "early_stopping_patience": 50,
  "early_stopping_min_delta": 0.0005
}
```
Más rounds permitidos, pero paciencia más estricta.

---

## 🔧 Integración con Rotación

Los jueces de terminación son **independientes de la rotación**:

- **Rotación**: Cambia el agregador cada N rounds (controlado por `rotation_min_rounds` y `rotation_interval`)
- **Terminación**: Detiene TODO el entrenamiento cuando se cumple la condición

**Cronología típica:**
```
Round 0-1: Entrenamiento normal
Round 2: ROTACIÓN (nuevo agregador elegido, todos reinician)
Round 3-4: Entrenamiento normal
Round 5: ROTACIÓN
...
Round 97: Entrenamiento normal
Round 98: ✗ No mejora (rounds_without_improvement=118)
Round 99: ✗ No mejora (rounds_without_improvement=119)
Round 100: ✗ No mejora (rounds_without_improvement=120)
🛑 TERMINACIÓN: Early stopping triggered
```

El nuevo agregador después de rotación **hereda el estado de terminación** (best_global_recall, rounds_without_improvement) desde la base de datos, asegurando continuidad en el seguimiento del progreso.

---

## 🚀 Cómo Usar

### 1. Configurar parámetros
Edita `setups/config_aggregator.json` o usa el script:
```bash
./setup_device_config.sh r2
# Genera config con valores por defecto
```

### 2. Iniciar sistema
```bash
# En r2 (agregador inicial)
python -m fl_main.aggregator.role_supervisor 1 8765 a_aggregator

# En r1 y r3 (agentes)
python -m fl_main.agent.role_supervisor 1 50002 a2
python -m fl_main.agent.role_supervisor 1 50003 a3
```

### 3. Observar logs
Los logs mostrarán:
- Recall de cada agente
- Recall global promedio
- Contador de rounds sin mejora
- Mensaje de terminación cuando se cumpla condición

### 4. Sistema termina automáticamente
Todos los procesos (agregador y agentes) se detienen limpiamente cuando cualquier juez dispara terminación.

---

## 📊 Ventajas del Sistema Dual

1. **Eficiencia**: Early stopping evita entrenamiento innecesario
2. **Seguridad**: Max rounds previene ejecución infinita
3. **Flexibilidad**: Ajusta parámetros según necesidades
4. **Coordinación**: Todos los nodos terminan simultáneamente
5. **Información**: Logs detallados de por qué terminó

---

## 🐛 Troubleshooting

**Problema**: "No se recibe recall de los agentes"
- **Causa**: Los agentes no están llamando `send_recall_metric()`
- **Solución**: Verifica que `classification_engine.py` incluya:
  ```python
  fl_client.send_recall_metric(accuracy)
  ```

**Problema**: "Early stopping nunca se dispara"
- **Causa**: Recall sigue mejorando o `early_stopping_patience` es muy alto
- **Solución**: Reduce `early_stopping_patience` o ajusta `early_stopping_min_delta`

**Problema**: "Terminación no llega a todos los agentes"
- **Causa**: Agentes no están haciendo polling activamente
- **Solución**: Verifica que los agentes estén en estado `waiting_gm` y haciendo polling periódico

**Problema**: "Sistema continúa después de terminación"
- **Causa**: `pending_termination_msg` no se está enviando
- **Solución**: Verifica prioridad en `_process_polling()` (termination debe ser Priority 0)
