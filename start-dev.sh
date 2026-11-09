#!/bin/bash
# PocketProWS dev start — alias for ./start.sh (the standard one-command
# entry point). Kept so the old command still works.
exec "$(dirname "$0")/start.sh" "$@"
