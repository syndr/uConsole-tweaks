# zmk-cursor-scroll

While `KEY_FRONT` (gamepad Select on the uConsole's ZMK keyboard) is held, the trackball drives the **scroll wheel** instead of the cursor. The pointer device is grabbed exclusively for the duration of the hold so the compositor sees scroll events only — no cursor drift.

## How it works

- Listens for `KEY_FRONT` (linux input code 140) on the **keyd virtual keyboard** (`vid:pid 0fac:0ade`). keyd holds an exclusive grab on the physical ZMK keyboard and re-emits non-remapped keys through its virtual device, which is why this daemon doesn't read the ZMK keyboard directly.
- On press: scans for the ZMK pointer interface (`vid:pid 1d50:615e` with `EV_REL` capability), grabs it exclusively, and starts re-emitting motion as `REL_WHEEL` / `REL_HWHEEL` on a uinput device named `zmk-cursor-scroll`.
- On release: ungrabs the pointer, motion goes back to driving the cursor normally.

The daemon recovers from USB re-enumeration of the ZMK device: any `OSError` from `grab()` or `read()` triggers a full rescan-and-reopen, so transient disconnects don't permanently break scrolling.

## Tuning

Edit the module-level constants at the top of `zmk-cursor-scroll`:

| Constant | Meaning |
| --- | --- |
| `PIXELS_PER_TICK_V` / `PIXELS_PER_TICK_H` | Pointer pixels per emitted wheel tick. Larger = slower scrolling. |
| `DIR_V` / `DIR_H` | `1` for natural direction (push down → scroll down), `-1` to invert. |
| `HOLD_KEY` | The keycode that activates scroll mode. Defaults to `ecodes.KEY_FRONT`. |
| `KEYD_VID` / `KEYD_PID` | keyd virtual keyboard vendor / product (`0x0FAC` / `0x0ADE`). |
| `ZMK_VID` / `ZMK_PID` | ZMK device vendor / product (`0x1D50` / `0x615E`). |

After editing, `sudo systemctl restart zmk-cursor-scroll`.

## Requirements

- **Hardware**: uConsole with the ZMK-based internal keyboard (`vid:pid 1d50:615e`).
- **Runtime**: `python3`, `python3-evdev`, `keyd` (configured to grab the ZMK keyboard and re-emit through its virtual keyboard `0fac:0ade`).

## Install / uninstall

```sh
./install.sh     # copies files to /usr/local/bin + /etc/systemd/system, enables service
./uninstall.sh   # disables service + removes files
```

## Debugging

```sh
sudo journalctl -u zmk-cursor-scroll -f
```

Look for `listening: kbd=... ptr=...` on start, and `reopened: ...` after any recovery cycle. If you see `pointer grab failed` without a following `reopened` line, the recovery path has regressed.
