#!/bin/bash
# Script para sincronizar código actualizado a todos los nodos

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Sincronización de Código a Nodos${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# IPs de los nodos (ajustar según tu configuración)
NODES=(
    "r1@172.23.211.138"
    "r2@172.23.211.117"
    "R3@172.23.211.121"
    "r4@172.23.211.247"
)

# Directorio remoto
REMOTE_DIR="Carlos/Semi_Descentralized/deploy_node"

# Archivos a sincronizar
FILES_TO_SYNC=(
    "fl_main/aggregator/server_th.py"
    "fl_main/lib/util/metrics_logger.py"
    "fl_main/agent/client.py"
    "setups/config_agent.json"
)

echo -e "${YELLOW}Archivos a sincronizar:${NC}"
for file in "${FILES_TO_SYNC[@]}"; do
    echo "  - $file"
done
echo ""

# Función para sincronizar un nodo
sync_node() {
    local node=$1
    echo -e "${BLUE}📡 Sincronizando ${node}...${NC}"
    
    for file in "${FILES_TO_SYNC[@]}"; do
        local source="deploy_node/$file"
        local dest="${node}:${REMOTE_DIR}/${file}"
        
        if [ -f "$source" ]; then
            scp "$source" "$dest" 2>&1 | grep -v "Warning: Permanently added"
            if [ ${PIPESTATUS[0]} -eq 0 ]; then
                echo -e "  ${GREEN}✓${NC} $file"
            else
                echo -e "  ${RED}✗${NC} $file (error)"
            fi
        else
            echo -e "  ${RED}✗${NC} $file (no existe localmente)"
        fi
    done
    
    echo ""
}

# Sincronizar todos los nodos
for node in "${NODES[@]}"; do
    sync_node "$node"
done

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Sincronización Completada${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANTE: Reiniciar nodos para aplicar cambios:${NC}"
echo ""
for node in "${NODES[@]}"; do
    echo "  ssh $node 'pkill -f python; bash Carlos/Semi_Descentralized/deploy_node/scripts/start.sh'"
done
echo ""
