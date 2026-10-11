#!/usr/bin/env bash
# Back up or flash the uc9900 keyboard through its UF2 bootloader.
#
#   flash.sh backup              save CURRENT.UF2 + INFO_UF2.TXT to backup/<timestamp>/
#   flash.sh backup --restore    same, then write that image straight back (leaves the bootloader)
#   flash.sh flash <file.uf2>    write a firmware image
#
# Start this FIRST, then press Fn + \ on the keyboard to enter the bootloader.
# The internal keyboard and trackpad are dead while the bootloader is active,
# so the script runs hands-off once the bootloader drive appears. Have SSH or
# another keyboard ready in case something goes wrong.
set -euo pipefail
# Without this, a failing command inside $(...) does not stop the script.
shopt -s inherit_errexit

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The vendor README says the drive is called NICENANO; the jhob101 fork reports
# ADM840BOOT on a V2.1 keyboard. Accept either, or whatever UF2_LABEL says.
LABELS="${UF2_LABEL:-ADM840BOOT NICENANO}"
DEV=""
TIMEOUT="${TIMEOUT:-120}"
KBD_ID='Vendor=1d50 Product=615e'

usage() {
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
}

find_drive() {
    local l
    for l in $LABELS; do
        if [ -e "/dev/disk/by-label/$l" ]; then
            DEV="/dev/disk/by-label/$l"
            return 0
        fi
    done
    return 1
}

wait_for_drive() {
    echo "waiting up to ${TIMEOUT}s for the bootloader drive ($LABELS) — press Fn + \\ on the keyboard now"
    local i
    for ((i = 0; i < TIMEOUT * 2; i++)); do
        if find_drive; then
            echo "found $DEV"
            return 0
        fi
        sleep 0.5
    done
    echo "error: no bootloader drive appeared; the keyboard never entered the bootloader" >&2
    exit 1
}

# Prints the mount point. udisks mounts the drive without asking only from the
# local desktop session; over SSH it wants an admin password, which the polkit
# rule installed by `make zmk-uc9900-setup` makes unnecessary for this drive.
mount_drive() {
    local mp
    mp="$(findmnt -n -o TARGET "$DEV" 2>/dev/null || true)"
    if [ -z "$mp" ]; then
        if ! udisksctl mount -b "$DEV" --no-user-interaction >/dev/null; then
            cat >&2 <<EOF
error: could not mount $DEV (see udisks message above).
  From SSH or a non-interactive shell, udisks needs authorization: run
  'make zmk-uc9900-setup' once (installs a polkit rule, asks for sudo), or run
  this from a terminal on the uConsole's desktop. The keyboard stays in its
  bootloader until an image is written, or returns to its firmware on its own
  about six minutes after entering the bootloader.
EOF
            exit 1
        fi
        mp="$(findmnt -n -o TARGET "$DEV")"
    fi
    if [ -z "$mp" ]; then
        echo "error: $DEV mounted but no mount point found" >&2
        exit 1
    fi
    echo "$mp"
}

is_uf2() {
    # UF2 blocks start with the magic "UF2\n".
    [ -s "$1" ] && [ "$(head -c 4 "$1")" = "UF2" ]
}

# write_image <file.uf2> <mountpoint>
write_image() {
    local i
    echo "writing $1"
    # The bootloader resets as soon as the last block lands, so the copy or
    # the sync can report an I/O error on a successful flash.
    cp "$1" "$2/" 2>/dev/null || true
    sync 2>/dev/null || true
    echo "waiting for the keyboard to come back"
    for ((i = 0; i < 120; i++)); do
        if ! find_drive && grep -q "$KBD_ID" /proc/bus/input/devices; then
            echo "keyboard is back: flash succeeded"
            return 0
        fi
        sleep 0.5
    done
    if find_drive; then
        echo "error: still in the bootloader; the image was not accepted. Run this again with a known-good image." >&2
    else
        echo "error: the keyboard did not come back after flashing" >&2
    fi
    return 1
}

case "${1:-}" in
    backup)
        restore="${2:-}"
        [ -z "$restore" ] || [ "$restore" = "--restore" ] || usage
        wait_for_drive
        mp="$(mount_drive)"
        dest="$HERE/backup/$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$dest"
        for f in INFO_UF2.TXT CURRENT.UF2 INDEX.HTM; do
            if [ -e "$mp/$f" ]; then cp "$mp/$f" "$dest/"; fi
        done
        sync
        echo "saved to $dest:"
        ls -l "$dest"
        [ -e "$dest/INFO_UF2.TXT" ] && cat "$dest/INFO_UF2.TXT"
        if ! is_uf2 "$dest/CURRENT.UF2"; then
            echo "warning: this bootloader did not provide a usable CURRENT.UF2; no firmware backup was taken" >&2
            restore=""
        fi
        if [ -n "$restore" ]; then
            write_image "$dest/CURRENT.UF2" "$mp"
        else
            udisksctl unmount -b "$DEV" --no-user-interaction >/dev/null || true
            echo "the keyboard is still in its bootloader: flash an image to leave now, or wait; it returns to its firmware about six minutes after entering"
        fi
        ;;
    flash)
        img="${2:-}"
        [ -n "$img" ] || usage
        if ! is_uf2 "$img"; then
            echo "error: $img is not a UF2 image" >&2
            exit 1
        fi
        wait_for_drive
        mp="$(mount_drive)"
        write_image "$img" "$mp"
        ;;
    *) usage ;;
esac
