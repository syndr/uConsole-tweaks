#!/usr/bin/env bash
# Uninstall the zmk-cursor-scroll daemon + systemd unit.
set -euo pipefail

BIN_DST="/usr/local/bin/zmk-cursor-scroll"
UNIT_DST="/etc/systemd/system/zmk-cursor-scroll.service"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

if systemctl list-unit-files zmk-cursor-scroll.service >/dev/null 2>&1; then
  echo "[zmk-cursor-scroll] stopping + disabling service"
  $SUDO systemctl disable --now zmk-cursor-scroll.service || true
fi

[ -e "$UNIT_DST" ] && { echo "[zmk-cursor-scroll] removing $UNIT_DST"; $SUDO rm -f "$UNIT_DST"; }
[ -e "$BIN_DST" ]  && { echo "[zmk-cursor-scroll] removing $BIN_DST";  $SUDO rm -f "$BIN_DST"; }

$SUDO systemctl daemon-reload
echo "[zmk-cursor-scroll] uninstalled."
