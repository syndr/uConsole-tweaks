# camera

`uconsole-camera`: a camera app for a Raspberry Pi CSI camera module, laid out
for the uConsole's 1280x720 screen.

## The problem

A CSI camera on a CM5 is a libcamera device, not a plain V4L2 webcam, so most
desktop camera apps either can't see it or can't drive it properly. GNOME
Snapshot works, but only saves 1920x1080 from a 4608x2592 sensor and exposes no
controls.

Raspberry Pi's [Picamera2](https://github.com/raspberrypi/picamera2) ships a
capable Qt app, `apps/app_full.py`, but it is built for a desktop monitor: two
fixed 400px side panels around an 800x600 preview, about 1700px wide, with the
shutter button cut off at the bottom-left on this screen; its "hide panel"
button also resizes the window, which a tiling compositor fights, and it
crashed after a few shots (see below).

## What this ships

| Path | What |
| --- | --- |
| `/usr/local/bin/uconsole-camera` | Launcher script. |
| `/usr/local/share/applications/uconsole-camera.desktop` | "uConsole Camera" menu entry. |
| `/usr/local/share/uconsole-tweaks/camera/uconsole-camera-app.py` | The app: a fork of Picamera2's `app_full.py` (tag `v0.3.37`). |

## The app

```
+----------------------------------------------+--------------------+
|                                              | Capture Exposure … |
|               live preview                   |                    |
|                                              |  settings drawer   |
|                                              |  (Tab / ⚙ hides)   |
+----------------------------------------------+--------------------+
| Photo Video [Shoot] AF  Zoom ----o-- 1.0x   status           [⚙] |
+-------------------------------------------------------------------+
```

- **Photo / Video** switch modes; **Shoot** takes a photo, or starts / stops
  recording in video mode.
- **Zoom** slider, mouse wheel over the preview, or `+` / `-` / `0` keys; drag
  the preview to pan.
- **AF** triggers autofocus. The *Focus* tab sets Continuous (default), Auto
  (trigger) or Manual with a lens-position slider.
- **Settings drawer** tabs: *Capture* (save folders, name, format, JPEG quality,
  resolution, sensor mode, live-preview mode, HDR), *Exposure* (AE/AWB, EV,
  manual shutter / gain, colour gains), *Focus*, *Tuning* (saturation, contrast,
  sharpness, brightness), *Zoom* (pan map), *Info* (live metadata), *Other*
  (every remaining camera control).
- **HDR** takes a bracket of exposures and writes `_base`, `_mean`, `_debevec`,
  `_robertson` and `_mertens` versions.

Keys: `Space` shoot / record, `Tab` toggle drawer, `F` autofocus, `+` `-` `0`
zoom, `F11` fullscreen, `Esc` / `Q` quit.

### Files and preferences

Photos are saved as `IMG_<timestamp>.<ext>` and videos as `VID_<timestamp>.<ext>`
(or the name you type in *Name*), never overwriting. The default folder is
`~/Pictures/Camera`; change it, and optionally a separate video folder, in the
*Capture* tab.

Setup choices are remembered in `~/.config/uconsole-camera/uconsole-camera.conf`:
folders, formats, JPEG quality, resolution, sensor mode, live-preview mode, video
preset / quality / frame rate, AF mode, drawer and fullscreen state, last tab.
Per-shot controls (exposure, gains, tuning sliders, zoom) start fresh each
launch. *Reset all preferences* clears the file.

The launcher writes the app's output to `~/.cache/uconsole-camera.log` (previous
run in `.log.1`), so a crash from the menu entry can still be diagnosed.

### Changes from upstream `app_full.py`

- Layout: full-window preview, one bottom bar, one collapsible drawer; the
  drawer is shown / hidden without resizing the window.
- Autofocus tab and AF button (upstream deliberately hides the `Af*` controls).
- Save location, timestamped filenames, JPEG quality, video resolution presets.
- Preferences persisted with `QSettings`.
- Keyboard shortcuts; wheel-zoom and drag-pan on the preview.
- Crash fix: upstream configured stills with `buffer_count=1`, so the Wayland GL
  preview widget did not hold a reference to the frame it showed, and a repaint
  after that request was recycled died with
  `AttributeError: 'NoneType' object has no attribute 'buffers'` (reproducibly
  on the third shot). The fork uses two buffers, drops the preview's frame before
  every reconfigure, and guards the repaint.
- Info-tab metadata formatting only runs while the tab is visible.

## Requirements

- `python3-picamera2`, `python3-pyqt5`, `python3-opengl`, and `python3-opencv`
  for HDR (all declared as `Recommends`, so `apt` pulls them in by default).
- A camera that libcamera detects. Check with `rpicam-hello --list-cameras`.
- The launcher pins `QT_QPA_PLATFORM` to `wayland` (or `xcb` outside Wayland):
  the GL preview fails at startup with `EGL_BAD_ALLOC` when the variable holds a
  fallback list such as `wayland;xcb`, which many Wayland sessions export.

### Enabling the camera on a CM5 uConsole

Tested with a Camera Module 3 (IMX708) on the HackerGadgets adapter board's CSI
connector. Add the sensor overlay to the `[pi5]` section of
`/boot/firmware/config.txt` and reboot:

```
dtoverlay=imx708,cam0
```

`cam0` matters: the uConsole display occupies the other MIPI port and its I2C
bus carries the PMIC, so the overlay's default port can't be used. Swap `imx708`
for the overlay matching your sensor (`imx219`, `ov5647`, `imx477`, ...).

If the kernel log shows `failed to read chip id`, check the ribbon cable first:
a bad or mismatched cable gives exactly that error while the overlay itself
loads fine.

## License

The app is derived from Picamera2's `apps/app_full.py`, copyright Raspberry Pi,
BSD 2-Clause License; see [`LICENSE.picamera2`](LICENSE.picamera2).
