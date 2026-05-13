#!/bin/bash
# Build uconsole-tweaks.deb from the contents of tweaks/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$SCRIPT_DIR/uconsole-tweaks"
VERSION="${ENV_VERSION:-0.1.0}"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/local/bin"
mkdir -p "$STAGE/etc/systemd/system"

# --- zmk-cursor-scroll --------------------------------------------------------

install -m 0755 "$SCRIPT_DIR/tweaks/zmk-cursor-scroll/zmk-cursor-scroll" \
    "$STAGE/usr/local/bin/zmk-cursor-scroll"

install -m 0644 "$SCRIPT_DIR/tweaks/zmk-cursor-scroll/zmk-cursor-scroll.service" \
    "$STAGE/etc/systemd/system/zmk-cursor-scroll.service"

# --- DEBIAN/control -----------------------------------------------------------

cat << EOF > "$STAGE/DEBIAN/control"
Package: uconsole-tweaks
Version: $VERSION
Maintainer: syndr <syndr@ultroncore.net>
Architecture: all
Depends: python3, python3-evdev, keyd
Description: Small standalone tweaks for the ClockworkPi uConsole.
 Ships:
   * zmk-cursor-scroll - hold the gamepad Select key to make the trackball
     drive the scroll wheel instead of the cursor.
EOF

# --- DEBIAN/postinst ----------------------------------------------------------

cat << 'EOF' > "$STAGE/DEBIAN/postinst"
#!/bin/bash
set -e

systemctl daemon-reload
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
EOF

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$STAGE" "$SCRIPT_DIR/uconsole-tweaks.deb"

rm -rf "$STAGE"
