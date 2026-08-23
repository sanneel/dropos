#!/bin/bash

# DropOS — Start Script
# Usage: ./start.sh
# Loads .env (if present), starts the backend on :8000 and opens the backoffice.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
PID_FILE="$SCRIPT_DIR/.backend.pid"
URL="http://localhost:8000"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Resolve python command — python, python3, then the Windows py launcher
_py_ok() { "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; }
if command -v python &>/dev/null && _py_ok python; then
  PY=python
elif command -v python3 &>/dev/null && _py_ok python3; then
  PY=python3
elif command -v py &>/dev/null && _py_ok py; then
  PY=py
else
  _WIN_PY="$(ls /c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe 2>/dev/null | head -1)"
  if [ -n "$_WIN_PY" ] && _py_ok "$_WIN_PY"; then
    PY="$_WIN_PY"
  else
    echo -e "${RED}Python 3.10+ not found. Install from python.org${NC}"; exit 1
  fi
fi

echo ""
echo -e "${BOLD}  DropOS Backoffice${NC}"
echo -e "  ${CYAN}-------------------------------${NC}"
echo -e "  ${CYAN}Python: $($PY --version)${NC}"

# Load .env without shell expansion (bcrypt hashes contain '$')
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue;; esac
    key="${line%%=*}"; val="${line#*=}"
    export "$key=$val"
  done < "$SCRIPT_DIR/.env"
  echo -e "  ${CYAN}Loaded .env${NC}"
else
  echo -e "  ${CYAN}No .env — running with defaults (embedded DB, first-run setup in the browser)${NC}"
fi

if [ -z "$DATABASE_URL" ]; then
  echo -e "  ${CYAN}No DATABASE_URL — using the embedded PostgreSQL in ./data/pg${NC}"
fi

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
if ! $PY -c "import fastapi,uvicorn,asyncpg,httpx,apscheduler,bcrypt,jwt,slowapi,pgserver,playwright" 2>/dev/null; then
  echo -e "  ${YELLOW}Installing dependencies (first run can take a few minutes)...${NC}"
  $PY -m pip install -r requirements.txt -q
fi
# Chromium for the CSSBuy scraper (no-op when already installed)
$PY -m playwright install chromium >/dev/null 2>&1 || echo -e "  ${YELLOW}Playwright Chromium install failed — scraping will not work until you run: $PY -m playwright install chromium${NC}"

echo -e "  ${CYAN}Starting backend on port 8000...${NC}"
nohup $PY -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/backend.log" 2>&1 &
BACKEND_PID=$!; echo $BACKEND_PID > "$PID_FILE"

# Wait for backend to be ready (up to 20s)
for i in {1..40}; do
  curl -s "$URL/health" >/dev/null 2>&1 && break
  sleep 0.5
done

if ! curl -s "$URL/health" >/dev/null 2>&1; then
  echo -e "  ${RED}Backend failed to start. Check backend.log for errors.${NC}"
  tail -n 40 "$SCRIPT_DIR/backend.log"
  exit 1
fi

echo -e "  ${GREEN}DropOS is running!${NC}"
echo -e "  Dashboard: $URL"
echo -e "  Logs:      tail -f $SCRIPT_DIR/backend.log"
echo -e "  Stop:      ./stop.sh"
echo ""

if [[ "$OSTYPE" == "darwin"* ]]; then open "$URL"
elif [[ "$OSTYPE" == "linux"* ]]; then xdg-open "$URL" 2>/dev/null
elif [[ "$OSTYPE" == "msys"* ]] || [[ "$OSTYPE" == "cygwin"* ]] || [[ "$OSTYPE" == "win"* ]]; then
  start "$URL"
fi

tail -f "$SCRIPT_DIR/backend.log"
