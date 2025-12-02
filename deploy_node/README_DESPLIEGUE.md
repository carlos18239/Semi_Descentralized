# Despliegue Federated Learning - Clasificación Tabular NCD

## 📋 Descripción

Este sistema implementa **Federated Learning semi-descentralizado** para clasificar muertes prematuras por Enfermedades No Comunicables (NCD) usando datos tabulares de hospitales.

### Arquitectura
```
┌─────────────────┐         ┌─────────────────┐
│  Tu PC (Server) │         │  Raspberry Pi 1 │
│   PseudoDB      │◄───────►│   Hospital 1    │
│ 172.23.211.109  │         │   data1.csv     │
└────────┬────────┘         └─────────────────┘
         │
         │                  ┌─────────────────┐
         ├─────────────────►│  Raspberry Pi 2 │
         │                  │   Hospital 2    │
         │                  │   data2.csv     │
         │                  └─────────────────┘
         │
         │                  ┌─────────────────┐
         ├─────────────────►│  Raspberry Pi 3 │
         │                  │   Hospital 3    │
         │                  │   data3.csv     │
         │                  └─────────────────┘
         │
         │                  ┌─────────────────┐
         └─────────────────►│  Raspberry Pi 4 │
                            │   Hospital 4    │
                            │   (data.csv)    │
                            └─────────────────┘
```

## 🗂️ Estructura de Archivos

### En tu PC (Servidor de Base de Datos)
```
deploy_db_server/
├── fl_main/
│   └── pseudodb/        # Base de datos SQLite
├── setups/
│   └── config_db.json   # Configuración del servidor
└── scripts/
    ├── start_federation.sh
    └── reset_federation.sh
```

### En cada Raspberry Pi
```
deploy_node/
├── fl_main/
│   ├── agent/           # Cliente FL
│   ├── aggregator/      # Agregador dinámico
│   └── examples/
│       └── tabular_ncd/ # Módulo de clasificación tabular
├── data/
│   └── data.csv         # Datos del hospital (UN archivo por nodo)
├── artifacts/
│   └── preprocessor_global.joblib  # Preprocesador de datos
├── setups/
│   └── config_agent.json
└── scripts/
```

---

## 🚀 Instrucciones de Despliegue

### PASO 1: Configurar el Servidor (Tu PC)

1. **Copiar carpeta `deploy_db_server/` a tu PC**

2. **Configurar IP en `setups/config_db.json`:**
```json
{
    "db_ip": "172.23.211.109",
    "db_port": 9017
}
```

3. **Iniciar el servidor:**
```bash
cd deploy_db_server
./scripts/start.sh
```

---

### PASO 2: Configurar cada Raspberry Pi

1. **Copiar carpeta `deploy_node/` a cada Raspberry Pi**

2. **Copiar el dataset del hospital a `data/data.csv`**

3. **Configurar `setups/config_agent.json`:**
```json
{
    "device_ip": "IP_DE_ESTA_RASPBERRY",
    "db_ip": "172.23.211.109",
    "db_port": 9017
}
```
**Importante:** Cambiar `device_ip` con la IP real de la Raspberry Pi

4. **Iniciar el nodo:**
```bash
cd deploy_node
./scripts/start.sh
```
El script automáticamente:
- Verifica e instala dependencias faltantes
- Valida la configuración
- Inicia el nodo FL

---

## 📊 Dataset: Defunciones Hospitalarias

### Columnas del Dataset
| Columna | Descripción |
|---------|-------------|
| `sexo` | Género del paciente |
| `edad_anos` | Edad en años |
| `etnia` | Etnia del paciente |
| `sabe_leer` | Alfabetización |
| `est_civil` | Estado civil |
| `niv_inst` | Nivel de instrucción |
| `prov_res` | Provincia de residencia |
| `prov_fall` | Provincia de fallecimiento |
| `cant_fall` | Cantón de fallecimiento |
| `area_res` | Área de residencia |
| `area_fall` | Área de fallecimiento |
| `lugar_ocur` | Lugar de ocurrencia |
| `mor_viol` | Muerte violenta |
| `lug_viol` | Lugar de violencia |
| `autopsia` | Se realizó autopsia |
| `residente` | Es residente |
| `anio_fall` | Año de fallecimiento |
| `mes_fall` | Mes de fallecimiento |
| `dia_fall` | Día de fallecimiento |
| `ncd_group` | Grupo de enfermedad NCD |
| `**is_premature_ncd**` | **Variable objetivo (0/1)** |
| `hospital_cliente` | ID del hospital |

### Variable Objetivo
- `is_premature_ncd = 1`: Muerte prematura por NCD (< 70 años)
- `is_premature_ncd = 0`: Otra causa de muerte

---

## 🧠 Modelo: MLP (Perceptrón Multicapa)

```
Entrada (21 features)
        │
   ┌────▼────┐
   │ fc1:120 │  + ReLU
   └────┬────┘
        │
   ┌────▼────┐
   │ fc2:84  │  + ReLU
   └────┬────┘
        │
   ┌────▼────┐
   │ fc3:1   │  + Sigmoid
   └────┬────┘
        │
   Salida (probabilidad 0-1)
```

### Hiperparámetros
- **Loss:** BCEWithLogitsLoss (Binary Cross-Entropy)
- **Optimizer:** Adam (lr=0.001)
- **Epochs locales:** 5
- **Batch size:** 32
- **Train/Test split:** 80%/20%

---

## 🔄 Flujo de Entrenamiento Federado

```
1. Todos los nodos se conectan al PseudoDB
2. Se elige un Agregador inicial (orden de conexión)
3. Cada nodo entrena localmente con sus datos
4. Los nodos envían gradientes al Agregador actual
5. El Agregador promedia los modelos (FedAvg)
6. El modelo global se redistribuye
7. Se repite hasta convergencia
8. Cada N rondas, se elige un nuevo Agregador
```

---

## 📈 Métricas de Evaluación

El sistema reporta automáticamente:
- **Accuracy:** Porcentaje de predicciones correctas
- **Loss:** Pérdida del modelo (BCE)
- **Precision, Recall, F1:** (opcional, en logs)

---

## 🛠️ Troubleshooting

### Error: "No se puede conectar al servidor"
- Verificar que el PseudoDB esté corriendo en tu PC
- Verificar que la IP y puerto en `config_agent.json` sean correctos
- Verificar conectividad: `ping 172.23.211.109`

### Error: "No se encuentra el dataset"
- Verificar que `dataset_path` en config apunte al archivo correcto
- Verificar que el archivo CSV exista en la carpeta `data/`

### Error: "Preprocessor not found"
- Verificar que `artifacts/preprocessor_global.joblib` exista

### El entrenamiento no avanza
- Verificar que todos los nodos estén conectados
- Revisar logs del Agregador actual

---

## 📝 Notas Adicionales

- El preprocesador (`preprocessor_global.joblib`) debe ser el mismo en todos los nodos
- Los datos nunca salen de cada Raspberry Pi (solo se comparten gradientes)
- El sistema tolera desconexiones temporales de nodos
