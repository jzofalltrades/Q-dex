# Q-dexter 🔴

[![Live Site](https://img.shields.io/badge/🌐_Live_Site-View_Build_Guide-CC0000?style=for-the-badge)](https://jzofalltrades.github.io/Q-dex/)
[![3D Model](https://img.shields.io/badge/🎮_3D_Model-Rotate_It-FFD233?style=for-the-badge&labelColor=333)](https://jzofalltrades.github.io/Q-dex/viewer.html)
[![Physical AI](https://img.shields.io/badge/🧠_Physical_AI-On_Device-3B9EFF?style=for-the-badge&labelColor=333)](https://jzofalltrades.github.io/Q-dex/physical-ai.html)

![board](https://img.shields.io/badge/board-Arduino_UNO_Q-00979D?style=flat-square&logo=arduino)
![controller](https://img.shields.io/badge/controller-ESP32--C3-E7352C?style=flat-square&logo=espressif)
![model](https://img.shields.io/badge/AI-MobileNetV2_int8-FF6F00?style=flat-square&logo=tensorflow)
![accuracy](https://img.shields.io/badge/accuracy-95.8%25-3DDC84?style=flat-square)
![pokemon](https://img.shields.io/badge/Pokédex-1025_entries-A78BFA?style=flat-square)
![challenge](https://img.shields.io/badge/Arduino_Physical_AI_Challenge-2026-CC0000?style=flat-square)

> A real handheld Pokédex with on-device AI, a voice assistant, and camera-based Pokémon recognition — built on the Arduino UNO Q for the **Arduino Physical AI Challenge India 2026**.

---

## 🔴 What it does

Point it at a Pokémon, press scan, and Q-dexter identifies the creature, shows its Pokédex entry, speaks its name, and logs the catch.

- **📷 Reverse Image Version** — camera → Google Lens → identifies any of the **1025 Pokémon**, shows stats / evolution / moves / location, speaks the entry, records the catch.
- **🧠 PhyAI Challenge** — an **on-device** neural network (MobileNetV2, no internet) recognising four Pokémon live from the camera. [Read the deep-dive →](https://jzofalltrades.github.io/Q-dex/physical-ai.html)
- **🎙️ Professor Oak** — ask questions out loud; offline speech-to-text → Claude → spoken reply. Knows your trainer profile and real catch progress.
- **🏆 Trainer system** — profiles, XP, levels, and **72 gym badges** across all 9 regions.
- **🕹️ Physical build** — 3D-printed Kanto-red shell, physical keypad, indicator LEDs, a blinking lens LED, and a real speaker.

## 🧠 The Physical AI

The centrepiece: a **MobileNetV2** classifier, trained by transfer learning on Colab, quantized to a **2.59 MB int8** TFLite model that runs entirely on the UNO Q's CPU — no cloud, no API, no connection. **95.8% quantized validation accuracy.** Full training notebook and dataset are in this repo; the [Physical AI page](https://jzofalltrades.github.io/Q-dex/physical-ai.html) documents dataset, architecture, training, and results.

```
Camera ─┬─► Reverse Image Version ─► Google Lens ─► Pokédex entry ─► speak + log
        └─► PhyAI (on-device model) ─► live identification

Mic ─► whisper.cpp ─► Claude ─► Professor Oak ─► spoken reply
```

## 🛠️ Hardware

Arduino UNO Q (processor) · ESP32-C3 Super Mini (controller) · USB camera · PAM8403 amp + speaker · WS2812 lens LED · indicator LEDs · 3D-printed enclosure. Full BOM in the [build guide](https://jzofalltrades.github.io/Q-dex/).

## 📂 Repository

See the [**Repository Map**](https://jzofalltrades.github.io/Q-dex/#repo) for every folder and file explained. Highlights:

| Path | What |
|------|------|
| `pokedex_app.py` | The main Pokédex application |
| `pokedex_phyai.tflite` | The on-device AI model |
| `pokedex_phyai_train.ipynb` | The full training notebook (reproducible) |
| `dataset/` | The training images |
| `cad/` · `models/` | Enclosure CAD and 3D model |

## ⏱️ Build time

**1 month** to build from scratch. With this guide, the code, and copy-paste commands: **under a week** to replicate.


## 👤 Built by

**Jayant** · Nagpur, India · solo entry, Arduino Physical AI Challenge India 2026.
