#!/bin/bash
# PocketProWS dev stop.
kill "$(cat /tmp/pocketprows-be.pid)" 2>/dev/null || true
kill "$(cat /tmp/pocketprows-fe.pid)" 2>/dev/null || true
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
pkill -f "vite --port 3003" 2>/dev/null || true
echo "PocketProWS dev stopped."
