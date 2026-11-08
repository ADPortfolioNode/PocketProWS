#!/bin/bash
# PocketProWS dev start: backend :5003, frontend :3003 (Vite dev, proxies /api to backend).
# Ports bump +1 while taken (up to 10 tries); never stops another app's process.
# The resolved ports are exported as POCKETPROWS_BE_PORT / POCKETPROWS_FE_PORT
# and picked up by backend/config.py and frontend/vite.config.js.
set -e
cd "$(dirname "$0")"
. scripts/resolve_host_ports.sh

resolve_pocketprows_ports
export POCKETPROWS_BE_PORT POCKETPROWS_FE_PORT

# uvicorn via the venv python: .venv/Scripts on Windows, .venv/bin elsewhere.
if [ -x .venv/Scripts/python.exe ]; then
    VENV_PY=.venv/Scripts/python.exe
elif [ -x .venv/Scripts/python ]; then
    VENV_PY=.venv/Scripts/python
elif [ -x .venv/bin/python ]; then
    VENV_PY=.venv/bin/python
else
    echo "No venv python found (.venv/Scripts/python or .venv/bin/python). Run the setup first:" >&2
    echo "  python3 -m venv .venv && .venv/Scripts/pip install -r backend/requirements-dev.txt" >&2
    exit 1
fi

if [ ! -x frontend/node_modules/.bin/vite ]; then
    echo "Vite not found (frontend/node_modules/.bin/vite). Run this first:" >&2
    echo "  cd frontend && npm install && npm run build && cd .." >&2
    exit 1
fi

"$VENV_PY" -m uvicorn backend.main:app --host 127.0.0.1 --port "$POCKETPROWS_BE_PORT" > /tmp/pocketprows-be.log 2>&1 &
echo $! > /tmp/pocketprows-be.pid
(cd frontend && exec ./node_modules/.bin/vite) > /tmp/pocketprows-fe.log 2>&1 &
echo $! > /tmp/pocketprows-fe.pid

# Wait for both servers to answer on their resolved ports before reporting up.
# A port that resolves free can still fail to serve (a race, a slow first
# boot); report that instead of claiming "up" on a dead server.
wait_for() {
    local url="$1"
    local timeout="$2"
    local tries=0
    while [ "$tries" -lt "$timeout" ]; do
        if curl -s -f "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        tries=$((tries + 1))
    done
    return 1
}

if command -v curl >/dev/null 2>&1; then
    if ! wait_for "http://127.0.0.1:${POCKETPROWS_BE_PORT}/api/health" 30 || ! wait_for "http://127.0.0.1:${POCKETPROWS_FE_PORT}/" 15; then
        echo "PocketProWS dev failed to come up; stopping what was started." >&2
        echo "--- backend log (tail) ---" >&2
        tail -20 /tmp/pocketprows-be.log >&2 || true
        echo "--- frontend log (tail) ---" >&2
        tail -20 /tmp/pocketprows-fe.log >&2 || true
        kill "$(cat /tmp/pocketprows-be.pid)" 2>/dev/null || true
        kill "$(cat /tmp/pocketprows-fe.pid)" 2>/dev/null || true
        exit 1
    fi
fi

echo "PocketProWS dev up: backend http://127.0.0.1:${POCKETPROWS_BE_PORT}/api/health  frontend http://127.0.0.1:${POCKETPROWS_FE_PORT}"
