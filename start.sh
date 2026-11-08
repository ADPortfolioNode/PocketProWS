#!/usr/bin/env bash
set -euo pipefail

# PocketProWS one-command startup.
# Same pattern as the other PocketPro projects: one command, persistent data
# (the Chroma data dir is never wiped by this script), silo-safe ports.
#
# Usage: ./start.sh [--build] [--rebuild] [--no-build] [--test] [--down]
#   (default)  start the dev stack (builds the venv/frontend first if missing)
#   --build    recreate the venv from scratch + clean frontend install
#              and build, then start
#   --rebuild  reinstall backend deps + frontend install and build
#              (cached), then start
#   --no-build start without building (errors if the venv or frontend
#              deps are missing)
#   --test     monitored startup: wait for both health endpoints and
#              report PASS/FAIL (the stack keeps running either way)
#   --down     stop the stack (data is kept)
#
# Run from the pocketprows folder in Git Bash.
# Backend :5003, frontend :3003 (Vite dev, proxies /api). If a port is held
# by another app, it bumps to 5004..5013 and the stack still starts; a stale
# PocketProWS server is stopped instead and the port is kept.
# start-dev.sh is an alias for ./start.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck source=scripts/resolve_host_ports.sh
. "${SCRIPT_DIR}/scripts/resolve_host_ports.sh"

# --- Flags ---
BUILD=false
REBUILD=false
NO_BUILD=false
TEST_REQUESTED=false
DOWN=false

while [ "${#}" -gt 0 ]; do
    case "$1" in
        --build) BUILD=true; shift ;;
        --rebuild) REBUILD=true; shift ;;
        --no-build) NO_BUILD=true; shift ;;
        --test) TEST_REQUESTED=true; shift ;;
        --down) DOWN=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--build] [--rebuild] [--no-build] [--test] [--down]"
            echo "  (default)  start the dev stack (builds first if the venv or frontend deps are missing)"
            echo "  --build    recreate the venv from scratch + clean frontend install and build, then start"
            echo "  --rebuild  reinstall backend deps + frontend install and build (cached), then start"
            echo "  --no-build start without building (errors if deps are missing)"
            echo "  --test     monitored startup: wait for both health endpoints, report PASS/FAIL"
            echo "  --down     stop the stack (data is kept)"
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; echo "Usage: $0 [--build] [--rebuild] [--no-build] [--test] [--down]" >&2; exit 2 ;;
    esac
done

# --- Stop (data is kept) ---
if [ "${DOWN}" = true ]; then
    echo "Stopping PocketProWS (data is kept)..."
    bash "${SCRIPT_DIR}/stop-dev.sh"
    exit 0
fi

# --- Venv helpers (Windows .venv/Scripts, Linux/macOS .venv/bin) ---
find_venv_python() {
    if [ -x .venv/Scripts/python.exe ]; then
        echo ".venv/Scripts/python.exe"
    elif [ -x .venv/Scripts/python ]; then
        echo ".venv/Scripts/python"
    elif [ -x .venv/bin/python ]; then
        echo ".venv/bin/python"
    else
        echo ""
    fi
}

find_venv_pip() {
    if [ -x .venv/Scripts/pip.exe ]; then
        echo ".venv/Scripts/pip.exe"
    elif [ -x .venv/Scripts/pip ]; then
        echo ".venv/Scripts/pip"
    elif [ -x .venv/bin/pip ]; then
        echo ".venv/bin/pip"
    else
        echo ""
    fi
}

venv_missing() {
    [ -z "$(find_venv_python)" ]
}

frontend_missing() {
    [ ! -x frontend/node_modules/.bin/vite ]
}

# --- Build steps ---
# --build recreates the venv from scratch (the --no-cache analogue);
# --rebuild reuses the existing venv and install caches.
run_build() {
    local from_scratch="$1"
    if [ "${from_scratch}" = true ] || venv_missing; then
        # find_python (scripts/resolve_host_ports.sh) verifies the
        # interpreter actually runs: on Windows, `python3` is often just
        # the Microsoft Store shortcut, which prints "Python was not
        # found..." instead of running.
        if ! find_python; then
            echo "ERROR: No working Python 3 found (tried python3, python, py -3)." >&2
            echo "On Windows, 'python3' is often just the Microsoft Store shortcut:" >&2
            echo "install Python from python.org (check 'Add Python to PATH'), or" >&2
            echo "turn the Store shortcut off in Settings > Apps > Advanced app settings > App execution aliases." >&2
            exit 1
        fi
        if [ "${from_scratch}" = true ]; then
            echo "Building from scratch: recreating the venv..."
            rm -rf .venv
        else
            echo "Creating the venv..."
        fi
        "${PY_CMD[@]}" -m venv .venv
    fi

    local pip
    pip="$(find_venv_pip)"
    if [ -z "${pip}" ]; then
        echo "ERROR: No venv pip found (.venv/Scripts/pip or .venv/bin/pip)." >&2
        exit 1
    fi
    echo "Installing backend deps..."
    "${pip}" install -r backend/requirements-dev.txt

    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: 'npm' not found. Install Node.js, then run ./start.sh --build again." >&2
        exit 1
    fi
    if [ "${from_scratch}" = true ]; then
        echo "Installing frontend deps (clean, from the lockfile)..."
        (cd frontend && npm ci)
    else
        echo "Installing frontend deps..."
        (cd frontend && npm install)
    fi
    echo "Building the frontend..."
    (cd frontend && npm run build)
}

if [ "${BUILD}" = true ]; then
    run_build true
elif [ "${REBUILD}" = true ]; then
    run_build false
elif [ "${NO_BUILD}" = false ] && { venv_missing || frontend_missing; }; then
    echo "First run (or missing deps) — building once. Use --no-build to skip this."
    run_build false
fi

# --- Preflight: the servers must be runnable now ---
VENV_PY="$(find_venv_python)"
if [ -z "${VENV_PY}" ]; then
    echo "ERROR: No venv python found (.venv/Scripts/python or .venv/bin/python)." >&2
    echo "Run ./start.sh --build to create it." >&2
    exit 1
fi
if frontend_missing; then
    echo "ERROR: Vite not found (frontend/node_modules/.bin/vite)." >&2
    echo "Run ./start.sh --build to install the frontend deps." >&2
    exit 1
fi

# --- Stop stale PocketProWS servers, then resolve ports ---
# A stale server of this app holds its port; stopping it keeps the port.
# Anything else holding the port gets a bump instead (never stopped).
echo "Stopping any stale PocketProWS servers..."
bash "${SCRIPT_DIR}/stop-dev.sh" >/dev/null 2>&1 || true
sleep 1

resolve_pocketprows_ports || {
    echo "ERROR: Unable to resolve host ports." >&2
    exit 1
}
export POCKETPROWS_BE_PORT POCKETPROWS_FE_PORT
echo "Backend host port: ${POCKETPROWS_BE_PORT}"
echo "Frontend host port: ${POCKETPROWS_FE_PORT}"

# --- Start ---
"${VENV_PY}" -m uvicorn backend.main:app --host 127.0.0.1 --port "${POCKETPROWS_BE_PORT}" > /tmp/pocketprows-be.log 2>&1 &
echo $! > /tmp/pocketprows-be.pid
(cd frontend && exec ./node_modules/.bin/vite) > /tmp/pocketprows-fe.log 2>&1 &
echo $! > /tmp/pocketprows-fe.pid

# --- Wait for both servers to answer on their resolved ports ---
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

fail_startup() {
    if [ "${TEST_REQUESTED}" = true ]; then
        echo "STARTUP TEST FAILED" >&2
    else
        echo "PocketProWS failed to come up; stopping what was started." >&2
    fi
    echo "--- backend log (tail) ---" >&2
    tail -20 /tmp/pocketprows-be.log >&2 || true
    echo "--- frontend log (tail) ---" >&2
    tail -20 /tmp/pocketprows-fe.log >&2 || true
    kill "$(cat /tmp/pocketprows-be.pid)" 2>/dev/null || true
    kill "$(cat /tmp/pocketprows-fe.pid)" 2>/dev/null || true
    exit 1
}

if [ "${TEST_REQUESTED}" = true ]; then
    BE_TIMEOUT=60
    FE_TIMEOUT=30
else
    BE_TIMEOUT=30
    FE_TIMEOUT=15
fi

if command -v curl >/dev/null 2>&1; then
    if ! wait_for "http://127.0.0.1:${POCKETPROWS_BE_PORT}/api/health" "${BE_TIMEOUT}" || ! wait_for "http://127.0.0.1:${POCKETPROWS_FE_PORT}/" "${FE_TIMEOUT}"; then
        fail_startup
    fi
fi

print_success() {
    echo ""
    echo "================================================="
    echo "PocketProWS Started Successfully"
    echo "================================================="
    echo ""
    echo "  Backend:  http://127.0.0.1:${POCKETPROWS_BE_PORT}/api/health"
    echo "  Frontend: http://127.0.0.1:${POCKETPROWS_FE_PORT}"
    echo ""
    echo "To view logs, run:"
    echo "  tail -f /tmp/pocketprows-be.log /tmp/pocketprows-fe.log"
    echo "To stop (data is kept), run:"
    echo "  ./start.sh --down"
}

if [ "${TEST_REQUESTED}" = true ]; then
    echo ""
    echo "STARTUP TEST PASSED — backend and frontend are up"
    print_success
    exit 0
fi

print_success
