#!/bin/bash
# =============================================================================
#  INICIO DEL SERVIDOR DE BASE DE DATOS (PseudoDB)
#  Ejecutar en tu PC (servidor central)
# =============================================================================

set -e

echo "=============================================="
echo "  🗄️  Servidor PseudoDB - Federated Learning"
echo "=============================================="
echo ""

# Directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DEPLOY_DIR"

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

# Verificar configuración
if [ ! -f "setups/config_db.json" ]; then
    echo "❌ Error: No se encontró setups/config_db.json"
    exit 1
fi

# Leer IP y puerto de configuración
DB_IP=$(python3 -c "import json; print(json.load(open('setups/config_db.json')).get('db_ip', '0.0.0.0'))" 2>/dev/null)
DB_PORT=$(python3 -c "import json; print(json.load(open('setups/config_db.json')).get('db_port', 9017))" 2>/dev/null)

echo "📍 Configuración:"
echo "   IP:     $DB_IP"
echo "   Puerto: $DB_PORT"
echo "   Dir:    $DEPLOY_DIR"
echo ""

# Crear directorio de base de datos si no existe
mkdir -p db

# Limpiar base de datos anterior para inicio limpio
echo "🧹 Limpiando base de datos anterior..."
if [ -f "db/sample_data.db" ]; then
    rm -f db/sample_data.db
    echo "   ✓ Base de datos eliminada (inicio limpio)"
else
    echo "   ✓ No hay base de datos anterior"
fi

# Verificar dependencias
echo "🔍 Verificando dependencias..."
python3 -c "import websockets" 2>/dev/null || {
    echo "⚠️  Instalando websockets..."
    pip3 install websockets
}

echo ""
echo "🚀 Iniciando servidor PseudoDB..."
echo "   (Presiona Ctrl+C para detener)"
echo "=============================================="
echo ""

# Iniciar servidor
python3 -m fl_main.pseudodb.pseudo_db
