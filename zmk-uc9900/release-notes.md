Firmware @VERSION@ for the uConsole Trackpad Keyboard (lululvlv's uc9900, **v2**). Built on upstream ZMK v0.3.0. What it does, key by key: [`zmk-uc9900/README.md`](https://github.com/syndr/uConsole-tweaks/blob/main/zmk-uc9900/README.md#keymap).

| File | What it is |
| --- | --- |
| `bb9900-uconsole.uf2` | The firmware. |
| `bb9900-stock-v2.uf2` | The vendor's firmware, rebuilt unchanged, to go back to stock. |
| `SHA256SUMS` | Checksums of the two files. |

## Flashing

Flash at your own risk; a firmware that fails to boot has no documented hardware recovery on this keyboard. The keyboard cannot type while it is in its bootloader, so have SSH or another keyboard ready.

1. Hold Fn and press `\` (on this firmware, Left Alt + Right Alt + Start also works). A USB drive called `ADM840BOOT` appears. The first time, copy its `CURRENT.UF2` somewhere safe: that is your current firmware.
2. Copy the `.uf2` onto that drive. The keyboard restarts on the new firmware by itself.
3. If nothing is copied, the bootloader returns to the previous firmware after six minutes.

From the uConsole with this repo checked out, `make zmk-uc9900-flash UF2=<file>` does the same hands-off. Trouble? See [Recovery](https://github.com/syndr/uConsole-tweaks/blob/main/zmk-uc9900/README.md#recovery).
