#!/bin/bash
# setup.sh - one-time setup for pokedexv5 on shimi.
# Run: bash ~/pokedexv5/setup.sh

BASE=/home/arduino/pokedexv5
echo "=== pokedexv5 setup ==="

# 1. Check the shared database + images are present (we reuse them, not rebuild)
DB=/home/arduino/pokedex/pokemon_db.json
IMGS=/home/arduino/pokedex/ui_images

if [ -f "$DB" ]; then
    COUNT=$(python3 -c "import json;print(len(json.load(open('$DB'))))" 2>/dev/null)
    echo "[OK]   database found: $COUNT pokemon"
else
    echo "[MISS] $DB not found -> run: python3 $BASE/build_db.py"
fi

if [ -d "$IMGS" ]; then
    N=$(ls "$IMGS" | wc -l)
    echo "[OK]   images found: $N"
else
    echo "[MISS] $IMGS not found -> run: python3 $BASE/download_ui_images.py"
fi

# 2. Secrets
if [ -f "$BASE/serp_key.txt" ]; then
    echo "[OK]   serp_key.txt present"
else
    echo "[MISS] create $BASE/serp_key.txt  (paste your SerpAPI key, no quotes)"
fi

chmod 600 "$BASE"/serp_key.txt 2>/dev/null

# 3. Python deps
python3 - <<'EOF'
mods = ['pygame','cv2','requests','rapidfuzz','serpapi','serial','PIL']
missing = []
for m in mods:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
if missing:
    print("[MISS] python modules:", ', '.join(missing))
    print("       pip3 install pygame opencv-python requests rapidfuzz \\")
    print("         google-search-results pyserial pillow --break-system-packages")
else:
    print("[OK]   all python modules present")
EOF

# 4. Devices
ls /dev/ttyACM* >/dev/null 2>&1 && echo "[OK]   keypad on $(ls /dev/ttyACM* | head -1)" \
    || echo "[MISS] no /dev/ttyACM* - plug in the ESP32 keypad"

echo ""
echo "Run it:"
echo "  Terminal 1: python3 $BASE/key_serial.py"
echo "  Terminal 2: export DISPLAY=:0 && python3 $BASE/pokedex_app.py"
