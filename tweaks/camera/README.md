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
| Photo Video  AF  Zoom ---o-- 1.0x  status      [   Shoot   ]  [⚙] |
+-------------------------------------------------------------------+
```

- **Photo / Video** switch modes; **Shoot** takes a photo, or starts / stops
  recording in video mode. A **self-timer** (Off / 3 / 5 / 10 s, in the
  *Capture* tab) counts down on the button; pressing again cancels.
- **Zoom** slider, mouse wheel over the preview, or `+` / `-` / `0` keys; drag
  the preview to pan (a tap without dragging focuses instead).
- **AF** triggers autofocus. The *Focus* tab sets Continuous (default), Auto
  (trigger) or Manual with a lens-position slider. **Tap the preview** to focus
  on that spot: a box marks the region and the AF window follows it (in
  Continuous mode it keeps tracking there; in Auto/Manual it triggers one
  focus run). *Whole frame* in the Focus tab goes back to full-frame metering.
- **Settings drawer** tabs: *Capture* (save folders, name, format, JPEG quality,
  resolution presets with megapixels, sensor mode, live-preview mode, HDR; in
  video mode: quality, frame rate, presets up to 4K, and a note of the sensor's
  frame-rate ceiling for the chosen size), *Exposure* (AE/AWB, EV,
  manual shutter / gain, colour gains), *Focus*, *Tuning* (saturation, contrast,
  sharpness, brightness), *Zoom* (pan map), *Info* (live metadata), *More*
  (every remaining camera control).
- **HDR** takes a bracket of exposures and writes `_base`, `_mean`, `_debevec`,
  `_robertson` and `_mertens` versions.

Video is H.264 encoded in software on the Pi 5 (there is no hardware encoder).
With a Camera Module 3, 1080p records at a real 30 fps; 4K (3840x2160) needs the
sensor's full-resolution mode, which tops out at about 14 fps, and loads the
CPU heavily. The presets and the note under *Resolution* are computed from the
detected sensor's modes, so they adapt to other cameras.

Keys: `Space` shoot / record, `Tab` toggle drawer, `F` autofocus, `+` `-` `0`
zoom, `F11` fullscreen, `Esc` / `Q` quit.

### Files and preferences

Photos are saved as `IMG_<timestamp>.<ext>` and videos as `VID_<timestamp>.<ext>`
(or the name you type in *Name*), never overwriting. The default folder is
`~/Pictures/Camera`; change it, and optionally a separate video folder, in the
*Capture* tab.

Setup choices are remembered in `~/.config/uconsole-camera/uconsole-camera.conf`:
folders, formats, JPEG quality, self-timer, resolution, sensor mode, live-preview mode, video
preset / quality / frame rate, AF mode, drawer and fullscreen state, last tab.
Per-shot controls (exposure, gains, tuning sliders, zoom) start fresh each
launch. *Reset all preferences* clears the file.

The launcher writes the app's output to `~/.cache/uconsole-camera.log` (previous
run in `.log.1`), so a crash from the menu entry can still be diagnosed.

### Changes from upstream `app_full.py`

- Layout: full-window preview, one bottom bar, one collapsible drawer; the
  drawer is shown / hidden without resizing the window.
- Autofocus tab, AF button and tap-to-focus via `AfWindows` (upstream
  deliberately hides the `Af*` controls).
- Digital-zoom crop carried correctly across sensor modes: upstream kept the
  old crop size when the ScalerCrop frame changed, leaving a crop with a
  negative origin that libcamera silently clamped but that misplaced the pan
  map (and would have misplaced the AF window).
- Self-timer with countdown and cancel.
- Save location, timestamped filenames, JPEG quality, photo and video resolution
  presets (video no longer capped at 1080p, which was a Pi 4 hardware-encoder
  limit), frame-rate ceiling note.
- Preview (lores) stream clamped to the chosen photo size: upstream raised
  `lores stream dimensions may not exceed main stream` for small custom sizes.
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
- A camera that libcamera detects (any Raspberry Pi camera module or third-party
  CSI sensor with a Pi libcamera driver; not USB webcams). Check with
  `rpicam-hello --list-cameras`.
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
