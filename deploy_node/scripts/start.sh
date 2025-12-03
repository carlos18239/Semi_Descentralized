#!/bin/bash
# =============================================================================
#  INICIO DEL NODO FEDERATED LEARNING
#  Ejecutar en cada Raspberry Pi (nodo/hospital)
# =============================================================================

set -e

echo "=============================================="
echo "  🏥 Nodo FL - Clasificación Tabular NCD"
echo "=============================================="
echo ""

# Directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DEPLOY_DIR"

# Verificar configuración
if [ ! -f "setups/config_agent.json" ]; then
    echo "❌ Error: No se encontró setups/config_agent.json"
    exit 1
fi

# Leer configuración
DEVICE_IP=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('device_ip', 'CHANGE_ME'))" 2>/dev/null)
DB_IP=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('db_ip', ''))" 2>/dev/null)
DB_PORT=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('db_port', 9017))" 2>/dev/null)

# Verificar que device_ip esté configurado
if [ "$DEVICE_IP" == "CHANGE_ME" ] || [ -z "$DEVICE_IP" ]; then
    echo "❌ Error: device_ip no está configurado"
    echo ""
    echo "Edita setups/config_agent.json y cambia 'CHANGE_ME' por la IP de esta Raspberry Pi"
    echo ""
    echo "Para obtener la IP, ejecuta: hostname -I | awk '{print \$1}'"
    exit 1
fi

echo "📍 Configuración:"
echo "   IP Nodo:     $DEVICE_IP"
echo "   IP Servidor: $DB_IP:$DB_PORT"
echo "   Dir:         $DEPLOY_DIR"
echo ""

# Configurar archivo de datos según la IP del nodo
if [ ! -f "data/data.csv" ]; then
    echo "🔍 Detectando archivo de datos según IP del nodo..."
    
    case "$DEVICE_IP" in
        "172.23.211.138")
            DATA_FILE="data1.csv"
            ;;
        "172.23.211.117")
            DATA_FILE="data2.csv"
            ;;
        "172.23.211.121")
            DATA_FILE="data3.csv"
            ;;
        "172.23.211.247")
            DATA_FILE="data4.csv"
            ;;
        *)
            DATA_FILE="data1.csv"  # Por defecto
            ;;
    esac
    
    if [ -f "data/$DATA_FILE" ]; then
        cp "data/$DATA_FILE" "data/data.csv"
        echo "   ✓ Usando $DATA_FILE para este nodo"
    else
        echo "❌ Error: No se encontró data/$DATA_FILE"
        exit 1
    fi
fi

# Verificar que el archivo existe
if [ ! -f "data/data.csv" ]; then
    echo "❌ Error: No se encontró data/data.csv"
    exit 1
fi

# Verificar preprocessor
if [ ! -f "artifacts/preprocessor_global.joblib" ]; then
    echo "❌ Error: No se encontró artifacts/preprocessor_global.joblib"
    exit 1
fi

# Verificar dependencias
# Activar entorno conda
echo "🐍 Activando entorno conda federatedenv2..."
eval "$(conda shell.bash hook)"
conda activate federatedenv2 2>/dev/null || {
    echo "❌ Error: No se pudo activar federatedenv2"
    echo "   Ejecuta primero: conda activate federatedenv2"
    exit 1
}
echo "   ✓ Entorno federatedenv2 activado"
echo ""

echo "🔍 Verificando dependencias..."
MISSING_DEPS=0

python3 -c "import torch" 2>/dev/null || { echo "  ⚠️  torch no instalado"; MISSING_DEPS=1; }
python3 -c "import pandas" 2>/dev/null || { echo "  ⚠️  pandas no instalado"; MISSING_DEPS=1; }
python3 -c "import sklearn" 2>/dev/null || { echo "  ⚠️  scikit-learn no instalado"; MISSING_DEPS=1; }
python3 -c "import joblib" 2>/dev/null || { echo "  ⚠️  joblib no instalado"; MISSING_DEPS=1; }
python3 -c "import websockets" 2>/dev/null || { echo "  ⚠️  websockets no instalado"; MISSING_DEPS=1; }

if [ $MISSING_DEPS -eq 1 ]; then
    echo ""
    echo "📦 Instalando dependencias faltantes..."
    pip3 install -r requirements.txt
fi

echo "✓ Dependencias OK"
echo ""

# Matar procesos anteriores que puedan estar usando los puertos
echo "🧹 Limpiando procesos anteriores..."
pkill -f "fl_main.agent.role_supervisor" 2>/dev/null || true
pkill -f "fl_main.aggregator.server_th" 2>/dev/null || true
pkill -f "fl_main.examples.tabular_ncd" 2>/dev/null || true
# Esperar a que los puertos se liberen
sleep 2
# Verificar y matar por puertos específicos si es necesario
for port in 4321 8765 7890; do
    pid=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "   Matando proceso en puerto $port (PID: $pid)"
        kill -9 $pid 2>/dev/null || true
    fi
done
sleep 1
echo "   ✓ Procesos anteriores limpiados"
echo ""

# Resetear configuración para inicio limpio
echo "🔄 Reseteando configuración para inicio limpio..."
python3 << EOF
import json
with open('setups/config_agent.json', 'r') as f:
    cfg = json.load(f)
cfg['role'] = 'agent'
cfg['aggr_ip'] = ''  # Vacío para descubrir agregador via DB
with open('setups/config_agent.json', 'w') as f:
    json.dump(cfg, f, indent=2)
print("   ✓ role = 'agent', aggr_ip = '' (descubrimiento dinámico)")
EOF

echo "🚀 Iniciando nodo Federated Learning..."
echo "   (Presiona Ctrl+C para detener)"
echo "=============================================="
echo ""

# Iniciar el supervisor de roles (maneja transiciones agent <-> aggregator)
python3 -m fl_main.agent.role_supervisor
