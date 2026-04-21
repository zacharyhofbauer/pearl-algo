#!/bin/bash
# Read-only health probe for pearl-algo from the Mac.
# Shells to the Beelink via Tailscale SSH, runs `pearl.sh quick`, parses the output,
# and exits non-zero if any service is not green.
#
# Usage:
#   ./scripts/ops/health-from-mac.sh          # human-readable output
#   ./scripts/ops/health-from-mac.sh --json   # machine-readable: {"status":"green"|"red","services":{...}}
#
# Suitable for cron, Mission Control polling, or wiring into alerting.

set -euo pipefail

REMOTE_HOST="${PEARLALGO_HOST:-pearlalgo}"
REMOTE_PATH="${PEARLALGO_PATH:-~/projects/pearl-algo}"
OUTPUT_MODE="human"

for arg in "$@"; do
    case "$arg" in
        --json) OUTPUT_MODE="json" ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# *//'
            exit 0
            ;;
    esac
done

RAW="$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE_HOST" "cd $REMOTE_PATH && ./pearl.sh quick" 2>&1 || true)"

if [[ -z "$RAW" ]]; then
    if [[ "$OUTPUT_MODE" == "json" ]]; then
        echo '{"status":"unreachable","services":{},"raw":""}'
    else
        echo "UNREACHABLE: no output from $REMOTE_HOST"
    fi
    exit 2
fi

STATUS="green"
declare -a SERVICES=()
while IFS= read -r line; do
    CLEAN="$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g')"
    if [[ "$CLEAN" == *"PEARL:"* ]]; then
        PARTS="${CLEAN#*PEARL: }"
        IFS='|' read -ra TOKENS <<< "$PARTS"
        for tok in "${TOKENS[@]}"; do
            tok="$(echo "$tok" | xargs)"
            NAME="${tok%% *}"
            STATE="${tok##* }"
            SERVICES+=("$NAME:$STATE")
            if [[ "$STATE" != *"✅"* ]]; then
                STATUS="red"
            fi
        done
        break
    fi
done <<< "$RAW"

if [[ "$OUTPUT_MODE" == "json" ]]; then
    SVC_JSON=""
    for entry in "${SERVICES[@]}"; do
        NAME="${entry%%:*}"
        STATE="${entry#*:}"
        SVC_JSON+="\"$NAME\":\"$STATE\","
    done
    SVC_JSON="${SVC_JSON%,}"
    echo "{\"status\":\"$STATUS\",\"services\":{$SVC_JSON}}"
else
    echo "$RAW"
    echo ""
    echo "Status: $STATUS"
fi

[[ "$STATUS" == "green" ]] && exit 0 || exit 1
