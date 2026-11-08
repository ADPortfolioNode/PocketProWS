#!/bin/bash
# PocketProWS dev stop.
kill "$(cat /tmp/pocketprows-be.pid)" 2>/dev/null || true
kill "$(cat /tmp/pocketprows-fe.pid)" 2>/dev/null || true
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
# No vite pkill: start-dev.sh execs vite directly, so the pid file holds
# the real vite PID and the kill above already stops it. A bare `pkill -f vite`
# could kill another project's dev server, so it is deliberately not here.
echo "PocketProWS dev stopped."
