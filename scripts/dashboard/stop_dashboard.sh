#!/bin/bash
# ============================================================================
# PEARL Dashboard Stop Script
# 
# Stops the API server and Next.js dashboard processes.
# ============================================================================

echo "Stopping PEARL Dashboard processes..."

# Kill API server
pkill -f "api_server.py" 2>/dev/null && echo "  Stopped API server" || echo "  API server not running"

# Kill Next.js dashboard
pkill -f "next-server" 2>/dev/null && echo "  Stopped Next.js dashboard" || true
pkill -f "next dev" 2>/dev/null || true

echo "Done."
