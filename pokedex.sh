#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# pokedex.sh - the one thing you run.
#
# Starts the keypad reader in the background, then the app in the foreground.
# When the app exits (Exit menu, crash, anything), the keypad reader is killed
# too - so the next launch doesn't fight it for /dev/ttyACM0.
#
# Run it:      bash ~/pokedexv5/pokedex.sh
# Or:          double-click the Pokedex icon on the desktop
# Or:          it starts by itself on boot (see install_launcher.sh)
# ─────────────────────────────────────────────────────────────────────────────

BASE=/home/arduino/pokedexv5
LOG=$BASE/pokedex.log

export DISPLAY=:0

# ── one instance only ────────────────────────────────────────────────────────
# Double-clicking the icon twice, or the icon while it's already autostarted,
# would otherwise give you two apps fighting over the camera and the keypad.
if pgrep -f "$BASE/pokedex_app.py" > /dev/null; then
    echo "Pokedex is already running."
    exit 0
fi

# ── clean up anything left over from a previous run ──────────────────────────
pkill -9 -f "$BASE/key_serial.py" 2>/dev/null
rm -f /tmp/*_trigger
sleep 0.5

# ── kill the keypad whenever we leave, however we leave ──────────────────────
# EXIT covers a normal quit, INT is ctrl-C, TERM is a kill. Without this the
# keypad reader would outlive the app and hold the serial port open.
cleanup() {
    pkill -9 -f "$BASE/key_serial.py" 2>/dev/null
    rm -f /tmp/*_trigger
}
trap cleanup EXIT INT TERM

# ── keep the screen awake ────────────────────────────────────────────────────
xset s off       2>/dev/null
xset s noblank   2>/dev/null
xset -dpms       2>/dev/null

# ── start the keypad reader ──────────────────────────────────────────────────
echo "=== $(date) : starting pokedex ===" >> "$LOG"
python3 "$BASE/key_serial.py" >> "$LOG" 2>&1 &
KEYPID=$!
sleep 1

if ! kill -0 $KEYPID 2>/dev/null; then
    echo "Keypad reader died on startup - check $LOG" >> "$LOG"
    echo "Is the ESP32 plugged in? (ls /dev/ttyACM*)" >> "$LOG"
    # not fatal: the app still runs, you just can't press anything
fi

# ── run the app ──────────────────────────────────────────────────────────────
python3 "$BASE/pokedex_app.py" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}

echo "=== $(date) : pokedex exited (code $RC) ===" >> "$LOG"

# cleanup runs automatically via the trap
exit $RC
