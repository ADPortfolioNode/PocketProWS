#!/bin/bash
# PocketProWS dev start: backend :5003, frontend :3003 (Vite dev, proxies /api to backend).
set -e
cd "$(dirname "$0")"
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 5003 > /tmp/pocketprows-be.log 2>&1 &
echo $! > /tmp/pocketprows-be.pid
cd frontend && npm run dev > /tmp/pocketprows-fe.log 2>&1 &
echo $! > /tmp/pocketprows-fe.pid
echo "PocketProWS dev up: backend http://127.0.0.1:5003/api/health  frontend http://127.0.0.1:3003"
