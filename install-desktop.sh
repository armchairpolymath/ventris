#!/usr/bin/env bash
# Add "G-code Analyzer" to the GNOME app menu (current user only).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME/.local/share/applications/com.patrickhoskins.GcodeAnalyzer.desktop"
mkdir -p "$(dirname "$dest")"
cat > "$dest" <<DESKTOP
[Desktop Entry]
Type=Application
Name=G-code Analyzer
Comment=Explain G-code line by line
Exec="$here/run.sh" %f
Icon=document-properties-symbolic
Terminal=false
Categories=Development;Graphics;
MimeType=text/x-gcode;
DESKTOP
update-desktop-database "$(dirname "$dest")" 2>/dev/null || true
echo "Installed $dest"
