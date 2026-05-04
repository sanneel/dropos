#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.backend.pid"
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"; rm -f "$PID_FILE"
    echo -e "${GREEN}DropOS stopped${NC}"
  else rm -f "$PID_FILE"; echo "Not running"
  fi
else
  PID=$(lsof -ti:8000 2>/dev/null | head -1)
  [ -n "$PID" ] && kill "$PID" && echo -e "${GREEN}Stopped${NC}" || echo "Not running"
fi
