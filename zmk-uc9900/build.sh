#!/usr/bin/env bash
# Build ZMK firmware for the uc9900 keyboard inside the zmk-build-arm container.
#
#   build.sh stock     vendor firmware, unmodified (the recovery image)
#   build.sh custom    our firmware, from config/
#
# The west workspace (ZMK, Zephyr, modules — a couple of GB) is cached under
# .build/<target>/ so only the first build is slow. Output lands in out/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Both the vendor fork and ZMK v0.3.0 are on Zephyr 3.5.
IMAGE="${ZMK_BUILD_IMAGE:-docker.io/zmkfirmware/zmk-build-arm:3.5}"
ENGINE="${CONTAINER_ENGINE:-$(command -v podman || command -v docker || true)}"
BOARD=bb9900

usage() {
    echo "usage: $0 stock|custom" >&2
    exit 2
}

case "${1:-}" in
    stock) src="$HERE/stock/config"; out="bb9900-stock-v2.uf2" ;;
    custom) src="$HERE/config"; out="bb9900-uconsole.uf2" ;;
    *) usage ;;
esac
target="$1"

if [ -z "$ENGINE" ]; then
    echo "error: need podman or docker" >&2
    exit 1
fi

ws="$HERE/.build/$target"
mkdir -p "$ws" "$HERE/out"

# west wants the manifest directory inside the workspace, so refresh a copy of
# the tracked config on every build.
rm -rf "$ws/config"
cp -a "$src" "$ws/config"

# PRISTINE=1 forces a clean rebuild of the firmware (not of the workspace).
"$ENGINE" run --rm -e PRISTINE="${PRISTINE:-}" -v "$ws:/workspace" -w /workspace "$IMAGE" bash -euc '
    [ -d .west ] || west init -l config
    west update --narrow --fetch-opt=--depth=1
    west zephyr-export
    west build -s zmk/app -d build -b '"$BOARD"' ${PRISTINE:+-p} -- -DZMK_CONFIG=/workspace/config
'

cp "$ws/build/zephyr/zmk.uf2" "$HERE/out/$out"
echo "built: $HERE/out/$out"
