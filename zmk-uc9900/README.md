# zmk-uc9900

[ZMK](https://zmk.dev) firmware for the uConsole Trackpad Keyboard ("uc9900" / `bb9900`) made by [lululvlv](https://forum.clockworkpi.com/u/lululvlv) — the keyboard the rest of this repo's tweaks assume. Built locally in a container and flashed over the keyboard's UF2 bootloader. Nothing here is part of the `.deb`.

## What's here

| Path | What it is |
| --- | --- |
| `stock/` | The vendor's firmware config for the **v2** keyboard, unmodified: [Bill-lulu/uc9900](https://github.com/Bill-lulu/uc9900) branch `V2.0` at `9e0de2d`. The only change is `config/west.yml`, which pins the vendor's ZMK fork (`ZitaoTech/zmk`, branch `bbkeyboard_tp`) to the commit it pointed at. This builds the recovery image. |
| `config/` | Our firmware. For now this is the vendor config on the same ZMK fork with three keymap changes, listed at the top of `config/bb9900.keymap`: Select sends gamepad Select again instead of Caps Lock, Start is Super when held, and Fn+Start sends Pause. |
| `build.sh` | Builds a firmware image with `podman` (or `docker`) in `zmkfirmware/zmk-build-arm:3.5`. |
| `flash.sh` | Backs up or flashes the keyboard through its bootloader, hands-off. |
| `LICENSE.vendor` | MIT license of the vendor config (© 2024 Zitao). |

Build outputs (`out/`), the cached west workspace (`.build/`) and backups (`backup/`) are not tracked.

## Build

```sh
make zmk-uc9900-stock        # -> zmk-uc9900/out/bb9900-stock-v2.uf2
make zmk-uc9900              # -> zmk-uc9900/out/bb9900-uconsole.uf2
```

The first build downloads the container image plus ZMK and Zephyr (a couple of GB) into `.build/`; later builds reuse them. `PRISTINE=1 ./build.sh stock` forces a clean rebuild of the firmware.

## Flash

**The internal keyboard and trackpad do not work while the keyboard is in its bootloader.** Before you start, make sure you can still reach the uConsole another way (SSH, a Bluetooth or USB keyboard).

```sh
make zmk-uc9900-backup RESTORE=1                              # save what is on the keyboard now, then write it back
make zmk-uc9900-flash UF2=zmk-uc9900/out/bb9900-uconsole.uf2  # write an image
```

Run the command first, then press **Fn + `\`** on the keyboard. The bootloader shows up as a USB drive (labelled `ADM840BOOT` or `NICENANO`); the script waits for it, does its work and reports the result. After a flash the keyboard reboots into the new firmware on its own. `RESTORE=1` makes the backup write the saved image straight back, which leaves the bootloader without changing what is on the keyboard; without it the keyboard stays in the bootloader until it is power-cycled or flashed.

Take a backup before flashing anything, and keep a copy off the device.

## Recovery

- If a flash is rejected, the keyboard stays in the bootloader: run `flash.sh flash` again with a known-good image (your backup's `CURRENT.UF2`, or the stock build).
- If a firmware boots but misbehaves, Fn + `\` still enters the bootloader as long as the key matrix and that binding are intact. Never remove `&bootloader` from the keymap.
- If the drive reappears a few seconds after a flash, that is a stuck unmount on the uConsole side, not a bad flash (reported by the [jhob101 firmware](https://github.com/jhob101/uconsole-bb9900-keyboard)): reboot the uConsole and flash again.
- If a firmware does not boot at all, the key combo is gone and recovery needs a hardware way into the bootloader. **Not established yet.** The bootloader appears to be the Atelier-du-Maker nRF52840 build, which enters UF2 mode when its DFU input (P0.11) is held low at power-on; whether the keyboard PCB exposes that pin is unknown.
