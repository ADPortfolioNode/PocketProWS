#!/usr/bin/env bash
# Resolve PocketProWS dev host ports when the defaults are already taken.
#
# Silo-safe: never stop another app's process to free a port. Bump the
# host port by one (up to 10 tries from the preferred port) and wire the
# resolved port through to the backend, the frontend and the printed URLs.
#
# The check is a UNION of probes (bind test, connect probe, listener
# listings): a port counts as in use when ANY probe says so. No single
# probe is trustworthy everywhere — on Windows a bind test with
# SO_REUSEADDR can succeed against a real listener (proven 2026-11-21:
# the resolver passed 5003 as free, then uvicorn and the Docker daemon
# both failed to bind it with error 10048, and the holder was not
# PocketProWS). A Docker-only check would miss host processes, and a
# `docker ps` check would miss a stopped container — neither matters
# here, because if anything is listening on the port, our server cannot
# bind it, whatever the holder is.
#
# An already-set POCKETPROWS_*_PORT is honoured only when it is free;
# when it is busy we bump from it instead of trusting it blindly.

# Find a real Python 3 interpreter, as an array in PY_CMD (empty when none
# works). On Windows, `python3` is often the Microsoft Store stub (an App
# execution alias): `command -v` finds it, but running it only prints
# "Python was not found..." and exits non-zero. So a candidate only counts
# when it actually runs Python code. Tries python3, python, py -3.12,
# py -3, then python3.12 last (so a stubbed `python` and the Windows
# launcher layout win first; python3.12 only matters on Unix where the
# other names may point at a newer Python). The result is cached for
# the life of the shell.
#
# Version preference: among candidates that run, prefer one reporting
# Python 3.12, because the pinned chromadb's hnswlib ships prebuilt wheels
# only up to cp312 — no hnswlib version ships cp313 wheels, so a 3.13+
# interpreter makes `pip install` fall back to building hnswlib from
# source, which needs Microsoft C++ Build Tools. When no 3.12 is available
# we fall back to the first working candidate (preserving the old order)
# and print a warning naming the problem.
PY_CMD=()

find_python() {
    if [ "${#PY_CMD[@]}" -gt 0 ]; then
        return 0
    fi
    local spec
    local -a cmd fallback=()
    local fallback_version=""
    for spec in "python3" "python" "py -3.12" "py -3" "python3.12"; do
        # Word-split the fixed literal spec into the command array.
        cmd=($spec)
        if ! command -v "${cmd[0]}" >/dev/null 2>&1; then
            continue
        fi
        if ! "${cmd[@]}" -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >/dev/null 2>&1; then
            continue
        fi
        local ver
        ver="$("${cmd[@]}" -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>/dev/null)"
        if [ "$ver" = "3 12" ]; then
            PY_CMD=("${cmd[@]}")
            echo "Using Python ${cmd[*]} ($("${cmd[@]}" --version 2>&1))" >&2
            return 0
        fi
        if [ "${#fallback[@]}" -eq 0 ]; then
            fallback=("${cmd[@]}")
            fallback_version="$ver"
        fi
    done
    if [ "${#fallback[@]}" -gt 0 ]; then
        PY_CMD=("${fallback[@]}")
        echo "Using Python ${fallback[*]} ($("${fallback[@]}" --version 2>&1))" >&2
        local vmaj vmin
        read -r vmaj vmin <<< "$fallback_version"
        if [ "$vmaj" = "3" ] && [ -n "$vmin" ] && [ "$vmin" -ge 13 ] 2>/dev/null; then
            echo "WARNING: Python ${vmaj}.${vmin} has no prebuilt chromadb wheels;" >&2
            echo "the backend install will try to build chroma-hnswlib from source and needs Microsoft C++ Build Tools (or a Python 3.12 venv)." >&2
        fi
        return 0
    fi
    PY_CMD=()
    return 1
}

host_port_in_use() {
    local port="$1"

    # Union of probes: the port is in use when ANY probe says so, and
    # free only when every available probe says free. Each probe covers
    # a hole in the others (see the header comment).
    if find_python; then
        # Probe 1+2 in one Python pass. Bind test: fails only when the
        # port is really held (a connect test alone would be wrong —
        # when a holder's accept queue is full, the connect times out
        # and looks "free"). Connect probe: catches the Windows case
        # the bind test misses, where SO_REUSEADDR lets our bind
        # succeed against a live listener — if something accepts a
        # connection, the port is held, full stop.
        "${PY_CMD[@]}" -c 'import errno, socket, sys
port = int(sys.argv[1])
addrs = ((socket.AF_INET, ("127.0.0.1", port)),
         (socket.AF_INET6, ("::1", port, 0, 0)))
for family, addr in addrs:
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        continue
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(addr)
    except OSError as e:
        s.close()
        if e.errno == errno.EADDRINUSE:
            sys.exit(0)
        continue
    s.close()
for family, addr in addrs:
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        continue
    s.settimeout(0.5)
    try:
        s.connect(addr)
    except OSError:
        s.close()
        continue
    s.close()
    sys.exit(0)
sys.exit(1)' "$port" 2>/dev/null
        if [ $? -eq 0 ]; then
            return 0
        fi
    fi

    # Probe 3: ss / netstat listener listings.
    if command -v ss >/dev/null 2>&1; then
        if ss -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"; then
            return 0
        fi
    elif command -v netstat >/dev/null 2>&1; then
        if netstat -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"; then
            return 0
        fi
    fi

    # Probe 4: Windows (Git Bash) — PowerShell's listener table is
    # authoritative there and is consulted even when Python exists;
    # gating it behind "no Python" is what let a held 5003 through.
    case "$(uname -s 2>/dev/null || echo unknown)" in
        MINGW*|MSYS*|CYGWIN*)
            if command -v powershell.exe >/dev/null 2>&1; then
                if powershell.exe -NoProfile -Command \
                    "if (Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) { exit 0 } else { exit 1 }" \
                    >/dev/null 2>&1; then
                    return 0
                fi
            fi
            ;;
    esac

    return 1
}

find_free_host_port() {
    local preferred="$1"
    local max_tries="${2:-10}"
    local port="$preferred"
    local tries=0

    while [ "$tries" -lt "$max_tries" ]; do
        if ! host_port_in_use "$port"; then
            echo "$port"
            return 0
        fi
        port=$((port + 1))
        tries=$((tries + 1))
    done

    return 1
}

resolve_host_port() {
    local var_name="$1"
    local preferred="$2"
    local current="${!var_name:-}"

    # An explicit port is honoured when it is free; when it is busy we
    # bump from it instead of failing on a port we never checked.
    if [ -n "$current" ]; then
        if ! host_port_in_use "$current"; then
            export "$var_name=$current"
            return 0
        fi
        local free_port
        if ! free_port=$(find_free_host_port "$current" 10); then
            echo "ERROR: Could not find a free host port near $current for $var_name." >&2
            return 1
        fi
        export "$var_name=$free_port"
        echo "Host port $current is busy; using $free_port for $var_name." >&2
        return 0
    fi

    if ! host_port_in_use "$preferred"; then
        export "$var_name=$preferred"
        return 0
    fi

    local free_port
    if ! free_port=$(find_free_host_port "$preferred" 10); then
        echo "ERROR: Could not find a free host port near $preferred for $var_name." >&2
        return 1
    fi

    export "$var_name=$free_port"
    echo "Host port $preferred is busy; using $free_port for $var_name." >&2
    return 0
}

resolve_pocketprows_ports() {
    resolve_host_port POCKETPROWS_BE_PORT 5003 || return 1
    resolve_host_port POCKETPROWS_FE_PORT 3003 || return 1
    return 0
}
