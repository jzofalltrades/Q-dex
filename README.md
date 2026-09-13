# Q-dexter — A Real Handheld Pokédex

A fully working handheld Pokédex built on the **Arduino UNO Q**, for the
**Arduino Physical AI Challenge India 2026**. Point it at a Pokémon, press
scan, and it identifies the creature, shows its Pokédex entry, speaks its
name, and logs the catch — with on-device AI, a voice assistant, and a
3D-printed Gen-1 Kanto shell.

### 🔗 Live pages
- **[📖 Full Build Guide](https://jzofalltrades.github.io/Q-dex/)** — the complete, illustrated how-to
- **[🎮 3D Model Viewer](https://jzofalltrades.github.io/Q-dex/viewer.html)** — rotate the enclosure in your browser

---

## What it does

- **Reverse Image Version** — camera capture → Google Lens → identifies any of
  the **1025 Pokémon**, shows stats/evolution/moves/location, speaks the entry,
  and records the catch.
- **PhyAI Challenge** — an **on-device** neural network (MobileNetV2, runs with
  no internet) that recognises four Pokémon (Bulbasaur, Charizard, Pikachu,
  Squirtle) live from the camera.
- **Professor Oak voice assistant** — ask questions out loud; on-device
  speech-to-text (whisper.cpp) → Claude → spoken reply. Knows your trainer
  profile and real catch progress.
- **Trainer system** — profiles, XP, levels, and **72 gym badges** across all
  9 regions, with region unlock gating.
- **Physical build** — 3D-printed Kanto-red shell, physical keypad, indicator
  LEDs, a blinking lens LED, and a real speaker.

## How it works

The device is an Arduino UNO Q (embedded Linux) running a pygame app, with an
ESP32-C3 handling the physical keypad and lens LED over USB serial. A camera
feeds both the online reverse-image path and the offline on-device classifier.
Audio is spoken through espeak into a PAM8403 amp and speaker.

```
Camera ─┬─► Reverse Image Version ─► Google Lens ─► Pokédex entry ─► speak + log
        └─► PhyAI (on-device model) ─► live identification

Mic ─► whisper.cpp ─► Claude ─► Professor Oak reply ─► speak
```

Full architecture, schematics, bill of materials, wiring, print settings, and
step-by-step build phases are in the **[Build Guide](https://jzofalltrades.github.io/Q-dex/)**.

## Repository layout

| Path | What it is |
|------|-----------|
| `pokedex_app.py` | The main pygame Pokédex application |
| `key_serial.py` | Host-side reader for the ESP32 keypad + LED forwarding |
| `keypad_serial.ino` | ESP32-C3 firmware (keypad + WS2812 lens LED) |
| `pokedex_phyai.tflite` | On-device Pokémon classifier (TFLite) |
| `labels.txt` | Class labels for the on-device model |
| `badges/` | All 72 gym-badge images, by region |
| `build_db.py`, `build_locations.py` | Database build scripts |
| `index.html`, `viewer.html` | The build-guide website and 3D viewer |
| `models/` | 3D model of the enclosure (`.glb`) |
| `cad/` | Fusion 360 / STL enclosure files |

## Hardware

Arduino UNO Q · ESP32-C3 Super Mini · USB camera · PAM8403 amplifier + speaker ·
WS2812 LED · indicator LEDs · 3D-printed enclosure. Full BOM in the build guide.

## License

This project's code and designs are released under the MIT License — see the LICENSE file. You're free to build your own, modify it, and share it, with credit.

**Non-commercial fan project.** Pokémon and all related names, data, and cries are trademarks of Nintendo / Game Freak / The Pokémon Company. Q-dex is an independent fan project, not affiliated with or endorsed by Nintendo, and may not be sold commercially.



## Built by

[jzofalltrades](https://github.com/jzofalltrades) — solo entry, Arduino
Physical AI Challenge India 2026.
