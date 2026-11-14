#!/bin/bash
# PocketProWS dev stop.
# End the recorded session first: start.sh writes the session's exact
# ports and process ids to a session file, and those pids are this app's
# own by construction. The pid files and sweeps below are the backstop
# for sessions started before the record existed or whose file was lost.
SESSION_FILE=/tmp/pocketprows-session.env
if [ -f "${SESSION_FILE}" ]; then
    for key in POCKETPROWS_BE_PID POCKETPROWS_FE_PID; do
        pid="$(sed -n "s/^${key}=//p" "${SESSION_FILE}" | head -1)"
        case "${pid}" in
            ''|*[!0-9]*) ;;
            *) kill "${pid}" 2>/dev/null || true ;;
        esac
    done
    rm -f "${SESSION_FILE}"
fi
kill "$(cat /tmp/pocketprows-be.pid)" 2>/dev/null || true
kill "$(cat /tmp/pocketprows-fe.pid)" 2>/dev/null || true
pkill -f "uvicorn backend.main:app" 2>/dev/null || true

# Orphan sweep: a server started outside start.sh (or whose pid file was
# lost) survives the kills above, keeps this app's usual ports, and goes
# on serving a stale frontend/backend pairing — the page then talks to
# whatever holds the backend port and every workflow 404s. A bare
# `pkill -f vite` stays deliberately OFF the table (it could kill another
# project's dev server); instead, stop only processes that provably
# belong to THIS checkout:
# - Linux: working directory inside this repo AND a vite/esbuild/uvicorn
#   command line.
# - Windows (Git Bash): node/python/esbuild whose executable path or
#   command line references this checkout (the same rule start.sh's
#   free_frontend_modules uses for locked node_modules).
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -s)" in
    Linux*)
        for proc in /proc/[0-9]*; do
            cwd="$(readlink "${proc}/cwd" 2>/dev/null)" || continue
            case "${cwd}" in
                "${ROOT}"|"${ROOT}"/*) ;;
                *) continue ;;
            esac
            cmd="$(tr '\0' ' ' < "${proc}/cmdline" 2>/dev/null)"
            case "${cmd}" in
                *vite*|*esbuild*|*"uvicorn backend.main"*)
                    kill "${proc#/proc/}" 2>/dev/null || true
                    ;;
            esac
        done
        ;;
    MINGW*|MSYS*|CYGWIN*)
        if command -v cygpath >/dev/null 2>&1 && command -v powershell.exe >/dev/null 2>&1; then
            PPWS_ROOT_WIN="$(cygpath -w "${ROOT}" 2>/dev/null || true)"
            if [ -n "${PPWS_ROOT_WIN}" ]; then
                export PPWS_ROOT_WIN
                powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.ProcessId -ne \$PID -and \$_.Name -in 'node.exe','python.exe','esbuild.exe' -and ((\$_.ExecutablePath -like \"\$env:PPWS_ROOT_WIN*\") -or (\$_.CommandLine -like \"*\$env:PPWS_ROOT_WIN*\")) } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
            fi
        fi
        ;;
esac
echo "PocketProWS dev stopped."
