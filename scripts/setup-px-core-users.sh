#!/usr/bin/env bash
# setup-px-core-users.sh
# Run once with: sudo bash setup-px-core-users.sh
# Then log out and reconnect SSH as pearlalgo (or pearlxprs for the other project).
#
# What this does:
# 1. Backs up /home/pearlxprs to /tmp, then creates user pearlxprs (admin) and restores project there.
# 2. Renames user pearl -> pearlalgo and moves /home/pearl -> /home/pearlalgo.
# 3. Removes the old pearlxprs folder from pearlalgo's home (it now lives under /home/pearlxprs).

set -e
if [[ $(id -u) -ne 0 ]]; then
  echo "Run with sudo."
  exit 1
fi

PEARL_UID=$(id -u pearl 2>/dev/null) || { echo "User pearl not found."; exit 1; }
BACKUP="/tmp/pearlxprs-backup-$$"
ADMIN_GROUP="sudo"

# --- 1. Backup pearlxprs project and create user pearlxprs ---
echo "Backing up pearlxprs project to $BACKUP ..."
cp -a /home/pearlxprs "$BACKUP"

echo "Creating admin user pearlxprs ..."
useradd -m -s /bin/bash -G "$ADMIN_GROUP" pearlxprs
cp -a "$BACKUP"/. /home/pearlxprs/
chown -R pearlxprs:pearlxprs /home/pearlxprs
rm -rf "$BACKUP"

# --- 2. Rename pearl -> pearlalgo and move home ---
echo "Renaming user pearl to pearlalgo and moving home ..."
usermod -l pearlalgo pearl
groupmod -n pearlalgo pearl
usermod -d /home/pearlalgo -m pearlalgo

# --- 3. Remove old pearlxprs dir from pearlalgo home (now duplicated under /home/pearlxprs) ---
echo "Removing old pearlxprs folder from pearlalgo home ..."
rm -rf /home/pearlalgo/pearlxprs

echo "Done. Set password for pearlxprs: sudo passwd pearlxprs"
echo "Reconnect SSH as pearlalgo or pearlxprs (see .vscode/ssh-px-core.config)."
