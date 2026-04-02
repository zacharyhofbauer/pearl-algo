#!/usr/bin/env bash
# =============================================================================
# git_rollback_paths.sh
#
# Safe, path-scoped rollback helper for "we need to revert ASAP" situations.
#
# What it does (high-level):
#  1) Verifies repo is clean (no local changes)
#  2) Creates a backup branch at the current HEAD
#  3) Restores one or more paths to a target commit/tag (git checkout <target> -- <paths>)
#  4) Deletes any tracked files under those paths that do NOT exist in the target commit
#  5) Verifies the staged result matches the target commit exactly for the requested paths
#  6) Optionally runs a validation command (e.g., `npm run build`)
#  7) Optionally creates a single rollback commit
#
# This mirrors the proven manual workflow we used to recover the PearlAlgo Web App UI
# after a bad refactor (CSS/panel split) without force-push or history rewrites.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
  cat <<'EOF'
Usage:
  ./scripts/maintenance/git_rollback_paths.sh --target <commit-ish> --path <path> [--path <path> ...] [options]

Required:
  --target <commit-ish>     Commit hash/tag/branch to restore from (e.g. 0102c787, v1.2.3, baseline/webapp)
  --path <path>             A repo-relative path to restore (repeatable)

Safety options:
  --yes                     Actually apply changes (required). Without this, script prints plan and exits.
  --backup-branch <name>    Backup branch name to create at current HEAD (default: backup/pre-rollback-YYYYMMDD-HHMMSSZ)

Optional:
  --run <cmd>               Validation command to run after staging rollback (e.g. "cd apps/pearl-algo-app && npm run build")
  --commit                  Create a single commit after successful verify/run
  --message <msg>           Commit message (only used with --commit)

Examples:
  # Roll back the web app + API server to a known-good commit (no commit yet)
  ./scripts/maintenance/git_rollback_paths.sh \
    --target 0102c787 \
    --path apps/pearl-algo-app \
    --path scripts/pearlalgo_web_app \
    --run "cd apps/pearl-algo-app && npm run build" \
    --yes

  # Same, but commit the rollback
  ./scripts/maintenance/git_rollback_paths.sh \
    --target 0102c787 \
    --path apps/pearl-algo-app \
    --path scripts/pearlalgo_web_app \
    --run "cd apps/pearl-algo-app && npm run build" \
    --commit \
    --message "Rollback web app to pre-panel-split UI template" \
    --yes
EOF
}

TARGET=""
BACKUP_BRANCH=""
RUN_CMD=""
DO_COMMIT=false
COMMIT_MESSAGE=""
CONFIRMED=false
PATHS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --path)
      PATHS+=("${2:-}")
      shift 2
      ;;
    --backup-branch)
      BACKUP_BRANCH="${2:-}"
      shift 2
      ;;
    --run)
      RUN_CMD="${2:-}"
      shift 2
      ;;
    --commit)
      DO_COMMIT=true
      shift
      ;;
    --message)
      COMMIT_MESSAGE="${2:-}"
      shift 2
      ;;
    --yes)
      CONFIRMED=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo ""
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$TARGET" || ${#PATHS[@]} -eq 0 ]]; then
  echo -e "${RED}Missing required args: --target and at least one --path${NC}"
  echo ""
  usage
  exit 2
fi

cd "$PROJECT_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo -e "${RED}Not inside a git work tree: $PROJECT_ROOT${NC}"
  exit 2
fi

if ! git rev-parse --verify "${TARGET}^{commit}" >/dev/null 2>&1; then
  echo -e "${RED}Target does not resolve to a commit: ${TARGET}${NC}"
  exit 2
fi

if [[ -z "$BACKUP_BRANCH" ]]; then
  BACKUP_BRANCH="backup/pre-rollback-$(date -u +%Y%m%d-%H%M%SZ)"
fi

echo -e "${YELLOW}=== Safe Git Rollback (path-scoped) ===${NC}"
echo "Repo:   $PROJECT_ROOT"
echo "Target: $TARGET"
echo "Paths:"
for p in "${PATHS[@]}"; do
  echo "  - $p"
done
echo "Backup branch: $BACKUP_BRANCH"
if [[ -n "$RUN_CMD" ]]; then
  echo "Run after stage: $RUN_CMD"
fi
if [[ "$DO_COMMIT" == true ]]; then
  echo "Commit: yes"
  if [[ -n "$COMMIT_MESSAGE" ]]; then
    echo "Message: $COMMIT_MESSAGE"
  else
    echo "Message: (auto)"
  fi
else
  echo "Commit: no"
fi
echo ""

if [[ "$CONFIRMED" == false ]]; then
  echo -e "${YELLOW}Dry plan only (no changes made). Re-run with --yes to apply.${NC}"
  exit 0
fi

# Require a clean working tree to avoid accidental loss of local work.
if [[ -n "$(git status --porcelain)" ]]; then
  echo -e "${RED}Working tree is not clean. Commit/stash your changes first.${NC}"
  git status --porcelain
  exit 1
fi

# Backup branch (cheap safety net).
if git show-ref --verify --quiet "refs/heads/${BACKUP_BRANCH}"; then
  echo -e "${RED}Backup branch already exists: ${BACKUP_BRANCH}${NC}"
  exit 1
fi
git branch "$BACKUP_BRANCH" HEAD
echo -e "${GREEN}Created backup branch:${NC} $BACKUP_BRANCH"

# 1) Restore requested paths from target commit into index + working tree.
git checkout "$TARGET" -- "${PATHS[@]}"

# 2) Remove any files under those paths that did not exist in the target commit.
# After checkout, these show up as "added" when diffing the index against the target.
git diff --cached -z --name-only --diff-filter=A "$TARGET" -- "${PATHS[@]}" \
  | xargs -0 -r git rm -f --ignore-unmatch --

# 3) Verify staged state matches target for the requested paths exactly.
if [[ -n "$(git diff --cached --name-status "$TARGET" -- "${PATHS[@]}")" ]]; then
  echo -e "${RED}Rollback verification failed: staged state does not match target for requested paths.${NC}"
  echo "Diff (staged vs target):"
  git diff --cached --name-status "$TARGET" -- "${PATHS[@]}"
  echo ""
  echo "You can recover instantly by switching to the backup branch:"
  echo "  git switch \"$BACKUP_BRANCH\""
  exit 1
fi
echo -e "${GREEN}Verified:${NC} staged paths match $TARGET exactly"

# 4) Optional validation run (after staging, before commit).
if [[ -n "$RUN_CMD" ]]; then
  echo -e "${YELLOW}Running validation command...${NC}"
  bash -lc "$RUN_CMD"
  echo -e "${GREEN}Validation command succeeded.${NC}"
fi

# 5) Optional commit.
if [[ "$DO_COMMIT" == true ]]; then
  if [[ -z "$COMMIT_MESSAGE" ]]; then
    COMMIT_MESSAGE="Rollback paths to $TARGET"
  fi
  git commit -m "$COMMIT_MESSAGE"
  echo -e "${GREEN}Committed rollback.${NC}"
else
  echo -e "${YELLOW}Rollback staged but not committed.${NC}"
  echo "Review with: git diff --cached"
  echo "Commit with: git commit -m \"Rollback paths to $TARGET\""
fi

echo ""
echo -e "${GREEN}Done.${NC}"
