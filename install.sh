#!/usr/bin/env bash
# Top-level installer: run install.sh in each tweaks/<name>/ subdirectory,
# or only the ones named on the command line.
#
# Examples:
#   ./install.sh                      # install all tweaks
#   ./install.sh zmk-cursor-scroll    # install only the named tweak(s)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TWEAKS_DIR="$HERE/tweaks"

if [ "$#" -gt 0 ]; then
  selected=("$@")
else
  selected=()
  for d in "$TWEAKS_DIR"/*/; do
    [ -d "$d" ] || continue
    selected+=("$(basename "$d")")
  done
fi

rc=0
for name in "${selected[@]}"; do
  script="$TWEAKS_DIR/$name/install.sh"
  if [ ! -x "$script" ]; then
    echo "skip $name: no executable install.sh at $script" >&2
    rc=1
    continue
  fi
  echo "==> installing $name"
  "$script" || { echo "!! $name install failed" >&2; rc=1; }
done

exit $rc
