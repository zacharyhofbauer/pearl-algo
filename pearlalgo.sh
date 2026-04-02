#!/usr/bin/env bash
# Compatibility shim for the historical top-level launcher name.
# Keep this file so existing scripts, docs, and restart hooks continue to work
# while `pearl.sh` remains the canonical entrypoint.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/pearl.sh" "$@"
