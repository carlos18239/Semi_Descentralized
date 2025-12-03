#!/bin/bash
# Script para hacer ejecutables y reiniciar todos los nodos

NODES=(
    "r1@172.23.211.138"
    "r2@172.23.211.117"
    "R3@172.23.211.121"
    "r4@172.23.211.247"
)

REMOTE_DIR="Carlos/Semi_Descentralized/deploy_node"

echo "=============================================="
echo "  🔧 Configurando y Reiniciando Nodos"
echo "=============================================="
echo ""

for node in "${NODES[@]}"; do
    echo "📡 Configurando $node..."
    
    # Hacer scripts ejecutables
    ssh $node "cd $REMOTE_DIR/scripts && chmod +x start.sh stop.sh status.sh" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo "   ✓ Scripts configurados como ejecutables"
    else
        echo "   ✗ Error al configurar scripts"
        continue
    fi
    
    echo ""
done

echo "=============================================="
echo "  ✅ Configuración Completada"
echo "=============================================="
echo ""
echo "SIGUIENTE PASO: Reiniciar cada nodo manualmente"
echo ""
echo "Conectarse a cada nodo y ejecutar:"
echo ""
for node in "${NODES[@]}"; do
    echo "  ssh $node"
    echo "  cd $REMOTE_DIR"
    echo "  bash scripts/stop.sh && bash scripts/start.sh"
    echo "  # Seleccionar opción 2 (Modo daemon)"
    echo ""
done
