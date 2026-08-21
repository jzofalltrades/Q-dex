#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# install_launcher.sh - makes the Pokedex feel like a Game Boy, not a computer.
#
# Sets up:
#   1. A Pokedex icon on the desktop        (double-click to play)
#   2. The same icon in the applications menu
#   3. Autostart on boot                    (power on -> Pokedex)
#
# Run once:   bash ~/pokedexv5/install_launcher.sh
# Undo:       bash ~/pokedexv5/install_launcher.sh --remove
# ─────────────────────────────────────────────────────────────────────────────

BASE=/home/arduino/pokedexv5
DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON_PNG="$BASE/pokedex_icon.png"
DESKTOP_FILE="pokedex.desktop"

# ── remove ───────────────────────────────────────────────────────────────────
if [ "$1" = "--remove" ]; then
    rm -f "$DESKTOP_DIR/$DESKTOP_FILE"
    rm -f "$APPS_DIR/$DESKTOP_FILE"
    rm -f "$AUTOSTART_DIR/$DESKTOP_FILE"
    echo "Removed. The Pokedex no longer starts on boot."
    echo "Run it by hand with:  bash $BASE/pokedex.sh"
    exit 0
fi

echo "=== Pokedex launcher setup ==="

# ── 1. the icon: svg -> png ──────────────────────────────────────────────────
# .desktop files want a raster icon. If you drop your own pokedex_icon.png in
# $BASE it gets used as-is and this step is skipped.
if [ -f "$ICON_PNG" ]; then
    echo "[skip] $ICON_PNG already exists - using yours"
else
    if command -v rsvg-convert > /dev/null; then
        rsvg-convert -w 256 -h 256 "$BASE/pokedex_icon.svg" -o "$ICON_PNG"
        echo "[ok]   icon converted with rsvg-convert"
    elif command -v convert > /dev/null; then
        convert -background none -resize 256x256 "$BASE/pokedex_icon.svg" "$ICON_PNG"
        echo "[ok]   icon converted with imagemagick"
    elif python3 -c "import cairosvg" 2>/dev/null; then
        python3 -c "import cairosvg; cairosvg.svg2png(url='$BASE/pokedex_icon.svg', write_to='$ICON_PNG', output_width=256, output_height=256)"
        echo "[ok]   icon converted with cairosvg"
    else
        # No converter? Draw it with pygame, which is definitely installed.
        python3 - << PYEOF
import pygame, math
pygame.init()
S=256
surf=pygame.Surface((S,S), pygame.SRCALPHA)
c=S//2; r=112
pygame.draw.circle(surf,(245,245,250),(c,c),r)
prev=surf.get_clip()
surf.set_clip(pygame.Rect(0,0,S,c))
pygame.draw.circle(surf,(227,53,13),(c,c),r)
surf.set_clip(prev)
pygame.draw.circle(surf,(22,22,28),(c,c),r,9)
pygame.draw.rect(surf,(22,22,28),(c-r,c-13,r*2,26))
pygame.draw.circle(surf,(22,22,28),(c,c),42)
pygame.draw.circle(surf,(240,240,246),(c,c),32)
pygame.draw.circle(surf,(22,22,28),(c,c),32,5)
pygame.draw.circle(surf,(250,250,252),(c,c),17)
pygame.image.save(surf,'$ICON_PNG')
print("[ok]   icon drawn with pygame")
PYEOF
    fi
fi

chmod +x "$BASE/pokedex.sh"

# ── 2. build the .desktop file ───────────────────────────────────────────────
TMP=$(mktemp)
cat > "$TMP" << EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Pokedex
GenericName=Pokemon Scanner
Comment=Point it at a Pokemon and press SCAN
Exec=bash $BASE/pokedex.sh
Icon=$ICON_PNG
Terminal=false
Categories=Game;
StartupNotify=false
EOF

# ── 3. desktop shortcut ──────────────────────────────────────────────────────
mkdir -p "$DESKTOP_DIR"
cp "$TMP" "$DESKTOP_DIR/$DESKTOP_FILE"
chmod +x "$DESKTOP_DIR/$DESKTOP_FILE"
# XFCE wants the file explicitly trusted or it shows a "untrusted launcher" prompt
gio set "$DESKTOP_DIR/$DESKTOP_FILE" metadata::xfce-exe-checksum \
    "$(sha256sum "$DESKTOP_DIR/$DESKTOP_FILE" | awk '{print $1}')" 2>/dev/null
gio set "$DESKTOP_DIR/$DESKTOP_FILE" metadata::trusted true 2>/dev/null
echo "[ok]   desktop icon  -> $DESKTOP_DIR/$DESKTOP_FILE"

# ── 4. applications menu ─────────────────────────────────────────────────────
mkdir -p "$APPS_DIR"
cp "$TMP" "$APPS_DIR/$DESKTOP_FILE"
chmod +x "$APPS_DIR/$DESKTOP_FILE"
update-desktop-database "$APPS_DIR" 2>/dev/null
echo "[ok]   apps menu     -> $APPS_DIR/$DESKTOP_FILE"

# ── 5. autostart on boot ─────────────────────────────────────────────────────
mkdir -p "$AUTOSTART_DIR"
cp "$TMP" "$AUTOSTART_DIR/$DESKTOP_FILE"
# a beat for X and USB to settle before we grab the camera and serial port
sed -i "s|^Exec=.*|Exec=bash -c 'sleep 8; bash $BASE/pokedex.sh'|" \
    "$AUTOSTART_DIR/$DESKTOP_FILE"
chmod +x "$AUTOSTART_DIR/$DESKTOP_FILE"
echo "[ok]   autostart     -> $AUTOSTART_DIR/$DESKTOP_FILE"

rm -f "$TMP"

echo ""
echo "Done."
echo ""
echo "  Double-click the Pokedex icon on the desktop to play."
echo "  It also starts by itself ~8s after boot."
echo "  Exit from the main menu drops you back to this desktop."
echo ""
echo "  Logs:     $BASE/pokedex.log"
echo "  Undo:     bash $BASE/install_launcher.sh --remove"
echo ""
echo "If the app ever crashes on boot you land on the desktop, not a black"
echo "screen - so you can always get back in here and fix it."
