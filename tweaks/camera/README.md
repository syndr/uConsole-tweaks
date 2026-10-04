# camera

A launcher for a full-featured camera app, for a Raspberry Pi CSI camera module
fitted to the uConsole.

## The problem

A CSI camera on a CM5 is a libcamera device, not a plain V4L2 webcam, so most
desktop camera apps either can't see it or can't drive it properly. GNOME
Snapshot works, but only saves 1920x1080 from a 4608x2592 sensor and exposes no
controls.

Raspberry Pi's own [Picamera2](https://github.com/raspberrypi/picamera2) ships a
much more capable Qt app, `apps/app_full.py`: full-resolution stills, sensor
mode and file type selection, exposure / gain / white balance, image tuning,
pan / zoom, and video recording. It isn't included in the `python3-picamera2`
package, and it needs one environment tweak to start on a Wayland session.

## What this ships

| Path | What |
| --- | --- |
| `/usr/local/bin/uconsole-camera` | Launcher script. |
| `/usr/local/share/applications/uconsole-camera.desktop` | "uConsole Camera" menu entry. |
| `/usr/local/share/uconsole-tweaks/camera/app_full.py` | Picamera2's app, unmodified, from tag `v0.3.37`. |

The launcher does two things before starting the app:

- **Pins `QT_QPA_PLATFORM`** to `wayland` (or `xcb` outside Wayland). The app's
  GL preview fails at startup with `EGL_BAD_ALLOC` when the variable holds a
  fallback list such as `wayland;xcb`, which many Wayland sessions export.
- **Changes into `~/Pictures/Camera`**, because the app saves into the current
  directory. Files are named after the app's `Name` field, or `test` when it is
  empty, so set a name to avoid overwriting the previous shot.

## Usage

```sh
uconsole-camera
```

or pick **uConsole Camera** from the application launcher.

The HDR option is greyed out unless OpenCV is installed:

```sh
sudo apt install python3-opencv
```

## Requirements

- `python3-picamera2`, `python3-pyqt5` and `python3-opengl` (declared as
  `Recommends`, so `apt` pulls them in by default).
- A camera that libcamera detects. Check with `rpicam-hello --list-cameras`.

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

`app_full.py` is copyright Raspberry Pi and distributed under the BSD 2-Clause
License; see [`LICENSE.picamera2`](LICENSE.picamera2).
