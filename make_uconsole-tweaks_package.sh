#!/bin/bash
# Build uconsole-tweaks.deb from the contents of tweaks/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$SCRIPT_DIR/uconsole-tweaks"
VERSION="${ENV_VERSION:-0.3.1}"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/local/bin"
mkdir -p "$STAGE/etc/systemd/system"
mkdir -p "$STAGE/etc/keyd"
mkdir -p "$STAGE/usr/local/share/applications"
mkdir -p "$STAGE/usr/local/share/uconsole-tweaks/camera"

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
Depends: python3, python3-evdev, keyd
Recommends: python3-picamera2, python3-pyqt5, python3-opengl, python3-opencv
Description: Small standalone tweaks for the ClockworkPi uConsole.
 Ships:
   * zmk-cursor-scroll - hold the gamepad Select key to make the trackball
     drive the scroll wheel instead of the cursor.
   * battery-gauge - uconsole-battery, a voltage-based state-of-charge
     estimator that works around the AXP223 PMIC's stuck fuel-gauge register
     (kernel capacity pinned at 100%). Includes uconsole-battery-calibrate to
     measure the pack's internal resistance for the estimator.
   * keyd-uconsole - keyd config scoping to the ZMK keyboard sub-device and
     mapping Tab (hold) -> Super. Also enables the keyd virtual keyboard that
     zmk-cursor-scroll listens on.
   * camera - uconsole-camera, a Picamera2 camera app for a CSI camera
     module, laid out for the uConsole's 1280x720 screen (forked from
     Picamera2's app_full.py).
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
EOF

# --- DEBIAN/prerm -------------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/prerm"
#!/bin/bash
set -e

if systemctl list-unit-files zmk-cursor-scroll.service >/dev/null 2>&1; then
    systemctl disable --now zmk-cursor-scroll.service || true
fi
EOF

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
