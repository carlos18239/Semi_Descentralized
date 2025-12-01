#!/bin/bash
# Reset Federation Script
# Run this on the DB server (your PC) to reset the federation state
# This clears the current_aggregator table, forcing fresh election

echo "🔄 Resetting Federation State"
echo "=============================="

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$REPO_ROOT" || exit 1

# Path to DB file
DB_PATH="./db/sample_data.db"

if [ ! -f "$DB_PATH" ]; then
    echo "⚠️  No database file found at $DB_PATH"
    echo "   This is normal if starting fresh"
    exit 0
fi

echo "📁 Database: $DB_PATH"
echo ""

# Clear current_aggregator table
echo "🧹 Clearing current_aggregator table..."
sqlite3 "$DB_PATH" << EOF
DELETE FROM current_aggregator;
SELECT 'Rows deleted: ' || changes();
EOF

if [ $? -eq 0 ]; then
    echo "✅ Federation state reset successfully"
    echo ""
    echo "Next steps:"
    echo "  1. Start DB server: python -m fl_main.pseudodb.pseudo_db"
    echo "  2. On each Raspberry Pi: ./scripts/start_federation.sh"
    echo "  3. The first node to connect will become aggregator"
else
    echo "❌ Error: Failed to reset database"
    exit 1
fi

