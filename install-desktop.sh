#!/usr/bin/env bash
# Add Ventris to the Linux app menu for the current user, running from this source folder.
# (The AppImage from the Releases page doesn't need this.)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME/.local/share/applications/io.github.armchairpolymath.Ventris.desktop"
mkdir -p "$(dirname "$dest")"
cat > "$dest" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Ventris
Comment=Explains G-code line by line
Exec="$here/run.sh" %f
Icon=$here/ventris/assets/ventris.png
Terminal=false
Categories=Development;
MimeType=text/x-gcode;
DESKTOP
update-desktop-database "$(dirname "$dest")" 2>/dev/null || true
echo "Installed $dest"
