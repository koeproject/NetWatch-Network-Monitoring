#!/usr/bin/env bash
# ops/check-boundary.sh -- enforce CLAUDE.md §4.
#
# Fails if an engine-specific word appears in the guarded paths. The only
# places allowed to know the engine are backend/app/zabbix/** and
# backend/app/container.py -- neither is scanned here.
#
# Runs in CI on every commit, and as a PostToolUse hook on every Write/Edit.
# Exit 0 = clean. Exit 2 = violation (Claude Code feeds stderr back to the model).

set -euo pipefail

cd "$(dirname "$0")/.."

GUARDED=(
  backend/app/domain
  backend/app/services
  backend/app/api
  backend/app/auth
  frontend
)

EXCLUDES=(
  --exclude-dir=node_modules
  --exclude-dir=dist
  --exclude-dir=.venv
  --exclude-dir=__pycache__
  '--exclude=*.pyc'
)

# Paths are rebuilt one step at a time — skip the ones that do not exist yet.
targets=()
for d in "${GUARDED[@]}"; do
  [ -e "$d" ] && targets+=("$d")
done

if [ ${#targets[@]} -eq 0 ]; then
  echo "check-boundary: no guarded paths exist yet — OK"
  exit 0
fi

found=0

# $1 = label, rest = grep pattern args
report() {
  local label=$1; shift
  local hits
  if hits=$(grep -rnI "${EXCLUDES[@]}" "$@" "${targets[@]}"); then
    echo "BOUNDARY VIOLATION [$label]:" >&2
    echo "$hits" >&2
    found=1
  fi
}

# Engine name, any case, anywhere in a word: ZabbixClient, ZABBIX_URL, ...
report "engine name"  -i  -e 'zabbix'

# Engine IDs. "_" counts as a separator, so device_hostid and hostids are caught.
report "engine id"    -iE -e '(^|[^a-z0-9])(event|host|item|trigger)ids?([^a-z0-9]|$)'
# camelCase: deviceHostId, problemEventIds
report "engine id"    -E  -e '[a-z0-9](Event|Host|Item|Trigger)Ids?([^a-z]|$)'

# Short field names. Not -w: grep counts "_" as a word char, so -w misses
# clock_ns / event_clock. "_" and camelCase humps count as separators here:
# clock, Clock, event_clock, clock_ns, clockNs, eventClock -- but not clocks,
# clockwise, dns, namespace.
report "engine field" -E  -e '(^|[^A-Za-z0-9])([Cc]lock|ns)([^a-z0-9]|$)' -e '[a-z0-9](Clock|Ns)([^a-z]|$)'

if [ "$found" -ne 0 ]; then
  echo "See CLAUDE.md §4: use device_ref / problem_ref; only zabbix/mapper.py knows the real IDs." >&2
  exit 2
fi

echo "check-boundary: OK (${targets[*]})"