#!/bin/bash
# Start Federation Script
# Usage: Run this on ALL Raspberry Pis simultaneously to start a fresh federation
# The first node to connect will automatically become the aggregator

echo "🚀 Starting Federated Learning Node"
echo "===================================="

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$REPO_ROOT" || exit 1

# Verify config files exist
if [ ! -f "setups/config_agent.json" ]; then
    echo "❌ Error: setups/config_agent.json not found"
    exit 1
fi

# Read device IP from config
DEVICE_IP=$(python3 -c "import json; print(json.load(open('setups/config_agent.json'))['device_ip'])" 2>/dev/null)

if [ -z "$DEVICE_IP" ] || [ "$DEVICE_IP" == "CHANGE_ME" ]; then
    echo "❌ Error: device_ip not configured in setups/config_agent.json"
    echo "Run: ./setups/setup_device_config.sh <r1|r2|r3|r4>"
    exit 1
fi

echo "📍 Device IP: $DEVICE_IP"
echo "📂 Working directory: $REPO_ROOT"
echo ""

# Clean local state (optional - uncomment if you want fresh start each time)
# echo "🧹 Cleaning local agent state..."
# rm -f data/agents/*/lms.binaryfile data/agents/*/gms.binaryfile data/agents/*/state

# Set role to 'agent' initially (will auto-promote if needed)
echo "🔧 Setting initial role to 'agent'..."
python3 << EOF
import json
with open('setups/config_agent.json', 'r') as f:
    cfg = json.load(f)
cfg['role'] = 'agent'
with open('setups/config_agent.json', 'w') as f:
    json.dump(cfg, f, indent=2)
EOF

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to update config"
    exit 1
fi

echo "✅ Configuration ready"
echo ""
echo "🎯 Starting role_supervisor..."
echo "   (This node will auto-promote to aggregator if needed)"
echo ""

# Start the role supervisor
# It will run the agent, which will discover or become the aggregator
python3 -m fl_main.agent.role_supervisor

