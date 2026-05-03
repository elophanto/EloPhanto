#!/usr/bin/env bash
# install.sh — bootstrap the relay on a fresh Ubuntu/Debian box.
# Idempotent: safe to re-run.
set -euo pipefail

BIN_SRC="${1:-/tmp/elophanto-p2pd}"
BIN_DST=/usr/local/bin/elophanto-p2pd
SVC_SRC="${2:-/tmp/elophanto-relay.service}"
SVC_DST=/etc/systemd/system/elophanto-relay.service
DATA_DIR=/var/lib/elophanto-relay

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (try: sudo bash $0)" >&2
  exit 1
fi

# 1. Dedicated unprivileged user. -r = system user, no home, no shell.
if ! id elophanto >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin elophanto
  echo "[install] created user 'elophanto'"
fi

# 2. Data dir for the persistent identity key. 0700 keeps the key
# unreadable to anyone but the service user.
install -d -o elophanto -g elophanto -m 0700 "$DATA_DIR"

# 3. Drop the binary in place + make executable.
install -m 0755 "$BIN_SRC" "$BIN_DST"
echo "[install] binary at $BIN_DST"

# 4. Drop the systemd unit + reload.
install -m 0644 "$SVC_SRC" "$SVC_DST"
systemctl daemon-reload

# 5. Enable + start.
systemctl enable elophanto-relay >/dev/null
systemctl restart elophanto-relay
sleep 2

# 6. Show status — operator copy-pastes the multiaddr from the log.
systemctl --no-pager --lines=30 status elophanto-relay || true
echo
echo "[install] done. Useful commands:"
echo "  journalctl -u elophanto-relay -f         # tail logs"
echo "  systemctl restart elophanto-relay        # restart"
echo "  cat $DATA_DIR/identity.key | xxd | head  # peek the key (32 bytes)"
echo
echo "[install] grab the multiaddr now:"
journalctl -u elophanto-relay --no-pager --lines=50 | grep -E "PeerID=|listening|/p2p/" | tail -10
