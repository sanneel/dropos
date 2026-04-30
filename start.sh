#!/bin/bash

# DropOS — Start Script
# Usage: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND="$SCRIPT_DIR/frontend/index.html"
DB_FILE="$BACKEND_DIR/dropship.db"
PID_FILE="$SCRIPT_DIR/.backend.pid"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}  DropOS Backoffice${NC}"
echo -e "  ${CYAN}-------------------------------${NC}"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo -e "  ${YELLOW}Stopping previous backend...${NC}"
    kill "$OLD_PID" 2>/dev/null || true; sleep 1
  fi
  rm -f "$PID_FILE"
fi

if ! command -v python3 &>/dev/null; then
  echo -e "  ${RED}Python 3 not found. Install from python.org${NC}"; exit 1
fi

echo -e "  ${CYAN}Checking dependencies...${NC}"
cd "$BACKEND_DIR"
if ! python3 -c "import fastapi,uvicorn,aiosqlite,httpx" 2>/dev/null; then
  echo -e "  ${YELLOW}Installing dependencies...${NC}"
  pip install -r requirements.txt -q
fi

echo -e "  ${CYAN}Starting backend on port 8000...${NC}"
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/backend.log" 2>&1 &
BACKEND_PID=$!; echo $BACKEND_PID > "$PID_FILE"

for i in {1..20}; do
  curl -s http://localhost:8000/api/stats >/dev/null 2>&1 && break
  sleep 0.5
done

echo -e "  ${GREEN}DropOS is running!${NC}"
echo -e "  Dashboard: file://$FRONTEND"
echo -e "  API: http://localhost:8000"
echo -e "  Logs: $SCRIPT_DIR/backend.log"
echo -e "  To stop: ./stop.sh"

if [[ "$OSTYPE" == "darwin"* ]]; then open "$FRONTEND"
elif [[ "$OSTYPE" == "linux"* ]]; then xdg-open "$FRONTEND" 2>/dev/null
elif [[ "$OSTYPE" == "msys" ]]; then start "$FRONTEND"
fi

tail -f "$SCRIPT_DIR/backend.log"
