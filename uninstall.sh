#!/usr/bin/env bash
# Top-level uninstaller: run uninstall.sh in each tweaks/<name>/ subdirectory,
# or only the ones named on the command line.
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
  script="$TWEAKS_DIR/$name/uninstall.sh"
  if [ ! -x "$script" ]; then
    echo "skip $name: no executable uninstall.sh at $script" >&2
    rc=1
    continue
  fi
  echo "==> uninstalling $name"
  "$script" || { echo "!! $name uninstall failed" >&2; rc=1; }
done

exit $rc
