#!/bin/bash
# Script para verificar que conda y el entorno federatedenv2 estén configurados

NODES=(
    "r1@172.23.211.138"
    "r2@172.23.211.117"
    "R3@172.23.211.121"
    "r4@172.23.211.247"
)

echo "=============================================="
echo "  🔍 Verificación de Entorno Conda"
echo "=============================================="
echo ""

# Verificar en PC local
echo "📍 PC Local (Servidor DB):"
eval "$(conda shell.bash hook)" 2>/dev/null
conda activate federatedenv2 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ federatedenv2 disponible"
    python3 -c "import torch, pandas, websockets; print('   ✅ Dependencias instaladas')" 2>/dev/null || echo "   ⚠️  Faltan dependencias"
else
    echo "   ❌ federatedenv2 NO disponible"
    echo "   Crear con: conda create -n federatedenv2 python=3.8"
fi
echo ""

# Verificar en nodos remotos
for node in "${NODES[@]}"; do
    echo "📡 Verificando $node..."
    
    # Verificar conda
    ssh -o ConnectTimeout=5 $node "eval \"\$(conda shell.bash hook)\" 2>/dev/null && conda activate federatedenv2 2>/dev/null && echo '   ✅ federatedenv2 disponible' || echo '   ❌ federatedenv2 NO disponible'" 2>/dev/null
    
    # Verificar dependencias
    ssh -o ConnectTimeout=5 $node "eval \"\$(conda shell.bash hook)\" 2>/dev/null && conda activate federatedenv2 2>/dev/null && python3 -c 'import torch, pandas, websockets, sklearn, joblib' 2>/dev/null && echo '   ✅ Dependencias instaladas' || echo '   ⚠️  Faltan dependencias'" 2>/dev/null
    
    echo ""
done

echo "=============================================="
echo ""
echo "Si algún nodo muestra errores, ejecutar en ese nodo:"
echo ""
echo "  # Si conda no está instalado:"
echo "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-armv7l.sh"
echo "  bash Miniconda3-latest-Linux-armv7l.sh"
echo ""
echo "  # Si federatedenv2 no existe:"
echo "  conda create -n federatedenv2 python=3.8 -y"
echo "  conda activate federatedenv2"
echo "  pip install -r requirements.txt"
echo ""
