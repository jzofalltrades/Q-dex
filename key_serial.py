"""
key_serial.py - Reads the ESP32-C3 keypad over USB serial and writes
trigger files that pokedex_app.py polls.

Run: python3 ~/test/key_serial.py
Requires: pip3 install pyserial --break-system-packages

Button -> trigger mapping:
  enter     -> select   (open highlighted menu item / confirm)
  cancel    -> back
  pageright -> mute
  pageleft  -> scan      (start detection, gameplay only)
  tab       -> tab       (switch tab / region)
  up/down/left/right -> dpad navigation

Also forwards an LED signal to the ESP32: the app writes '1' or '0' to
/tmp/led_trigger, and we send that byte over the same serial port (which
only this process may hold open) so the WS2812 blinks while audio plays.
"""

import serial

PORT = '/dev/ttyACM0'
BAUD = 115200

TRIGGERS = {
    'pageleft':  '/tmp/scan_trigger',
    'pageright': '/tmp/mute_trigger',
    'cancel':    '/tmp/back_trigger',
    'enter':     '/tmp/select_trigger',
    'tab':       '/tmp/tab_trigger',
    'up':        '/tmp/up_trigger',
    'down':      '/tmp/down_trigger',
    'left':      '/tmp/left_trigger',
    'right':     '/tmp/right_trigger',
}

LED_TRIGGER = '/tmp/led_trigger'
import os

print(f"Reading keypad on {PORT}")
ser = serial.Serial(PORT, BAUD, timeout=0.2)

_last_led = None

def _poll_led():
    """If the app changed the LED state, forward one byte to the ESP32.
    '1' = audio on (blink blue), '0' = off. Only sends on change, so we're
    not spamming the serial line every loop."""
    global _last_led
    try:
        with open(LED_TRIGGER) as f:
            val = f.read().strip()
    except Exception:
        return
    if val in ('0', '1') and val != _last_led:
        ser.write(val.encode())
        _last_led = val

while True:
    _poll_led()
    line = ser.readline().decode(errors='ignore').strip()
    if not line:
        continue
    print(f"Button: {line}")
    if line in TRIGGERS:
        open(TRIGGERS[line], 'w').write('1')
