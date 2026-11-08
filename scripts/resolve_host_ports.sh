#!/usr/bin/env bash
# Resolve PocketProWS dev host ports when the defaults are already taken.
#
# Silo-safe: never stop another app's process to free a port. Bump the
# host port by one (up to 10 tries from the preferred port) and wire the
# resolved port through to the backend, the frontend and the printed URLs.
#
# The check is a real TCP bind test, so any holder counts: another
# app's container (a published port is a host listener), a host process,
# or a stale server. A Docker-only check would miss host processes, and
# a `docker ps` check would miss a stopped container — neither matters
# here, because this stack runs on the host: if nothing is listening on
# the port, our server can bind it.
#
# An already-set POCKETPROWS_*_PORT is honoured only when it is free;
# when it is busy we bump from it instead of trusting it blindly.

host_port_in_use() {
    local port="$1"

    # 1. Real bind test (authoritative for a host-process stack). We try
    # to bind the port exactly as our server will: a bind fails only when
    # the port is really held. A connect test would be wrong here — when
    # a holder's accept queue is full, the connect times out and looks
    # "free" even though the port is taken.
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import errno, socket, sys
port = int(sys.argv[1])
for family, addr in ((socket.AF_INET, ("127.0.0.1", port)),
                     (socket.AF_INET6, ("::1", port, 0, 0))):
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
sys.exit(1)' "$port" 2>/dev/null
        return $?
    fi

    # 2. ss / netstat listener listings.
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"
        return $?
    fi

    if command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"
        return $?
    fi

    # 3. Windows (Git Bash): ask PowerShell for a listener on the port.
    case "$(uname -s 2>/dev/null || echo unknown)" in
        MINGW*|MSYS*|CYGWIN*)
            if command -v powershell.exe >/dev/null 2>&1; then
                powershell.exe -NoProfile -Command \
                    "if (Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) { exit 0 } else { exit 1 }" \
                    >/dev/null 2>&1
                return $?
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
