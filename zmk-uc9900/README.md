# zmk-uc9900

[ZMK](https://zmk.dev) firmware for the uConsole Trackpad Keyboard ("uc9900" / `bb9900`) made by [lululvlv](https://forum.clockworkpi.com/u/lululvlv) — the keyboard the rest of this repo's tweaks assume. Built locally in a container and flashed over the keyboard's UF2 bootloader. Nothing here is part of the `.deb`.

## What's here

| Path | What it is |
| --- | --- |
| `stock/` | The vendor's firmware config for the **v2** keyboard, unmodified: [Bill-lulu/uc9900](https://github.com/Bill-lulu/uc9900) branch `V2.0` at `9e0de2d`. The only change is `config/west.yml`, which pins the vendor's ZMK fork (`ZitaoTech/zmk`, branch `bbkeyboard_tp`) to the commit it pointed at. This builds the recovery image. |
| `config/` | Our firmware, on **upstream ZMK v0.3.0** (pinned in `config/west.yml`) instead of the vendor's 2023 fork. `config/boards/arm/bb9900/` is the board: the vendor's matrix, pins and flash layout, a small polled driver for the A320 trackpad sensor that feeds ZMK's pointing subsystem, the scroll-direction processor and toggle behavior, the Caps Lock scroll glue and the trackpad light. The keymap changes are listed at the top of `config/bb9900.keymap`; see [Keymap](#keymap). |
| `build.sh` | Builds a firmware image with `podman` (or `docker`) in `zmkfirmware/zmk-build-arm:3.5`. |
| `flash.sh` | Backs up or flashes the keyboard through its bootloader, hands-off. |
| `50-uf2-bootloader.rules` | polkit rule so `flash.sh` can mount the bootloader drive from an SSH session. See "Setup". |
| `LICENSE.vendor` | MIT license of the vendor config (© 2024 Zitao). |

Build outputs (`out/`), the cached west workspace (`.build/`) and backups (`backup/`) are not tracked.

## Keymap

Everything the vendor keymap does, with these changes:

| Keys | Does | Vendor firmware |
| --- | --- | --- |
| Select | tap = gamepad Select (`KEY_FRONT`); hold = the trackpad scrolls | Caps Lock |
| Fn + Tab (Caps Lock) | Caps Lock, and the trackpad scrolls while it is on | same, coarse and reversed |
| Fn + `/` | scroll switch: trackpad scrolls until pressed again | – |
| Fn + `'` | flip the scroll direction (natural / inverted); remembered | – |
| Y or B held + D-pad | moves the pointer; a tap still sends F21 / F23 | F21 / F23 only |
| Start | tap = Play, hold = Super | Play |
| Tab | tap = Tab, hold = Super | Tab (keyd did the hold on the host) |
| Speaker / Shift+Speaker / Fn+Speaker | Volume down / up / mute | Mute / nothing useful / volume |
| Fn + Right Alt, Fn + Right Ctrl | Alt, Ctrl | dead |
| Fn + Start | Pause | phantom mouse clicks |
| Right Fn + Esc | switch output between USB and the selected Bluetooth profile | clear all Bluetooth bonds |
| Right Fn + 1–4 | select Bluetooth profile 1–4 | same |
| Left Alt + Right Alt + Start | bootloader | – |
| Fn + `\` | bootloader | same |
| both Fn + Esc | clear Bluetooth bonds | right Fn + Esc |
| both Fn + R | restart the keyboard | right Fn, then left Fn |
| Fn + Tab | Caps Lock | same |

Switching the output to Bluetooth makes the keyboard drive the paired device instead of the uConsole, trackpad included, until it is switched back. Key positions are listed at the top of the keymap.

### Scrolling

Scrolling is done in the firmware, so the [`zmk-cursor-scroll`](../tweaks/zmk-cursor-scroll) daemon is not needed with this build (it stays idle if left running: the firmware never sends the F19 it listens for). All three ways in, hold Select, Caps Lock and the Fn+`/` switch, share one scroll layer, so they scroll the same way and at the same speed. The trackpad light goes out while scrolling. Scrolling is smooth: the firmware enables the HID resolution multiplier and Linux turns it into high-resolution wheel events, so Firefox and VS Code scroll too, which jhob101's coarse implementation could not do. The default direction is natural on both axes (the content follows the finger); Fn+`'` flips it and the choice is stored on the keyboard. Speed is set by `SCROLL_MUL`/`SCROLL_DIV` at the top of the keymap (3/8 ≈ the daemon's 64 pointer pixels per notch).

### Lights and host sleep

The trackpad light is on while the keyboard is in use. It goes out in scroll mode, after the keyboard has been idle for `CONFIG_ZMK_IDLE_TIMEOUT` (30 s; a key or a touch relights it), and while the host is asleep. The keyboard backlight (Fn+Space) keeps ZMK's own idle auto-off.

**Host sleep.** The [uConsole-sleep](https://github.com/syndr/uConsole-sleep) service tells the keyboard when the uConsole goes to sleep: it sets the Kana bit (bit 4) of the standard HID LED output report before the uConsole sleeps and clears it on wake. The firmware also treats a suspended USB link as sleep, but the service does not suspend the keyboard by default (that broke the keyboard on this host, see Recovery), so the LED bit is the cue in practice. Host-sleep mode means: a layer of `&none` goes on top so no key or pointer report (and no USB remote-wakeup request) is sent, the trackpad is no longer polled and drops into the sensor's own rest mode, and both lights are off and stay off even if keys are pressed. Everything returns to its previous state on wake; the backlight is driven directly for this, so its own on/off setting is untouched. Any host can use the same signal by writing the LED report (`CONFIG_UC9900_HOST_SLEEP_LED_BIT` picks the bit). Power to the trackpad sensor (P0.13, `ext_power`) is left on: what else it feeds is undocumented.

Not carried over from the vendor firmware: the layer-indicator LED on P0.03 is not driven.

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
- **If the keyboard vanishes after a reset** and `dmesg` shows `usb 1-1.1: device descriptor read/64, error -71` or `device not accepting address`, the uConsole's USB host port is stuck, not the keyboard (seen here after the Alt+Alt+Start chord; jhob101 saw the same log after a flash). The port shows `state=powered` under `/sys/bus/usb/devices/1-1/1-1:1.0/1-1-port1/` and gets no further connect events, so even the bootloader's six-minute exit goes unnoticed. **Reboot the uConsole.** Do not try to re-probe the hub (`unbind`/`bind` of `1-1` under `/sys/bus/usb/drivers/usb/`): the uConsole-sleep work tried it and every device on the hub then failed enumeration until a reboot, and the kernel's own port power cycle did not help either. The hub is a Genesys Logic 05e3:0608 behind the CM5's dwc2 controller.
- **Do not let the host runtime-suspend the keyboard** (`power/control` must stay `on`, the kernel default for it). On this host a USB selective suspend of the keyboard ended in `runtime_status=error` and a failed rebind (`can't set config #1, error -22`), leaving the keyboard dead until a reboot.
- If a firmware does not boot at all, the key combo is gone and recovery needs a hardware way into the bootloader. **Not established yet.** The bootloader is the [Adafruit nRF52 bootloader](https://github.com/adafruit/Adafruit_nRF52_Bootloader) 0.10.0 built for the Atelier-du-Maker board (`Board-ID: ADM_B_NRF52840_1`, no SoftDevice, built 2026-02-03, read from `INFO_UF2.TXT`). That build has two hardware ways in: hold its DFU input **P0.11** low (it is pulled up) while power is applied, or a double reset on the chip's reset pin within 500 ms. P0.11 is not used by the key matrix. Whether the keyboard PCB exposes either pin is unknown.

### Bootloader facts

- The drive is labelled `ADM840BOOT`. `CURRENT.UF2` is the whole application area (`0x1000`–`0xEA000`, 1.9 MB as UF2) tagged with the board-specific family ID `0x239A009F` (USB VID `239A` and PID `009F` of the bootloader). The bootloader also accepts the generic nRF52840 family ID `0xADA52840`, which is what ZMK builds carry, so our images flash without re-tagging.
- The factory firmware is ZMK on `Zephyr OS v3.5.0` build `339570e2393b`, the same Zephyr commit our stock build uses. Only ~17% of the bytes match because the toolchain and link differ; the symbol set is identical.
- The bootloader starts whatever is in flash as long as it was written through the bootloader, so a firmware that crashes at boot stays crashed. That is why the recovery gate above exists.
