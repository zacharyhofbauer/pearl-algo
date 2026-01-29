#!/bin/bash
# ============================================================================
# PEARL Live Main Chart Stop Script
# ============================================================================

echo "Stopping PEARL Live Main Chart..."

pkill -f "api_server.py" 2>/dev/null && echo "  Stopped API server" || echo "  API server not running"
pkill -f "next-server" 2>/dev/null && echo "  Stopped chart server" || true
pkill -f "next dev" 2>/dev/null || true

echo "Done."
