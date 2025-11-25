#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="ibgateway.service"

echo "==> systemctl status ${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager || true

echo
echo "==> Recent logs (journalctl -u ${SERVICE_NAME} -n 50)"
journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
