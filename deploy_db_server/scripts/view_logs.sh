#!/bin/bash
# Script para ver los logs del servidor DB

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/db_server.log"

# Colores
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

show_help() {
    echo ""
    echo "📋 Visor de Logs del DB Server"
    echo "=============================="
    echo ""
    echo "Uso: ./view_logs.sh [opción]"
    echo ""
    echo "Opciones:"
    echo "  -f, --follow     Ver logs en tiempo real (tail -f)"
    echo "  -e, --errors     Mostrar solo errores (ERROR, WARNING)"
    echo "  -t, --today      Mostrar logs de hoy"
    echo "  -l, --last N     Mostrar últimas N líneas (default: 50)"
    echo "  -a, --all        Mostrar todos los logs"
    echo "  -s, --search     Buscar texto en los logs"
    echo "  -c, --clean      Limpiar archivo de logs"
    echo "  -h, --help       Mostrar esta ayuda"
    echo ""
}

if [ ! -f "$LOG_FILE" ]; then
    echo -e "${YELLOW}⚠️  No existe archivo de logs todavía${NC}"
    echo "El archivo se creará cuando inicies el servidor DB"
    exit 0
fi

case "$1" in
    -f|--follow)
        echo -e "${GREEN}📡 Siguiendo logs en tiempo real... (Ctrl+C para salir)${NC}"
        echo ""
        tail -f "$LOG_FILE" | while read line; do
            if [[ $line == *"ERROR"* ]]; then
                echo -e "${RED}$line${NC}"
            elif [[ $line == *"WARNING"* ]]; then
                echo -e "${YELLOW}$line${NC}"
            elif [[ $line == *"Started"* ]] || [[ $line == *"elected"* ]]; then
                echo -e "${GREEN}$line${NC}"
            else
                echo "$line"
            fi
        done
        ;;
    -e|--errors)
        echo -e "${RED}🔴 Errores y Advertencias:${NC}"
        echo ""
        grep -E "ERROR|WARNING" "$LOG_FILE" | tail -100
        ;;
    -t|--today)
        TODAY=$(date +%Y-%m-%d)
        echo -e "${BLUE}📅 Logs de hoy ($TODAY):${NC}"
        echo ""
        grep "^$TODAY" "$LOG_FILE"
        ;;
    -l|--last)
        N=${2:-50}
        echo -e "${BLUE}📜 Últimas $N líneas:${NC}"
        echo ""
        tail -n "$N" "$LOG_FILE"
        ;;
    -a|--all)
        echo -e "${BLUE}📖 Todos los logs:${NC}"
        echo ""
        cat "$LOG_FILE"
        ;;
    -s|--search)
        if [ -z "$2" ]; then
            echo -e "${RED}❌ Debes especificar un texto a buscar${NC}"
            echo "Uso: ./view_logs.sh -s \"texto\""
            exit 1
        fi
        echo -e "${BLUE}🔍 Buscando '$2':${NC}"
        echo ""
        grep -i "$2" "$LOG_FILE"
        ;;
    -c|--clean)
        echo -e "${YELLOW}⚠️  ¿Estás seguro de limpiar los logs? (s/n)${NC}"
        read -r confirm
        if [ "$confirm" = "s" ] || [ "$confirm" = "S" ]; then
            > "$LOG_FILE"
            echo -e "${GREEN}✅ Logs limpiados${NC}"
        else
            echo "Cancelado"
        fi
        ;;
    -h|--help)
        show_help
        ;;
    *)
        # Por defecto mostrar últimas 50 líneas
        echo -e "${BLUE}📜 Últimas 50 líneas (usa -h para más opciones):${NC}"
        echo ""
        tail -50 "$LOG_FILE"
        ;;
esac
