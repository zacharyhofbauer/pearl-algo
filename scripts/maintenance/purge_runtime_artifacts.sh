#!/usr/bin/env bash
# =============================================================================
# purge_runtime_artifacts.sh
# Safe cleanup of runtime/build artifacts from the repository.
# Requires explicit --yes flag to execute deletions.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Allowlist of directories/patterns to purge (relative to PROJECT_ROOT)
PURGE_DIRS=(
    "data"
    "logs"
    "telemetry"
)

PURGE_PATTERNS=(
    "tmp_debug_*.png"
    "tmp_test_*.png"
    "__pycache__"
    "*.egg-info"
    ".pytest_cache"
    ".ruff_cache"
    ".mypy_cache"
    ".coverage"
    "htmlcov"
)

usage() {
    echo "Usage: $0 [--yes] [--dry-run]"
    echo ""
    echo "Options:"
    echo "  --yes      Execute deletions (required to make changes)"
    echo "  --dry-run  Show what would be deleted without making changes"
    echo ""
    echo "Without flags, shows usage and exits."
    exit 0
}

# Parse arguments
DRY_RUN=false
CONFIRMED=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)
            CONFIRMED=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

if [[ "$CONFIRMED" == false && "$DRY_RUN" == false ]]; then
    usage
fi

cd "$PROJECT_ROOT"

echo -e "${YELLOW}=== Runtime Artifact Purge ===${NC}"
echo "Project root: $PROJECT_ROOT"
echo ""

# Track what we find
FOUND_ITEMS=()

# Check directories
for dir in "${PURGE_DIRS[@]}"; do
    if [[ -d "$dir" ]]; then
        count=$(find "$dir" -type f 2>/dev/null | wc -l)
        if [[ $count -gt 0 ]]; then
            FOUND_ITEMS+=("$dir/ ($count files)")
        fi
    fi
done

# Check patterns at root level
for pattern in "tmp_debug_*.png" "tmp_test_*.png"; do
    matches=$(find . -maxdepth 1 -name "$pattern" 2>/dev/null | wc -l)
    if [[ $matches -gt 0 ]]; then
        FOUND_ITEMS+=("$pattern ($matches files)")
    fi
done

# Check __pycache__ directories anywhere
pycache_count=$(find . -type d -name '__pycache__' 2>/dev/null | wc -l)
if [[ $pycache_count -gt 0 ]]; then
    FOUND_ITEMS+=("__pycache__/ ($pycache_count directories)")
fi

# Check egg-info
egginfo_count=$(find . -type d -name '*.egg-info' 2>/dev/null | wc -l)
if [[ $egginfo_count -gt 0 ]]; then
    FOUND_ITEMS+=("*.egg-info ($egginfo_count directories)")
fi

# Check pytest/ruff/mypy caches
for cache in ".pytest_cache" ".ruff_cache" ".mypy_cache" "htmlcov"; do
    if [[ -d "$cache" ]]; then
        FOUND_ITEMS+=("$cache/")
    fi
done

# Check .coverage file
if [[ -f ".coverage" ]]; then
    FOUND_ITEMS+=(".coverage")
fi

if [[ ${#FOUND_ITEMS[@]} -eq 0 ]]; then
    echo -e "${GREEN}No runtime artifacts found. Repository is clean.${NC}"
    exit 0
fi

echo "Found artifacts to purge:"
for item in "${FOUND_ITEMS[@]}"; do
    echo "  - $item"
done
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}[DRY-RUN] No changes made.${NC}"
    exit 0
fi

if [[ "$CONFIRMED" == true ]]; then
    echo -e "${YELLOW}Purging...${NC}"
    
    # Purge directory contents (keep the directories themselves for gitkeep)
    for dir in "${PURGE_DIRS[@]}"; do
        if [[ -d "$dir" ]]; then
            rm -rf "${dir:?}"/*
            echo "  Cleared $dir/"
        fi
    done
    
    # Purge root-level temp images
    find . -maxdepth 1 -name 'tmp_debug_*.png' -delete 2>/dev/null || true
    find . -maxdepth 1 -name 'tmp_test_*.png' -delete 2>/dev/null || true
    echo "  Removed tmp_*.png files"
    
    # Purge __pycache__ directories
    find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
    echo "  Removed __pycache__ directories"
    
    # Purge egg-info
    find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
    echo "  Removed *.egg-info directories"
    
    # Purge test/lint caches
    for cache in ".pytest_cache" ".ruff_cache" ".mypy_cache" "htmlcov"; do
        if [[ -d "$cache" ]]; then
            rm -rf "$cache"
            echo "  Removed $cache/"
        fi
    done
    
    # Purge .coverage
    if [[ -f ".coverage" ]]; then
        rm -f ".coverage"
        echo "  Removed .coverage"
    fi
    
    echo ""
    echo -e "${GREEN}Purge complete.${NC}"
fi


