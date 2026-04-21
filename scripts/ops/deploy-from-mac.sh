#!/bin/bash
# Deploy pearl-algo from Mac (control plane) to Beelink (runtime).
# Flow: push local main -> SSH to pearlalgo -> git pull -> (optional) restart service.
#
# Usage:
#   ./scripts/ops/deploy-from-mac.sh                 # sync only (safe during market hours)
#   ./scripts/ops/deploy-from-mac.sh --restart       # full pearl.sh restart (disruptive)
#   ./scripts/ops/deploy-from-mac.sh --tv-paper      # restart trading agent only
#   ./scripts/ops/deploy-from-mac.sh --chart         # rebuild + restart web app only
#   ./scripts/ops/deploy-from-mac.sh --status        # pull + print pearl.sh status
#
# Refuses to run if the local tree has uncommitted changes — commit first.

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'

REMOTE_HOST="${PEARLALGO_HOST:-pearlalgo}"
REMOTE_PATH="${PEARLALGO_PATH:-~/projects/pearl-algo}"

RESTART_MODE="none"
for arg in "$@"; do
    case "$arg" in
        --restart)    RESTART_MODE="full" ;;
        --tv-paper)   RESTART_MODE="tv-paper" ;;
        --chart)      RESTART_MODE="chart" ;;
        --status)     RESTART_MODE="status" ;;
        -h|--help)
            sed -n '2,13p' "$0" | sed 's/^# *//'
            exit 0
            ;;
        *)
            echo "${RED}Unknown argument: $arg${NC}" >&2
            exit 2
            ;;
    esac
done

cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "${RED}ERROR: uncommitted changes on Mac. Commit or stash before deploying.${NC}"
    git status --short
    exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
    echo "${YELLOW}WARN: not on main (current: $BRANCH). Pushing branch as-is.${NC}"
fi

echo "${CYAN}==> Pushing $BRANCH to origin${NC}"
git push origin "$BRANCH"

echo "${CYAN}==> Pulling on $REMOTE_HOST${NC}"
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && git fetch origin && git reset --hard origin/$BRANCH && git log --oneline -1"

case "$RESTART_MODE" in
    none)
        echo ""
        echo "${GREEN}Code synced. Trading service still running on old code.${NC}"
        echo "When ready to apply changes (outside market hours or per your judgment):"
        echo "  ${CYAN}./scripts/ops/deploy-from-mac.sh --tv-paper${NC}   # restart agent only"
        echo "  ${CYAN}./scripts/ops/deploy-from-mac.sh --restart${NC}    # full restart"
        ;;
    full)
        echo "${YELLOW}==> Full restart on $REMOTE_HOST (ALL services)${NC}"
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./pearl.sh restart"
        ;;
    tv-paper)
        echo "${YELLOW}==> Restarting tv-paper (trading agent) on $REMOTE_HOST${NC}"
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./pearl.sh tv-paper restart"
        ;;
    chart)
        echo "${YELLOW}==> Rebuilding + restarting web app on $REMOTE_HOST${NC}"
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./pearl.sh chart deploy"
        ;;
    status)
        echo "${CYAN}==> pearl.sh status on $REMOTE_HOST${NC}"
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./pearl.sh quick"
        ;;
esac

echo ""
echo "${GREEN}Done.${NC}"
