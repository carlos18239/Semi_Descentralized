#!/bin/bash
# =============================================================================
#  MONITOREAR ESTADO DEL NODO FL
#  Muestra procesos, conexiones y últimas líneas de logs
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DEPLOY_DIR"

# Activar entorno conda (necesario para leer config JSON)
eval "$(conda shell.bash hook)" 2>/dev/null
conda activate federatedenv2 2>/dev/null

echo "=============================================="
echo "  📊 Estado del Nodo FL"
echo "=============================================="
echo ""

# Verificar configuración actual
if [ -f "setups/config_agent.json" ]; then
    ROLE=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('role', 'N/A'))" 2>/dev/null)
    DEVICE_IP=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('device_ip', 'N/A'))" 2>/dev/null)
    AGGR_IP=$(python3 -c "import json; print(json.load(open('setups/config_agent.json')).get('aggr_ip', 'N/A'))" 2>/dev/null)
    
    echo "📍 Configuración:"
    echo "   Rol:         $ROLE"
    echo "   IP Nodo:     $DEVICE_IP"
    echo "   IP Agregador: $AGGR_IP"
    echo ""
fi

# Verificar procesos
echo "🔄 Procesos FL:"
SUPERVISOR=$(ps aux | grep '[f]l_main.agent.role_supervisor' | grep -v grep)
AGGREGATOR=$(ps aux | grep '[f]l_main.aggregator.server_th' | grep -v grep)
AGENT=$(ps aux | grep '[f]l_main.examples.tabular_ncd' | grep -v grep)

if [ -n "$SUPERVISOR" ]; then
    SPID=$(echo "$SUPERVISOR" | awk '{print $2}')
    STIME=$(echo "$SUPERVISOR" | awk '{print $9}')
    echo "   ✅ role_supervisor  (PID: $SPID, desde: $STIME)"
else
    echo "   ❌ role_supervisor  (NO CORRIENDO)"
fi

if [ -n "$AGGREGATOR" ]; then
    APID=$(echo "$AGGREGATOR" | awk '{print $2}')
    ATIME=$(echo "$AGGREGATOR" | awk '{print $9}')
    echo "   ✅ server_th        (PID: $APID, desde: $ATIME)"
elif [ -n "$AGENT" ]; then
    TPID=$(echo "$AGENT" | awk '{print $2}')
    TTIME=$(echo "$AGENT" | awk '{print $9}')
    echo "   ✅ tabular_engine   (PID: $TPID, desde: $TTIME)"
else
    echo "   ❌ Ningún proceso de entrenamiento activo"
fi

# Verificar conexiones a puertos FL
echo ""
echo "🔌 Puertos FL:"
for port in 4321 8765 7890 9017; do
    STATUS=$(netstat -tuln 2>/dev/null | grep ":$port " || lsof -i:$port 2>/dev/null | tail -n +2 || echo "")
    if [ -n "$STATUS" ]; then
        echo "   ✅ Puerto $port - EN USO"
    else
        echo "   ⚪ Puerto $port - libre"
    fi
done

# PID file
echo ""
if [ -f "logs/supervisor.pid" ]; then
    PID=$(cat logs/supervisor.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "📄 PID file: logs/supervisor.pid ($PID) - ✅ Válido"
    else
        echo "📄 PID file: logs/supervisor.pid ($PID) - ⚠️  Proceso muerto"
    fi
else
    echo "📄 PID file: No existe (posible modo interactivo)"
fi

# Últimas líneas de logs
echo ""
echo "📝 Últimas líneas de logs:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "logs/node_supervisor.log" ]; then
    echo "   [logs/node_supervisor.log]"
    tail -n 10 logs/node_supervisor.log | sed 's/^/   /'
elif [ -f "logs/agent.log" ]; then
    echo "   [logs/agent.log]"
    tail -n 10 logs/agent.log | sed 's/^/   /'
else
    echo "   ⚠️  No se encontraron archivos de logs"
fi

echo ""
echo "=============================================="
echo ""
echo "Comandos útiles:"
echo "  - Ver logs en vivo:    tail -f logs/node_supervisor.log"
echo "  - Reiniciar nodo:      bash scripts/start.sh"
echo "  - Detener nodo:        bash scripts/stop.sh"
echo ""
