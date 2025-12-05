#!/bin/bash
#
# Cleanup Script for PearlAlgo v2
# Removes unnecessary, redundant, and outdated files
#
# WARNING: Review CLEANUP_REVIEW_REPORT.md before running
# This script is SAFE - it only removes files identified as unnecessary
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "PearlAlgo v2 Cleanup Script"
echo "=========================================="
echo ""
echo "This will remove unnecessary files identified in CLEANUP_REVIEW_REPORT.md"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleanup cancelled."
    exit 1
fi

echo ""
echo "Starting cleanup..."
echo ""

# Category 1: Redundant Documentation Files
echo "1. Removing redundant status/summary files..."
rm -f ARCHIVING_COMPLETE.md
rm -f CLEANUP_PLAN.md
rm -f FINAL_IMPLEMENTATION_STATUS.md
rm -f FINAL_SUMMARY.md
rm -f IMPLEMENTATION_PROGRESS.md
rm -f IMPLEMENTATION_SUMMARY.md
rm -f REFACTORING_SUMMARY.md
rm -f REFERENCE_FILES_UPDATED.md
rm -f TODAYS_UPGRADES_SUMMARY.md

# IBKR fix docs (now deprecated)
echo "2. Removing outdated IBKR connection fix docs..."
rm -f IBKR_CONNECTION_FIX.md
rm -f IBKR_CONNECTION_FIXES.md
rm -f IBKR_CONNECTION_FIXES_FINAL.md
rm -f IBKR_CONNECTION_STATUS.md
rm -f IBKR_FIXES_SUMMARY.md

# Duplicate start files
echo "3. Removing duplicate quick start files..."
rm -f START_HERE.md
rm -f QUICK_START_COMMANDS.txt

# Category 2: Cache and Build Artifacts
echo "4. Removing Python cache directories..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
rm -rf .pytest_cache/
rm -rf src/pearlalgo_dev_ai_agents.egg-info/

# Old state snapshots
echo "5. Removing old state cache snapshots..."
rm -f state_cache/*.pkl

# Test artifacts
echo "6. Removing test database files..."
rm -f data/test_ledger_quick.db

# Category 4: test_system.py (keep - different from scripts/test_new_system.py)
echo "7. Checking test_system.py..."
if [ -f "test_system.py" ]; then
    echo "   test_system.py (root) exists - keeping (tests LangGraph, different from scripts/test_new_system.py)"
fi

echo ""
echo "=========================================="
echo "Cleanup Complete!"
echo "=========================================="
echo ""
echo "Files removed. Review CLEANUP_REVIEW_REPORT.md for details."
echo ""
echo "Optional cleanup (not performed by this script):"
echo "- Logs directory (551MB): Already gitignored, consider archiving old logs"
echo "  Largest files:"
du -sh logs/*.log 2>/dev/null | sort -h | tail -3 || true
echo ""
echo "Next steps:"
echo "1. Review IBKR files (scripts/debug_ibkr.py, etc.) - manually archive if needed"
echo "2. Run: git status (to see changes)"
echo ""

