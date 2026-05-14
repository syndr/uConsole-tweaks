# zmk-cursor-scroll

While gamepad Select is held on the uConsole's ZMK keyboard, the trackball drives the **scroll wheel** instead of the cursor. The pointer device is grabbed exclusively for the duration of the hold so the compositor sees scroll events only — no cursor drift.

## How it works

- Listens for `KEY_F24` (linux input code 194) on the **keyd virtual keyboard** (`vid:pid 0fac:0ade`). keyd holds an exclusive grab on the physical ZMK keyboard; the [`keyd-uconsole`](../keyd-uconsole) config rebinds Select via `timeout(front, 200, f24)` so that a *tap* of Select still emits `KEY_FRONT` for apps and games that expect it, but *holding* Select past 200 ms emits `KEY_F24` instead. `KEY_F24` is unmapped in essentially all userspace — so apps don't react to it, which avoids the "Select-press snaps terminals to bottom of scrollback" problem you'd see if the daemon latched directly on `KEY_FRONT`. Cost: ~200 ms latency between pressing Select and scroll mode engaging.
- On press: scans for the ZMK pointer interface (`vid:pid 1d50:615e` with `EV_REL` capability), grabs it exclusively, and starts re-emitting motion on a uinput device named `zmk-cursor-scroll`. Each pointer batch produces both **hi-res** scroll events (`REL_WHEEL_HI_RES` / `REL_HWHEEL_HI_RES`, 120 units per legacy notch) and the **legacy** notch events (`REL_WHEEL` / `REL_HWHEEL`) in the same `SYN_REPORT` frame. Modern compositors / toolkits (Hyprland's libinput, GTK, Chromium, Firefox) consume the hi-res stream for sub-line smooth scroll; legacy clients fall back to the notch events.
- On release: ungrabs the pointer, motion goes back to driving the cursor normally.

The daemon recovers from USB re-enumeration of the ZMK device: any `OSError` from `grab()` or `read()` triggers a full rescan-and-reopen, so transient disconnects don't permanently break scrolling.

## Tuning

Edit the module-level constants at the top of `zmk-cursor-scroll`:

| Constant | Meaning |
| --- | --- |
| `PIXELS_PER_TICK_V` / `PIXELS_PER_TICK_H` | Pointer pixels per emitted **legacy notch**. Hi-res events fire continuously in between (one hi-res unit every `PIXELS_PER_TICK / HI_RES_PER_NOTCH` pixels of motion). Larger = slower scrolling on both axes. |
| `HI_RES_PER_NOTCH` | Kernel-fixed ratio of hi-res units per legacy notch (`120`). **Do not change** — modern compositors hard-code this value. |
| `DIR_V` / `DIR_H` | `1` for natural direction (push down → scroll down), `-1` to invert. |
| `HOLD_KEY` | The keycode that activates scroll mode. Defaults to `ecodes.KEY_F24` — emitted by [`keyd-uconsole`](../keyd-uconsole) when gamepad Select is held >200 ms. If you change this, you'll also need to adjust the keyd binding (or restore the previous `ecodes.KEY_FRONT` default and drop the `front =` line from the keyd config). |
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
