# Pokédex — Complete Setup Guide (from scratch)

Everything needed to take a blank Arduino UNO Q to a working Pokédex.
Written so you can come back in six months and follow it without remembering
anything.

Device is called **shimi**. User `arduino`, password `arduino`.
All app files live in **`~/pokedexv5/`**.

---

## 0. What this thing is

Point the camera at a Pokémon card or figure, press SCAN. It uploads the photo,
reverse-image-searches it with Google Lens, matches the result against a local
1025-Pokémon database, then shows the stats on screen and speaks the name out
loud. Every catch is saved forever in a local database.

Nine physical buttons drive everything. No touchscreen, no keyboard.

---

## 1. Hardware

| Part | Purpose | Notes |
|---|---|---|
| Arduino UNO Q | the brain | Linux side runs everything |
| Waveshare 2.8" HDMI LCD | screen | 640×480, via USB-C PD hub |
| Arducam UB0238 USB camera | eyes | shows up as "Hy-Usb2.0" |
| ESP32-C3 Super Mini | 9 buttons | connects to shimi by **USB** |
| PAM8403 amp + 2 speakers | sound | **separate 5V supply** |
| USB PnP sound card | audio out | |

### The one rule that will burn you

**The PAM8403 amplifier must have its own 5V supply** (phone charger or power
bank). Share only the GND wire with the UNO Q.

If you power the amp from the UNO Q, the whole board browns out and shuts down
the moment audio plays. This looks like a random crash and you will waste an
hour on it.

### Buttons

Each button: one leg → its GPIO, other leg → GND. No resistors (internal
pull-ups). 2-pin tactile buttons have no polarity — either leg either way.

| Button | GPIO | Does |
|---|---|---|
| enter | 0 | select / open |
| cancel | 1 | back |
| tab | 2 | switch tab / region |
| up | 3 | move up |
| down | 4 | move down |
| right | 5 | next tab / region |
| left | 6 | prev tab / region |
| pageleft | 7 | **SCAN** |
| pageright | 10 | back |

GPIO 2 is a strapping pin. If `tab` misbehaves or the board won't boot, move it
to GPIO 21 (change the wire *and* the sketch).

---

## 2. Flash the keypad

1. Open `keypad_serial.ino` in Arduino IDE
2. Board: **ESP32C3 Dev Module**
3. **Tools → USB CDC On Boot → Enabled** ← miss this and serial won't work
4. Upload

Test it: open Serial Monitor at 115200, press buttons. Each should print its
name (`enter`, `up`, `pageleft`...). If a button fires on its own, that pin is
floating — check the wire.

Then plug the ESP32 into shimi's USB. It becomes `/dev/ttyACM0`.

---

## 3. First-time system setup on shimi

SSH in from your laptop:

```bash
ssh arduino@192.168.1.56
```

### Storage — read this before installing anything

The 32GB eMMC is split into two partitions:

- `/` (system) — **10GB, nearly full**
- `/home/arduino` — **18GB, mostly empty**

pip installs to `/` by default and fills it, then everything fails with
`No space left on device`. Always install like this:

```bash
mkdir -p /home/arduino/tmp
TMPDIR=/home/arduino/tmp pip3 install --user --break-system-packages <package>
```

Never install full `torch` — it drags in 500MB+ of NVIDIA CUDA libraries that
are useless here (no NVIDIA GPU) and will fill the disk.

If you run out of space:
```bash
pip3 cache purge
sudo apt clean
df -h /
```

### Install the packages

```bash
mkdir -p /home/arduino/tmp
TMPDIR=/home/arduino/tmp pip3 install --user --break-system-packages \
  pygame opencv-python requests rapidfuzz google-search-results pyserial pillow
```

### Static IP

Stops the IP changing on every reboot. Uses the 2.4GHz network:

```bash
nmcli device wifi connect "FTTH" password "12345678"
sudo nmcli connection modify FTTH ipv4.addresses 192.168.1.56/24
sudo nmcli connection modify FTTH ipv4.gateway 192.168.1.1
sudo nmcli connection modify FTTH ipv4.dns "8.8.8.8 1.1.1.1"
sudo nmcli connection modify FTTH ipv4.method manual
sudo nmcli connection down FTTH && sudo nmcli connection up FTTH
```

Verify — should say `proto static`:
```bash
hostname -I
ip route | grep default
```

### Landscape screen, permanently

Without this the screen boots portrait every time:

```bash
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/90-rotate.conf > /dev/null << 'EOF'
Section "Monitor"
    Identifier "DP-1"
    Option "Rotate" "left"
EndSection
EOF
sudo reboot
```

### Stop Arduino App Lab auto-launching

It opens over your app on every boot:

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/ArduinoAppLab.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Arduino App Lab
Exec=arduino-app-lab
Hidden=true
X-XFCE-Autostart-Enabled=false
NoDisplay=true
EOF
```

`Hidden=true` alone isn't enough on XFCE — you need
`X-XFCE-Autostart-Enabled=false` too.

Leave `arduino-router.service` and `arduino-app-cli.service` running. They're
background daemons, not the GUI, and other things depend on them.

### Audio volume

```bash
amixer -c 1 cset numid=6 100%
amixer -c 1 cset numid=5 1
```

(`-c 1` = the USB card. Check with `aplay -l` — the app auto-detects it, but
`amixer` needs the number.)

---

## 4. Get the files onto shimi

Unzip the package on your laptop, then from PowerShell:

```powershell
scp -r C:\path\to\pokedexv5 arduino@192.168.1.56:/home/arduino/
```

`scp -r` nests folders if the target exists. Check and flatten if needed:

```bash
ls -R ~/pokedexv5/
# if you see ~/pokedexv5/pokedexv5/ :
mv ~/pokedexv5/pokedexv5/* ~/pokedexv5/ && rmdir ~/pokedexv5/pokedexv5
```

### Your SerpAPI key

```bash
nano ~/pokedexv5/serp_key.txt
```

Paste the key (nothing else, no quotes). Ctrl+O, Enter, Ctrl+X.

```bash
chmod 600 ~/pokedexv5/serp_key.txt
```

Get a key free at serpapi.com — 250 searches/month. Check what's left:
```bash
curl -s "https://serpapi.com/account?api_key=$(cat ~/pokedexv5/serp_key.txt)"
```

---

## 5. Build the database (once, ~40 min)

Only if `~/pokedex/pokemon_db.json` doesn't already exist.

```bash
mkdir -p ~/pokedex
python3 ~/pokedexv5/build_db.py            # ~40 min, 1025 pokemon
python3 ~/pokedexv5/download_ui_images.py  # all 1025 artwork PNGs
```

Run them in two terminals at once to save time. `download_ui_images.py` skips
files it already has, so re-run it if it dies partway.

Verify:
```bash
python3 -c "
import json
db=json.load(open('/home/arduino/pokedex/pokemon_db.json'))
print('pokemon:', len(db))
b=db['bulbasaur']
print('fields:', sorted(b.keys()))
"
ls ~/pokedex/ui_images/ | wc -l    # should be 1025
```

Both live in `~/pokedex/` and are shared — the app reads them from there.

### Location data (optional, ~30 min)

The Location tab needs encounter data, which isn't in the base database:

```bash
python3 ~/pokedexv5/build_locations.py
```

Safe to re-run — it skips pokemon it already did and saves every 25, so if it
dies partway just run it again. Without it the Location tab says "No location
data". Many pokemon legitimately have none (evolutions, legendaries, starters)
and show "Not found in the wild".

---

## 6. Check everything

```bash
bash ~/pokedexv5/setup.sh
```

Every line should say `[OK]`. Fix any `[MISS]` before running.

---

## 7. Run it

Two terminals.

**Terminal 1 — keypad:**
```bash
python3 ~/pokedexv5/key_serial.py
```
Leave it running. Every button press prints its name here.

**Terminal 2 — the app:**
```bash
export DISPLAY=:0
python3 ~/pokedexv5/pokedex_app.py
```

**Kill both:**
```bash
pkill -9 -f pokedex_app.py; pkill -9 -f key_serial.py
```

---

## 8. Using it

```
Main Menu
├── Reverse Image Version
│   ├── Play Catch 'Em All    camera starts HERE (not before)
│   ├── Pokedex List          all 1025 by region, caught ones green
│   ├── Search by Name        letter grid
│   ├── Favourites            starred pokemon
│   ├── Caught Pokemon        completion %, most caught, latest
│   ├── Catch Log             every catch, newest first
│   └── Back
├── PhyAI Challenge           placeholder
├── Trainer Status            profile, level, badges, switch trainer
└── Data                      erase catches / erase everything
```

**First run:** there's no trainer yet. Open **Trainer Status** and it walks you
through creating one — name, city, age, gender, team (Red / Blue / Yellow).
Name and city use the letter grid: dpad moves, **enter** picks, DONE finishes.
**cancel** goes back a step.

**Catch 'Em All:** aim using the live feed, **pageleft** to scan. The scan
screen freezes on the exact photo being uploaded. On a hit you get the tabbed
result (Stats / Location / Evolution / Moves / Cry), it speaks the name,
records the catch, and shows an XP toast. **back** returns to the live feed;
**back** again exits to the menu.

**Pokedex List:** up/down scrolls, **tab** switches region, **enter** opens.

**Any detail screen:** **tab** or left/right cycles tabs, **enter** stars the
pokemon as a favourite, **cancel** goes back.

**Caught Pokemon:** **tab** cycles the sort — Dex No. / Most Caught / Recent.

**Trainer Status:** three tabs, **tab** cycles them.
- **Info** — profile card, level, XP bar, totals, and the menu (switch trainer,
  edit profile, How to Play)
- **Regions** — all 9 with progress bars and the 60% unlock marker
- **Badges** — all 72, locked ones grey

In the trainer list, **tab** deletes a trainer (with confirmation).

### XP and levels

| Event | XP |
|---|---|
| Catch a pokemon | 100 |
| First time catching that species | +400 bonus |

Level N costs `500 × N` XP. Caps at level 50.

### Badges — 72 across 9 regions

Every region is always playable. What locks is a region's **badge set**: catch
**60%** of a region to unlock its 8 badges, then each badge has its own
requirement (catch a specific pokemon / catch N from the region / complete the
regional dex).

| Region | Need | of |
|---|---|---|
| Kalos | 44 | 72 |
| Alola | 53 | 88 |
| Galar | 58 | 96 |
| Johto | 60 | 100 |
| Sinnoh | 65 | 107 |
| Paldea | 72 | 120 |
| Hoenn | 81 | 135 |
| Kanto | 91 | 151 |
| Unova | 94 | 156 |

Full badge tables are in **GAME_MANUAL.md**, and the same content is in the
app under Trainer → Info → How to Play.

### Badge art

Drawn by the app as original shapes — real names and colours, not Nintendo's
artwork. To use your own, drop PNGs in `~/pokedexv5/badges/` named after the
badge (`boulder_badge.png`). Missing files fall back to the drawn shape.

### Data

**Erase my catches** — wipes the current trainer's catches, XP, badges and
favourites. Keeps the profile.
**Erase EVERYTHING** — every trainer, every catch. Back to a blank device.

Both ask for confirmation first.

Everything is saved to `~/pokedexv5/catches.db` (SQLite) and survives reboots.
Multiple trainers share the one file — each keeps their own catches.

---

## 9. Why things are built the way they are

Read this before "fixing" any of it.

### The keypad is USB, not WiFi

The router has **AP/client isolation** — WiFi devices can't talk to each other.
shimi and the ESP32 both get internet but can't ping each other (100% loss).
The old WiFi keypad returned `HTTP -1` forever because of this.

USB serial sidesteps the network entirely. Don't switch it back to WiFi unless
you can disable isolation on the router.

### The image host is litterbox

SerpApi's Google Lens API **only accepts publicly-hosted image URLs**. File
upload isn't supported (open feature request, years old). So the capture has to
be uploaded somewhere public first.

Hosts that stopped working — Google Lens silently returns **0 matches**:
- tmpfiles.org
- catbox.moe

Hosts that don't work here:
- imgur — blocked in India
- 0x0.st — unreachable from this network
- AWS S3 — Lens has known trouble with S3 URLs

Works: **litterbox.catbox.moe** (verified, 60 matches). Files expire in 1h,
which is fine — the URL only needs to survive one search.

GitHub raw URLs also work (verified, 59 matches) if litterbox ever dies. That
needs a repo + a **classic** token with the `repo` scope. Fine-grained tokens
with "public repositories" are read-only and give a confusing **404** (not 403)
on write.

### Camera and audio auto-detect

Both device numbers shift between reboots:
- Camera: `/dev/video0` one boot, `/dev/video1` or `video2` the next
- Audio: `card 0` or `card 1`

The camera is trickier — **two** devices match "Hy-" (e.g. video1 and video4)
but only one actually returns frames. `find_camera()` tries each and keeps the
one that delivers a real frame. `find_audio()` parses `aplay -l` and prefers
the USB card.

Never hardcode either.

### Camera needs MJPEG

Without this the camera opens but returns nothing:
```python
cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
```

### The 5-frame flush

The camera buffers frames. Without flushing, a scan captures a stale frame from
several seconds ago — you'd aim at a Pokémon and it would upload a photo of
your hand. So before capturing:
```python
for _ in range(5): self.cap.read()
ret, frame = self.cap.read()
```

### SDL_AUDIODRIVER=dummy

This line must be at the very **top** of the app, before `import pygame`:
```python
os.environ['SDL_AUDIODRIVER'] = 'dummy'
```
Otherwise pygame grabs the audio device and espeak/aplay can't use it.

---

## 10. When it breaks

### "Pokemon not found" every time

Look at what the camera actually sent:
```bash
export DISPLAY=:0
ristretto ~/pokedexv5/capture.jpg
```

- **Wrong thing in frame** (your hand, etc.) → the flush isn't working
- **Blurry / dark** → aim and lighting
- **Looks fine** → the host died. Test it:

```bash
cd ~/pokedexv5 && python3 -c "
import requests, time
from serpapi import GoogleSearch
KEY=open('serp_key.txt').read().strip()
u=requests.post('https://litterbox.catbox.moe/resources/internals/api.php',
  data={'reqtype':'fileupload','time':'1h'},
  files={'fileToUpload':open('capture.jpg','rb')}).text.strip()
print('url:', u); time.sleep(2)
r=GoogleSearch({'engine':'google_lens','url':u,'api_key':KEY}).get_dict()
print('matches:', len(r.get('visual_matches',[])))
"
```

Confirm it's the host, not the image, with a URL known to work:
```bash
cd ~/pokedexv5 && python3 -c "
from serpapi import GoogleSearch
KEY=open('serp_key.txt').read().strip()
r=GoogleSearch({'engine':'google_lens','api_key':KEY,
 'url':'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png'}).get_dict()
print('matches:', len(r.get('visual_matches',[])))
"
```
59-ish matches = SerpAPI is fine, your host is dead → find a new one.
0 matches = SerpAPI or quota problem.

Check quota:
```bash
curl -s "https://serpapi.com/account?api_key=$(cat ~/pokedexv5/serp_key.txt)" | grep searches_left
```

### UNO Q shuts down when audio plays
The amp is on the UNO Q's power. Give it its own 5V supply. Only GND shared.

### No audio
```bash
aplay -l                                    # find the USB card number
espeak -a 200 "test" --stdout | aplay -D plughw:1,0
cd ~/pokedexv5 && python3 -c "
import sys; sys.path.insert(0,'.')
from pokedex_app import AUDIO_DEV; print('detected:', AUDIO_DEV)"
```
If espeak works but the app is silent, `AUDIO_DEV` detected wrong.

### Camera black / won't open
```bash
v4l2-ctl --list-devices
cd ~/pokedexv5 && python3 -c "
import sys; sys.path.insert(0,'.')
from pokedex_app import find_camera; print(find_camera())"
```
Should print the Hy- device that actually works.

### Keypad dead
```bash
ls /dev/ttyACM*          # should exist
fuser /dev/ttyACM0       # something else holding it?
```
Close the Arduino IDE Serial Monitor — it holds the port.
Button names print but nothing happens → that screen doesn't use that button.

### Can't SSH / password rejected
IP probably changed. On the HDMI screen:
```bash
hostname -I
whoami
```
Then redo the static IP (section 3).

### Screen is portrait
```bash
DISPLAY=:0 xrandr --output DP-1 --rotate left      # right now
```
Permanent fix is `/etc/X11/xorg.conf.d/90-rotate.conf` (section 3).

### No space left on device
```bash
df -h              # look at / vs /home/arduino
pip3 cache purge
sudo apt clean
```
Reinstall with `TMPDIR=/home/arduino/tmp pip3 install --user --break-system-packages`.

---

## 11. Files

```
~/pokedexv5/
├── pokedex_app.py          the whole app
├── key_serial.py           keypad reader
├── keypad_serial.ino       flash to ESP32-C3
├── build_db.py             only if DB missing
├── download_ui_images.py   only if images missing
├── build_locations.py      adds Location tab data
├── setup.sh                pre-flight check
├── GAME_MANUAL.md          the game: badges, regions, strategy
├── badges/                 optional: your own badge PNGs
├── serp_key.txt            YOUR key (create it)
├── catches.db              made on first catch
└── capture.jpg             latest camera frame

~/pokedex/                  shared, built once
├── pokemon_db.json         1025 pokemon
└── ui_images/              1025 PNGs
```

Inside `pokedex_app.py`:
- `CatchDB` — trainers, catches, XP, favourites, log, badges (one SQLite file)
- `level_from_xp()` — XP curve
- `REGION_RANGE` / `BADGES_BY_REGION` / `badge_earned()` — the 72 badges
- `draw_badge()` — draws all 20 badge shapes
- `TextInput` / `NumberInput` / `ChoiceInput` — dpad-driven input widgets
- `draw_pokeball()` / `draw_star()` — cursor and favourite marker
- `find_camera()` / `find_audio()` — device detection
- `upload_image()` — litterbox
- `search_image()` / `extract_candidates()` / `match_pokemon()` — recognition
- `App` — every screen as an `h_*` handler

### Upgrading from an older build

The database migrates itself. An old `catches` table with no trainer column
gets moved onto a profile called "Trainer" on first run, so nothing is lost.

---

## 12. Quick reference

```bash
# run
python3 ~/pokedexv5/key_serial.py                            # terminal 1
export DISPLAY=:0 && python3 ~/pokedexv5/pokedex_app.py      # terminal 2

# kill
pkill -9 -f pokedex_app.py; pkill -9 -f key_serial.py

# check
bash ~/pokedexv5/setup.sh
v4l2-ctl --list-devices
aplay -l
ls /dev/ttyACM*
hostname -I
df -h

# shutdown
sudo shutdown now
```
