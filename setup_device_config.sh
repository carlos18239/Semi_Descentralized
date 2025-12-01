#!/bin/bash
# Script para configurar cada Raspberry Pi con sus configuraciones específicas
if [ -z "$1" ]; then
    echo "Usage: ./setup_device_config.sh <r1|r2|r3|r4>"
    echo ""
    echo "Este script configura los archivos JSON para cada dispositivo Raspberry Pi"
    echo "  r1: 172.23.211.138 (Agent a2, puerto 50002)"
    echo "  r2: 172.23.211.117 (Aggregator inicial, puerto 8765)"
    echo "  r3: 172.23.211.121 (Agent a3, puerto 50003)"
    echo "  r4: 172.23.211.247 (Agent a4, puerto 50004)"
    exit 1


DEVICE=$1
SETUPS_DIR="./setups"

case $DEVICE in
    r1)
        echo "Configurando r1 (172.23.211.138) - Agent a2..."
        cat > "$SETUPS_DIR/config_agent.json" << 'EOF'
{
  "device_ip": "172.23.211.138",
  "aggr_ip": "172.23.211.117",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
EOF

        cat > "$SETUPS_DIR/config_aggregator.json" << 'EOF'
{
  "device_ip": "172.23.211.138",
  "aggr_ip": "172.23.211.138",
  "db_ip": "172.23.211.109",
  "reg_socket": "50002",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator",
  "rotation_min_rounds": 1,
  "rotation_interval": 3,
  "rotation_delay": 20,
  "agent_wait_interval": 10,
  "agent_ttl_seconds": 300,
  "max_rounds": 100,
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
EOF
        echo "✓ r1 configurado con IP 172.23.211.138 y puerto 50002"
        ;;
        
    r2)
        echo "Configurando r2 (172.23.211.117) - Aggregator inicial..."
        cat > "$SETUPS_DIR/config_agent.json" << 'EOF'
{
  "device_ip": "172.23.211.117",
  "aggr_ip": "172.23.211.117",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
EOF

        cat > "$SETUPS_DIR/config_aggregator.json" << 'EOF'
{
  "device_ip": "172.23.211.117",
  "aggr_ip": "172.23.211.117",
  "db_ip": "172.23.211.109",
  "reg_socket": "8765",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator",
  "rotation_min_rounds": 1,
  "rotation_interval": 3,
  "rotation_delay": 20,
  "agent_wait_interval": 10,
  "agent_ttl_seconds": 300,
  "max_rounds": 100,
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
EOF
        echo "✓ r2 configurado con IP 172.23.211.117 y puerto 8765"
        ;;
        
    r3)
        echo "Configurando r3 (172.23.211.121) - Agent a3..."
        cat > "$SETUPS_DIR/config_agent.json" << 'EOF'
{
  "device_ip": "172.23.211.121",
  "aggr_ip": "172.23.211.117",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
EOF

        cat > "$SETUPS_DIR/config_aggregator.json" << 'EOF'
{
  "device_ip": "172.23.211.121",
  "aggr_ip": "172.23.211.121",
  "db_ip": "172.23.211.109",
  "reg_socket": "50003",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator",
  "rotation_min_rounds": 1,
  "rotation_interval": 3,
  "rotation_delay": 20,
  "agent_wait_interval": 10,
  "agent_ttl_seconds": 300,
  "max_rounds": 100,
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
EOF
        echo "✓ r3 configurado con IP 172.23.211.121 y puerto 50003"
        ;;
        
    r4)
        echo "Configurando r4 (172.23.211.247) - Agent a4..."
        cat > "$SETUPS_DIR/config_agent.json" << 'EOF'
{
  "device_ip": "172.23.211.247",
  "aggr_ip": "172.23.211.117",
  "reg_socket": "8765",
  "model_path": "./data/agents",
  "local_model_file_name": "lms.binaryfile",
  "global_model_file_name": "gms.binaryfile",
  "state_file_name": "state",
  "init_weights_flag": 1,
  "polling": 1,
  "role": "agent"
}
EOF

        cat > "$SETUPS_DIR/config_aggregator.json" << 'EOF'
{
  "device_ip": "172.23.211.247",
  "aggr_ip": "172.23.211.247",
  "db_ip": "172.23.211.109",
  "reg_socket": "50004",
  "exch_socket": "7890",
  "recv_socket": "4321",
  "db_socket": "9017",
  "round_interval": 5,
  "aggregation_threshold": 1,
  "polling": 1,
  "role": "aggregator",
  "rotation_min_rounds": 1,
  "rotation_interval": 3,
  "rotation_delay": 20,
  "agent_wait_interval": 10,
  "agent_ttl_seconds": 300,
  "max_rounds": 100,
  "early_stopping_patience": 120,
  "early_stopping_min_delta": 0.0001
}
EOF
        echo "✓ r4 configurado con IP 172.23.211.247 y puerto 50004"
        ;;
        
    *)
        echo "Error: Dispositivo desconocido '$DEVICE'"
        echo "Usa: r1, r2, r3, o r4"
        exit 1
        ;;
esac

echo ""
echo "Archivos configurados en $SETUPS_DIR:"
echo "  - config_agent.json"
echo "  - config_aggregator.json"
echo ""
echo "Siguiente paso: git add, commit y push estos cambios, luego haz git pull en $DEVICE"
