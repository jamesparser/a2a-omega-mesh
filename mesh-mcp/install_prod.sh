#!/bin/bash
# Install script for the production mesh board (revP) on Omega. Idempotent.
set -euo pipefail
SRC=/opt/mesh-board-prod-20261031
BIND_DIR=/etc/mesh-board-prod-20261031
BIND_FILE=$BIND_DIR/bind-tailnet.txt
TSIP=$(tailscale ip -4 2>/dev/null | head -1)
[ -n "$TSIP" ] || { echo "no tailnet ip; refusing to write bind file"; exit 1; }

mkdir -p "$BIND_DIR"
chmod 0755 "$BIND_DIR"
printf '%s\n' "$TSIP" > "$BIND_FILE.tmp.$$"
mv "$BIND_FILE.tmp.$$" "$BIND_FILE"
chmod 0644 "$BIND_FILE"
echo "bind file -> $TSIP"

cp /opt/mesh-board-v2-20261030/mesh-board-prod-20261031.service /etc/systemd/system/ 2>/dev/null || true
if [ ! -f /etc/systemd/system/mesh-board-prod-20261031.service ]; then
  echo "unit file missing in $SRC; aborting"; exit 1
fi
systemctl daemon-reload
systemctl enable mesh-board-prod-20261031.service
systemctl restart mesh-board-prod-20261031.service
sleep 2
systemctl is-active mesh-board-prod-20261031.service
ss -tlnp | grep -E '18792'
