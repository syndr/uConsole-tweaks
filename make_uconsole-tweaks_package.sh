#!/bin/bash
# Build uconsole-tweaks.deb from the contents of tweaks/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$SCRIPT_DIR/uconsole-tweaks"
VERSION="${ENV_VERSION:-0.5.0}"
DKMS_NAME="ocp8178-backlight"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/local/bin"
mkdir -p "$STAGE/etc/systemd/system"
mkdir -p "$STAGE/etc/keyd"
mkdir -p "$STAGE/usr/local/share/applications"
mkdir -p "$STAGE/usr/local/share/uconsole-tweaks/camera"
mkdir -p "$STAGE/usr/src/$DKMS_NAME-$VERSION"

# --- zmk-cursor-scroll --------------------------------------------------------

install -m 0755 "$SCRIPT_DIR/tweaks/zmk-cursor-scroll/zmk-cursor-scroll" \
    "$STAGE/usr/local/bin/zmk-cursor-scroll"

install -m 0644 "$SCRIPT_DIR/tweaks/zmk-cursor-scroll/zmk-cursor-scroll.service" \
    "$STAGE/etc/systemd/system/zmk-cursor-scroll.service"

# --- battery-gauge ------------------------------------------------------------

install -m 0755 "$SCRIPT_DIR/tweaks/battery-gauge/uconsole-battery" \
    "$STAGE/usr/local/bin/uconsole-battery"

install -m 0755 "$SCRIPT_DIR/tweaks/battery-gauge/uconsole-battery-calibrate" \
    "$STAGE/usr/local/bin/uconsole-battery-calibrate"

# Device-specific overrides live in /etc/uconsole-battery.conf or
# ~/.config/uconsole-battery.conf; ship only the documented example.
mkdir -p "$STAGE/usr/share/doc/uconsole-tweaks"
install -m 0644 "$SCRIPT_DIR/tweaks/battery-gauge/uconsole-battery.conf.example" \
    "$STAGE/usr/share/doc/uconsole-tweaks/uconsole-battery.conf.example"

# --- keyd-uconsole ------------------------------------------------------------

install -m 0644 "$SCRIPT_DIR/tweaks/keyd-uconsole/uconsole.conf" \
    "$STAGE/etc/keyd/uconsole.conf"

# --- camera -------------------------------------------------------------------

install -m 0755 "$SCRIPT_DIR/tweaks/camera/uconsole-camera" \
    "$STAGE/usr/local/bin/uconsole-camera"

install -m 0644 "$SCRIPT_DIR/tweaks/camera/uconsole-camera-app.py" \
    "$STAGE/usr/local/share/uconsole-tweaks/camera/uconsole-camera-app.py"

install -m 0644 "$SCRIPT_DIR/tweaks/camera/LICENSE.picamera2" \
    "$STAGE/usr/local/share/uconsole-tweaks/camera/LICENSE.picamera2"

install -m 0644 "$SCRIPT_DIR/tweaks/camera/uconsole-camera.desktop" \
    "$STAGE/usr/local/share/applications/uconsole-camera.desktop"

# --- ocp8178-backlight (DKMS) -------------------------------------------------

install -m 0644 "$SCRIPT_DIR/tweaks/ocp8178-backlight/ocp8178_bl.c" \
    "$STAGE/usr/src/$DKMS_NAME-$VERSION/ocp8178_bl.c"

install -m 0644 "$SCRIPT_DIR/tweaks/ocp8178-backlight/Makefile" \
    "$STAGE/usr/src/$DKMS_NAME-$VERSION/Makefile"

sed "s/@VERSION@/$VERSION/" "$SCRIPT_DIR/tweaks/ocp8178-backlight/dkms.conf" \
    > "$STAGE/usr/src/$DKMS_NAME-$VERSION/dkms.conf"
chmod 0644 "$STAGE/usr/src/$DKMS_NAME-$VERSION/dkms.conf"

# --- DEBIAN/conffiles ---------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/conffiles"
/etc/keyd/uconsole.conf
EOF

# --- DEBIAN/control -----------------------------------------------------------

cat << EOF > "$STAGE/DEBIAN/control"
Package: uconsole-tweaks
Version: $VERSION
Maintainer: syndr <syndr@ultroncore.net>
Architecture: all
Depends: python3, python3-evdev, keyd, dkms
Recommends: python3-picamera2, python3-pyqt5, python3-opengl, python3-opencv
Suggests: wl-clipboard, xclip
Description: Small standalone tweaks for the ClockworkPi uConsole.
 Ships:
   * zmk-cursor-scroll - hold the gamepad Select key to make the trackball
     drive the scroll wheel instead of the cursor.
   * battery-gauge - uconsole-battery, a battery percentage for waybar that
     shows the AXP223 fuel gauge while it is moving and falls back to a
     voltage-based estimate when the gauge sticks (classically pinned at
     100%). Includes uconsole-battery-calibrate to measure the pack's
     internal resistance for the estimator.
   * keyd-uconsole - keyd config scoping to the ZMK keyboard sub-device and
     mapping Tab (hold) -> Super. Also enables the keyd virtual keyboard that
     zmk-cursor-scroll listens on.
   * camera - uconsole-camera, a Picamera2 camera app for a CSI camera
     module, laid out for the uConsole's 1280x720 screen (forked from
     Picamera2's app_full.py).
   * ocp8178-backlight - DKMS build of the backlight driver exposing all 32
     levels of the OCP8178 instead of the stock driver's 10. Needs the
     running kernel's headers (linux-headers-<version>).
EOF

# --- DEBIAN/postinst ----------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/postinst"
#!/bin/bash
set -e

systemctl daemon-reload

if systemctl is-active --quiet keyd; then
    systemctl reload-or-restart keyd || true
fi

systemctl enable --now zmk-cursor-scroll.service

# ocp8178-backlight: register and build the DKMS module for the running kernel.
dkms add -m @DKMS_NAME@ -v @VERSION@ >/dev/null 2>&1 || true
if dkms install -m @DKMS_NAME@ -v @VERSION@ -k "$(uname -r)"; then
    echo "ocp8178-backlight: module built for $(uname -r)."
    echo "  Reboot to activate. Do not modprobe -r/modprobe it live: the panel driver keeps"
    echo "  its reference to the old backlight device and DPMS would leave the screen dark."
else
    echo "ocp8178-backlight: DKMS build failed (are linux-headers-$(uname -r) installed?)." >&2
    echo "  Re-run later with: sudo dkms install @DKMS_NAME@/@VERSION@" >&2
fi
EOF
sed -i "s/@DKMS_NAME@/$DKMS_NAME/g; s/@VERSION@/$VERSION/g" "$STAGE/DEBIAN/postinst"

# --- DEBIAN/prerm -------------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/prerm"
#!/bin/bash
set -e

if systemctl list-unit-files zmk-cursor-scroll.service >/dev/null 2>&1; then
    systemctl disable --now zmk-cursor-scroll.service || true
fi

# ocp8178-backlight: drop the DKMS module; the stock driver is used after the
# next reboot (or a modprobe -r / modprobe cycle).
if command -v dkms >/dev/null 2>&1; then
    dkms remove -m @DKMS_NAME@ -v @VERSION@ --all >/dev/null 2>&1 || true
fi
EOF
sed -i "s/@DKMS_NAME@/$DKMS_NAME/g; s/@VERSION@/$VERSION/g" "$STAGE/DEBIAN/prerm"

# --- DEBIAN/postrm ------------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/postrm"
#!/bin/bash
set -e

systemctl daemon-reload || true

if systemctl is-active --quiet keyd; then
    systemctl reload-or-restart keyd || true
fi
EOF

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$STAGE" "$SCRIPT_DIR/uconsole-tweaks.deb"

rm -rf "$STAGE"
