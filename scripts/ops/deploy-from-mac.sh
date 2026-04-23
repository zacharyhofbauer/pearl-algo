#!/bin/bash
# Deploy pearl-algo from Mac (control plane) to Beelink (runtime).
# Flow: push local branch -> SSH -> git reset --hard origin/<branch> ->
#       run predeploy_smoke.py -> (optional) restart service. Auto-
#       rolls the Beelink back to the prior SHA if smoke fails.
#
# Usage:
#   ./scripts/ops/deploy-from-mac.sh                 # sync + smoke, NO restart (safe during market hours)
#   ./scripts/ops/deploy-from-mac.sh --restart       # sync + smoke + full pearl.sh restart (disruptive)
#   ./scripts/ops/deploy-from-mac.sh --tv-paper      # sync + smoke + restart trading agent only
#   ./scripts/ops/deploy-from-mac.sh --chart         # sync + smoke + rebuild + restart web app only
#   ./scripts/ops/deploy-from-mac.sh --status        # pull + print pearl.sh status (no smoke, no restart)
#   ./scripts/ops/deploy-from-mac.sh --rollback      # revert Beelink to prior SHA (HEAD@{1})
#   ./scripts/ops/deploy-from-mac.sh --rollback --tv-paper  # rollback then restart agent
#   ./scripts/ops/deploy-from-mac.sh --no-smoke      # skip predeploy smoke (escape hatch; NOT default)
#   ./scripts/ops/deploy-from-mac.sh --full-smoke    # run pytest subset as part of smoke (slower)
#
# Refuses to run if the local tree has uncommitted changes — commit first.
# Exit codes: 1 dirty tree, 2 unknown arg, 3 smoke failed (auto-rolled back), 4 rollback failed.

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'

REMOTE_HOST="${PEARLALGO_HOST:-pearlalgo}"
REMOTE_PATH="${PEARLALGO_PATH:-~/projects/pearl-algo}"

RESTART_MODE="none"
SMOKE_MODE="fast"        # fast | full | none
ROLLBACK_MODE="false"

for arg in "$@"; do
    case "$arg" in
        --restart)     RESTART_MODE="full" ;;
        --tv-paper)    RESTART_MODE="tv-paper" ;;
        --chart)       RESTART_MODE="chart" ;;
        --status)      RESTART_MODE="status" ;;
        --rollback)    ROLLBACK_MODE="true" ;;
        --no-smoke)    SMOKE_MODE="none" ;;
        --full-smoke)  SMOKE_MODE="full" ;;
        -h|--help)
            sed -n '2,19p' "$0" | sed 's/^# *//'
            exit 0
            ;;
        *)
            echo "${RED}Unknown argument: $arg${NC}" >&2
            exit 2
            ;;
    esac
done

cd "$(git rev-parse --show-toplevel)"

# ────────────────────────────────────────────────────────────────────
# Rollback path: revert Beelink to HEAD@{1}, then (optionally) restart.
# ────────────────────────────────────────────────────────────────────
if [[ "$ROLLBACK_MODE" == "true" ]]; then
    echo "${YELLOW}==> ROLLBACK: reverting $REMOTE_HOST:$REMOTE_PATH to HEAD@{1}${NC}"

    set +e
    ROLLBACK_OUTPUT="$(ssh "$REMOTE_HOST" "cd $REMOTE_PATH && \
        echo PRIOR=\$(git rev-parse HEAD) && \
        git reset --hard HEAD@{1} && \
        echo NOW=\$(git rev-parse HEAD) && \
        git log --oneline -1")"
    ROLLBACK_STATUS=$?
    set -e

    echo "$ROLLBACK_OUTPUT"
    if [[ $ROLLBACK_STATUS -ne 0 ]]; then
        echo "${RED}ERROR: rollback command failed on $REMOTE_HOST (exit $ROLLBACK_STATUS).${NC}" >&2
        echo "${RED}Reflog may be empty or \`git reset --hard HEAD@{1}\` was rejected.${NC}" >&2
        exit 4
    fi
    echo "${GREEN}Rollback applied.${NC}"
    # Fall through to the RESTART_MODE case so operator can optionally
    # restart with the rolled-back SHA. Skip smoke on rollback because
    # HEAD@{1} was, by definition, a previously-good SHA.
    SMOKE_MODE="none"
else
    # ──────────────────────────────────────────────────────────────
    # Forward deploy path: guard dirty tree, push, record PRIOR_SHA,
    # reset forward, run smoke, rollback on failure, then restart.
    # ──────────────────────────────────────────────────────────────
    if [[ -n "$(git status --porcelain)" ]]; then
        echo "${RED}ERROR: uncommitted changes on Mac. Commit or stash before deploying.${NC}"
        git status --short
        exit 1
    fi

    BRANCH="$(git branch --show-current)"
    if [[ "$BRANCH" != "main" ]]; then
        echo "${YELLOW}WARN: not on main (current: $BRANCH). Pushing branch as-is.${NC}"
    fi

    # --status is a read-only shortcut; skip push + smoke.
    if [[ "$RESTART_MODE" != "status" ]]; then
        echo "${CYAN}==> Pushing $BRANCH to origin${NC}"
        git push origin "$BRANCH"

        echo "${CYAN}==> Capturing prior SHA on $REMOTE_HOST${NC}"
        PRIOR_SHA="$(ssh "$REMOTE_HOST" "cd $REMOTE_PATH && git rev-parse HEAD")"
        echo "    prior_sha=$PRIOR_SHA"

        echo "${CYAN}==> Pulling on $REMOTE_HOST${NC}"
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && git fetch origin && git reset --hard origin/$BRANCH && git log --oneline -1"

        if [[ "$SMOKE_MODE" != "none" ]]; then
            SMOKE_ARGS=""
            if [[ "$SMOKE_MODE" == "full" ]]; then
                SMOKE_ARGS="--full"
            fi
            echo "${CYAN}==> Running predeploy smoke on $REMOTE_HOST (mode=$SMOKE_MODE)${NC}"
            set +e
            # Use the Beelink's venv python so `import pearlalgo` resolves.
            # Falls back to python3 only if the venv is missing (broken Beelink).
            ssh "$REMOTE_HOST" "cd $REMOTE_PATH && if [ -x .venv/bin/python ]; then ./.venv/bin/python scripts/ops/predeploy_smoke.py $SMOKE_ARGS; else python3 scripts/ops/predeploy_smoke.py $SMOKE_ARGS; fi"
            SMOKE_STATUS=$?
            set -e
            if [[ $SMOKE_STATUS -ne 0 ]]; then
                echo "${RED}==> SMOKE FAILED (exit $SMOKE_STATUS). Rolling back to $PRIOR_SHA.${NC}" >&2
                set +e
                ssh "$REMOTE_HOST" "cd $REMOTE_PATH && git reset --hard $PRIOR_SHA && git log --oneline -1"
                ROLLBACK_STATUS=$?
                set -e
                if [[ $ROLLBACK_STATUS -ne 0 ]]; then
                    echo "${RED}CRITICAL: auto-rollback to $PRIOR_SHA failed. Beelink is on the broken SHA.${NC}" >&2
                    echo "${RED}Manual intervention required: ssh $REMOTE_HOST; cd $REMOTE_PATH; git reset --hard $PRIOR_SHA${NC}" >&2
                    exit 4
                fi
                echo "${YELLOW}Rollback to $PRIOR_SHA applied. Service was NOT restarted.${NC}"
                exit 3
            fi
            echo "${GREEN}==> Smoke passed.${NC}"
        else
            echo "${YELLOW}==> Smoke skipped (--no-smoke).${NC}"
        fi
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Restart phase (unchanged semantics).
# ────────────────────────────────────────────────────────────────────
case "$RESTART_MODE" in
    none)
        if [[ "$ROLLBACK_MODE" != "true" ]]; then
            echo ""
            echo "${GREEN}Code synced. Trading service still running on old code.${NC}"
            echo "When ready to apply changes (outside market hours or per your judgment):"
            echo "  ${CYAN}./scripts/ops/deploy-from-mac.sh --tv-paper${NC}   # restart agent only"
            echo "  ${CYAN}./scripts/ops/deploy-from-mac.sh --restart${NC}    # full restart"
        fi
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
