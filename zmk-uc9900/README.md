# zmk-uc9900

[ZMK](https://zmk.dev) firmware for the uConsole Trackpad Keyboard ("uc9900" / `bb9900`) made by [lululvlv](https://forum.clockworkpi.com/u/lululvlv) — the keyboard the rest of this repo's tweaks assume. Built locally in a container and flashed over the keyboard's UF2 bootloader. Nothing here is part of the `.deb`.

## What's here

| Path | What it is |
| --- | --- |
| `stock/` | The vendor's firmware config for the **v2** keyboard, unmodified: [Bill-lulu/uc9900](https://github.com/Bill-lulu/uc9900) branch `V2.0` at `9e0de2d`. The only change is `config/west.yml`, which pins the vendor's ZMK fork (`ZitaoTech/zmk`, branch `bbkeyboard_tp`) to the commit it pointed at. This builds the recovery image. |
| `config/` | Our firmware. For now this is the vendor config on the same ZMK fork with three keymap changes, listed at the top of `config/bb9900.keymap`: Select sends gamepad Select again instead of Caps Lock (so a tap is Select and a hold scrolls through `zmk-cursor-scroll`), Start is Super when held, and Fn+Start sends Pause. Caps Lock stays on Fn+Tab, including its scroll mode. Verified on the v2 keyboard on 2026-10-11. |
| `build.sh` | Builds a firmware image with `podman` (or `docker`) in `zmkfirmware/zmk-build-arm:3.5`. |
| `flash.sh` | Backs up or flashes the keyboard through its bootloader, hands-off. |
| `50-uf2-bootloader.rules` | polkit rule so `flash.sh` can mount the bootloader drive from an SSH session. See "Setup". |
| `LICENSE.vendor` | MIT license of the vendor config (© 2024 Zitao). |

Build outputs (`out/`), the cached west workspace (`.build/`) and backups (`backup/`) are not tracked.

## Build

```sh
make zmk-uc9900-stock        # -> zmk-uc9900/out/bb9900-stock-v2.uf2
make zmk-uc9900              # -> zmk-uc9900/out/bb9900-uconsole.uf2
```

The first build downloads the container image plus ZMK and Zephyr (a couple of GB) into `.build/`; later builds reuse them. `PRISTINE=1 ./build.sh stock` forces a clean rebuild of the firmware.

## Setup (once)

```sh
make zmk-uc9900-setup
```

This installs `50-uf2-bootloader.rules` into `/etc/polkit-1/rules.d/` (asks for your sudo password, so run it in a real terminal). udisks lets a user mount a removable drive without a password only from the local desktop session; from SSH, which is where you will be while the internal keyboard is in its bootloader, it asks for an admin password that a script cannot type. The rule allows members of `plugdev` to mount and unmount exactly one kind of drive, the `Adafruit nRF UF2` bootloader. Without it, `flash.sh` stops with an error and the keyboard stays in its bootloader until it times out (six minutes, see below) or is flashed from the desktop.

## Flash

**The internal keyboard and trackpad do not work while the keyboard is in its bootloader.** Before you start, make sure you can still reach the uConsole another way (SSH, a Bluetooth or USB keyboard).

```sh
make zmk-uc9900-backup RESTORE=1                              # save what is on the keyboard now, then write it back
make zmk-uc9900-flash UF2=zmk-uc9900/out/bb9900-uconsole.uf2  # write an image
```

Run the command first (from SSH, or from a terminal on the uConsole if you have another keyboard), then press **Fn + `\`** on the keyboard. The bootloader shows up as a USB drive (labelled `ADM840BOOT` or `NICENANO`); the script waits for it, does its work and reports the result. After a flash the keyboard reboots into the new firmware on its own. `RESTORE=1` makes the backup write the saved image straight back, which leaves the bootloader at once without changing what is on the keyboard; without it the keyboard stays in the bootloader until it is flashed or until the bootloader's six-minute timeout returns it to the firmware.

Take a backup before flashing anything, and keep a copy off the device.

## Recovery

- If a flash is rejected, the keyboard stays in the bootloader: run `flash.sh flash` again with a known-good image (your backup's `CURRENT.UF2`, or the stock build). You have six minutes before the bootloader gives up and boots whatever is in flash.
- **The bootloader leaves on its own after six minutes** if nothing is flashed (observed on 2026-10-11: entered 14:20:35, keyboard back at 14:26:35 with no writes; it is `DFU_TIMEOUT_INTERVAL = 360000` ms in the bootloader's DFU library). So an accidental Fn + `\` heals itself, and there is no need to power-cycle to get out. Start `flash.sh` before pressing the chord so the work is done inside that window.
- If a firmware boots but misbehaves, Fn + `\` still enters the bootloader as long as the key matrix and that binding are intact. Never remove `&bootloader` from the keymap.
- If the drive reappears a few seconds after a flash, that is a stuck unmount on the uConsole side, not a bad flash (reported by the [jhob101 firmware](https://github.com/jhob101/uconsole-bb9900-keyboard)): reboot the uConsole and flash again.
- If a firmware does not boot at all, the key combo is gone and recovery needs a hardware way into the bootloader. **Not established yet.** The bootloader is the [Adafruit nRF52 bootloader](https://github.com/adafruit/Adafruit_nRF52_Bootloader) 0.10.0 built for the Atelier-du-Maker board (`Board-ID: ADM_B_NRF52840_1`, no SoftDevice, built 2026-02-03, read from `INFO_UF2.TXT`). That build has two hardware ways in: hold its DFU input **P0.11** low (it is pulled up) while power is applied, or a double reset on the chip's reset pin within 500 ms. P0.11 is not used by the key matrix. Whether the keyboard PCB exposes either pin is unknown.

### Bootloader facts

- The drive is labelled `ADM840BOOT`. `CURRENT.UF2` is the whole application area (`0x1000`–`0xEA000`, 1.9 MB as UF2) tagged with the board-specific family ID `0x239A009F` (USB VID `239A` and PID `009F` of the bootloader). The bootloader also accepts the generic nRF52840 family ID `0xADA52840`, which is what ZMK builds carry, so our images flash without re-tagging.
- The factory firmware is ZMK on `Zephyr OS v3.5.0` build `339570e2393b`, the same Zephyr commit our stock build uses. Only ~17% of the bytes match because the toolchain and link differ; the symbol set is identical.
- The bootloader starts whatever is in flash as long as it was written through the bootloader, so a firmware that crashes at boot stays crashed. That is why the recovery gate above exists.
