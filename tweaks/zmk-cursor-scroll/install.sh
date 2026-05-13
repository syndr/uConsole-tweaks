#!/usr/bin/env bash
# Install the zmk-cursor-scroll daemon + systemd unit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SRC="$HERE/zmk-cursor-scroll"
UNIT_SRC="$HERE/zmk-cursor-scroll.service"
BIN_DST="/usr/local/bin/zmk-cursor-scroll"
UNIT_DST="/etc/systemd/system/zmk-cursor-scroll.service"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

if ! python3 -c "import evdev" >/dev/null 2>&1; then
  echo "[zmk-cursor-scroll] python3 evdev module not found." >&2
  echo "  Install it with: sudo apt install python3-evdev" >&2
  exit 1
fi

if ! systemctl list-unit-files keyd.service >/dev/null 2>&1; then
  echo "[zmk-cursor-scroll] WARNING: keyd.service is not installed." >&2
  echo "  This tweak listens on keyd's virtual keyboard for KEY_FRONT and" >&2
  echo "  will sit waiting for it. Install keyd before expecting scrolling." >&2
fi

echo "[zmk-cursor-scroll] installing daemon → $BIN_DST"
$SUDO install -m 0755 -o root -g root "$BIN_SRC" "$BIN_DST"

echo "[zmk-cursor-scroll] installing unit  → $UNIT_DST"
$SUDO install -m 0644 -o root -g root "$UNIT_SRC" "$UNIT_DST"

echo "[zmk-cursor-scroll] reloading systemd + enabling service"
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now zmk-cursor-scroll.service

$SUDO systemctl --no-pager --lines=0 status zmk-cursor-scroll.service || true
