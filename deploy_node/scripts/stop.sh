#!/bin/bash
# =============================================================================
#  DETENER NODO FEDERATED LEARNING
#  Mata todos los procesos FL y limpia archivos PID
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DEPLOY_DIR"

# Activar entorno conda (necesario para algunos comandos)
eval "$(conda shell.bash hook)" 2>/dev/null
conda activate federatedenv2 2>/dev/null

echo "=============================================="
echo "  🛑 Deteniendo Nodo FL"
echo "=============================================="
echo ""

# Detener por PID file si existe
if [ -f "logs/supervisor.pid" ]; then
    PID=$(cat logs/supervisor.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "🔪 Deteniendo supervisor (PID: $PID)..."
        kill $PID 2>/dev/null
        sleep 2
        # Force kill si aún está vivo
        if ps -p $PID > /dev/null 2>&1; then
            kill -9 $PID 2>/dev/null
        fi
        echo "   ✓ Supervisor detenido"
    else
        echo "⚠️  PID $PID ya no existe"
    fi
    rm -f logs/supervisor.pid
fi

# Detener procesos por nombre (backup)
echo "🧹 Limpiando procesos FL..."
pkill -f "fl_main.agent.role_supervisor" 2>/dev/null && echo "   ✓ role_supervisor detenido"
pkill -f "fl_main.aggregator.server_th" 2>/dev/null && echo "   ✓ server_th detenido"
pkill -f "fl_main.examples.tabular_ncd" 2>/dev/null && echo "   ✓ tabular_engine detenido"

sleep 1

# Verificar que todo esté detenido
REMAINING=$(ps aux | grep -E 'fl_main\.(agent|aggregator|examples)' | grep -v grep)
if [ -n "$REMAINING" ]; then
    echo ""
    echo "⚠️  Algunos procesos aún están corriendo:"
    echo "$REMAINING"
    echo ""
    read -p "¿Forzar terminación (kill -9)? (s/N): " FORCE
    if [ "$FORCE" = "s" ] || [ "$FORCE" = "S" ]; then
        pkill -9 -f "fl_main" 2>/dev/null
        echo "   ✓ Procesos forzados a terminar"
    fi
else
    echo "   ✓ Todos los procesos FL detenidos"
fi

# Liberar puertos si están ocupados
echo ""
echo "🔓 Liberando puertos..."
for port in 4321 8765 7890; do
    pid=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "   Liberando puerto $port (PID: $pid)"
        kill -9 $pid 2>/dev/null || true
    fi
done

echo ""
echo "✅ Nodo FL detenido completamente"
echo ""
