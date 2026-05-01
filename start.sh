#!/bin/bash

# DropOS — Start Script
# Usage: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND="$SCRIPT_DIR/frontend/index.html"
PID_FILE="$SCRIPT_DIR/.backend.pid"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Resolve python command — try py launcher (Windows), then python3, then python
_py_ok() { "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; }
if command -v py &>/dev/null && _py_ok py; then
  PY=py
elif command -v python3 &>/dev/null && _py_ok python3; then
  PY=python3
elif command -v python &>/dev/null && _py_ok python; then
  PY=python
else
  # Last resort: check common Windows install path directly
  _WIN_PY="$(ls /c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe 2>/dev/null | head -1)"
  if [ -n "$_WIN_PY" ] && _py_ok "$_WIN_PY"; then
    PY="$_WIN_PY"
  else
    echo -e "${RED}Python 3.8+ not found. Install from python.org${NC}"; exit 1
  fi
fi

echo ""
echo -e "${BOLD}  DropOS Backoffice${NC}"
echo -e "  ${CYAN}-------------------------------${NC}"
echo -e "  ${CYAN}Python: $($PY --version)${NC}"

# Kill any existing backend
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo -e "  ${YELLOW}Stopping previous backend (pid $OLD_PID)...${NC}"
    kill "$OLD_PID" 2>/dev/null || true; sleep 1
  fi
  rm -f "$PID_FILE"
fi

echo -e "  ${CYAN}Checking dependencies...${NC}"
cd "$BACKEND_DIR"
if ! $PY -c "import fastapi,uvicorn,aiosqlite,httpx,apscheduler" 2>/dev/null; then
  echo -e "  ${YELLOW}Installing dependencies...${NC}"
  $PY -m pip install -r requirements.txt -q
fi

echo -e "  ${CYAN}Starting backend on port 8000...${NC}"
nohup $PY -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/backend.log" 2>&1 &
BACKEND_PID=$!; echo $BACKEND_PID > "$PID_FILE"

# Wait for backend to be ready (up to 10s)
for i in {1..20}; do
  curl -s http://localhost:8000/api/stats >/dev/null 2>&1 && break
  sleep 0.5
done

if ! curl -s http://localhost:8000/api/stats >/dev/null 2>&1; then
  echo -e "  ${RED}Backend failed to start. Check backend.log for errors.${NC}"
  cat "$SCRIPT_DIR/backend.log"
  exit 1
fi

echo -e "  ${GREEN}DropOS is running!${NC}"
echo -e "  Dashboard: file://$FRONTEND"
echo -e "  API:       http://localhost:8000"
echo -e "  Logs:      tail -f $SCRIPT_DIR/backend.log"
echo -e "  Stop:      ./stop.sh"
echo ""

if [[ "$OSTYPE" == "darwin"* ]]; then open "$FRONTEND"
elif [[ "$OSTYPE" == "linux"* ]]; then xdg-open "$FRONTEND" 2>/dev/null
elif [[ "$OSTYPE" == "msys"* ]] || [[ "$OSTYPE" == "cygwin"* ]] || [[ "$OSTYPE" == "win"* ]]; then
  start "$FRONTEND"
fi

tail -f "$SCRIPT_DIR/backend.log"
