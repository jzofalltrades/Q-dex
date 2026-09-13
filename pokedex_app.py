import os
import re
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pygame
import cv2
import json
import subprocess
import requests
import math
import wave
import struct
import threading
import time
import sqlite3
from datetime import datetime
from collections import Counter
from rapidfuzz import process, fuzz
from serpapi import GoogleSearch

# ─── Config ───────────────────────────────────────────────
BASE          = '/home/arduino/pokedexv5'
SERP_API_KEY  = open(f'{BASE}/serp_key.txt').read().strip()
DB_PATH       = '/home/arduino/pokedex/pokemon_db.json'
UI_IMG_DIR    = '/home/arduino/pokedex/ui_images'
CATCH_DB      = f'{BASE}/catches.db'
CAPTURE_PATH  = f'{BASE}/capture.jpg'
BADGE_IMG_DIR = f'{BASE}/badges'

# GitHub is the image host - see upload_image() for why every free host failed.
GH_USER  = 'jzofalltrades'
GH_REPO  = 'pokedex_v1'
GH_DIR   = 'pokedex_capture'
GH_TOKEN = open(f'{BASE}/gh_token.txt').read().strip()

# Professor Oak - Claude API + local whisper.cpp speech-to-text.
# The key file is optional: if it's missing, Oak shows a friendly message
# instead of crashing, so the rest of the app still runs.
try:
    CLAUDE_KEY = open(f'{BASE}/claude_key.txt').read().strip()
except Exception:
    CLAUDE_KEY = ''
WHISPER_BIN   = '/home/arduino/whisper.cpp/build/bin/whisper-cli'
WHISPER_MODEL = '/home/arduino/whisper.cpp/models/ggml-tiny.en.bin'
OAK_WAV       = '/home/arduino/whisper.cpp/oak.wav'
# OAK_MIC is resolved at record time from find_mic(), not fixed here,
# because the two identical USB cards renumber between reboots.

# PhyAI - on-device Pokemon recognition, no internet, no API.
# Trained on Colab (MobileNetV2, transfer learning), exported to TFLite.
PHYAI_MODEL  = f'{BASE}/pokedex_phyai.tflite'
PHYAI_LABELS = f'{BASE}/labels.txt'
PHYAI_SIZE   = 160          # must match the size the model was trained at
PHYAI_CONF_THRESHOLD = 0.60 # below this, treat it as "not sure" rather than guess
# Throw animation. Off for now - the board was browning out under load and
# the animation was the visible symptom, not the cause (it costs 0.05ms/frame
# on this hardware). Flip to True once the 5V supply is sorted.
THROW_ANIM    = False
BALL_BIG      = 56   # parked / start of throw
BALL_SMALL    = 34   # landed, further away
SCORE_CUTOFF  = 85


# Trigger files (written by key_serial.py)
TRIG = {
    'scan':  '/tmp/scan_trigger',
    'back':  '/tmp/back_trigger',
    'select':'/tmp/select_trigger',
    'tab':   '/tmp/tab_trigger',
    'up':    '/tmp/up_trigger',
    'down':  '/tmp/down_trigger',
    'left':  '/tmp/left_trigger',
    'right': '/tmp/right_trigger',
    'mute':  '/tmp/mute_trigger',
}

SCREEN_W, SCREEN_H = 640, 480

# The 3D-printed bezel hides a few pixels at the edges of the panel. Rather
# than shift every draw call, the whole UI is drawn to an off-screen canvas
# and blitted inset by these margins so nothing lands under the bezel. Tune
# these if the fit changes: bigger LEFT pushes content right, etc. All in
# pixels. Set every value to 0 to disable and draw edge-to-edge again.
BEZEL_LEFT   = 28
BEZEL_RIGHT  = 6
BEZEL_TOP    = 4
BEZEL_BOTTOM = 4

BG=(12,20,44); PANEL=(20,32,66); RED=(220,50,50); ORANGE=(240,140,40)
YELLOW=(245,200,40); WHITE=(245,245,250); CYAN=(90,180,235)
GREY=(120,130,150); GREEN=(40,210,90); BLACK=(8,12,26); HILITE=(40,70,130)

TYPE_COLORS={'normal':(168,168,120),'fire':(240,128,48),'water':(104,144,240),
    'electric':(248,208,48),'grass':(120,200,80),'ice':(152,216,216),
    'fighting':(192,48,40),'poison':(160,64,160),'ground':(224,192,104),
    'flying':(168,144,240),'psychic':(248,88,136),'bug':(168,184,32),
    'rock':(184,160,56),'ghost':(112,88,152),'dragon':(112,56,248),
    'dark':(112,88,72),'steel':(184,184,208),'fairy':(238,153,172)}

STAT_LABELS=[('hp','HP'),('attack','Attack'),('defense','Defense'),
    ('special-attack','Sp.Atk'),('special-defense','Sp.Def'),('speed','Speed')]

REGIONS=['Kanto','Johto','Hoenn','Sinnoh','Unova','Kalos','Alola','Galar','Paldea']
RESULT_TABS=['Stats','Location','Evolution','Moves','Cry']

# ─── Database Manager ─────────────────────────────────────
BADGE_UNLOCK_PCT = 0.60     # catch this much of a region to unlock its badges

# Region -> (national dex start, end)
REGION_RANGE = {
    'Kanto':  (1, 151),
    'Johto':  (152, 251),
    'Hoenn':  (252, 386),
    'Sinnoh': (387, 493),
    'Unova':  (494, 649),
    'Kalos':  (650, 721),
    'Alola':  (722, 809),
    'Galar':  (810, 905),
    'Paldea': (906, 1025),
}

REGION_ORDER = ['Kanto', 'Johto', 'Hoenn', 'Sinnoh', 'Unova',
                'Kalos', 'Alola', 'Galar', 'Paldea']

# Shape vocabulary for drawing badges without any copyrighted artwork.
# octagon, droplet, bolt, flower, heart, crescent, star, globe, diamond,
# hex, shield, wing, leaf, flame, gear, snow, ring, fist, spiral, feather

# Each badge: (name, leader, shape, colour, kind, value)
#   kind 'count'   -> value = how many of this region's pokemon to catch
#   kind 'species' -> value = pokemon name (must be caught)
#   kind 'all'     -> value = None, need the whole regional dex
BADGES_BY_REGION = {
    'Kanto': [
        ('Boulder Badge',  'Brock',    'octagon',  (150, 150, 160), 'species', 'geodude'),
        ('Cascade Badge',  'Misty',    'droplet',  (90, 170, 235),  'count',   25),
        ('Thunder Badge',  'Surge',    'bolt',     (245, 200, 40),  'species', 'pikachu'),
        ('Rainbow Badge',  'Erika',    'flower',   (200, 120, 200), 'count',   75),
        ('Soul Badge',     'Koga',     'heart',    (230, 120, 170), 'species', 'gastly'),
        ('Marsh Badge',    'Sabrina',  'crescent', (240, 140, 190), 'species', 'abra'),
        ('Volcano Badge',  'Blaine',   'flame',    (235, 100, 50),  'species', 'charizard'),
        ('Earth Badge',    'Giovanni', 'globe',    (140, 190, 110), 'all',     None),
    ],
    'Johto': [
        ('Zephyr Badge',   'Falkner',  'wing',     (150, 190, 235), 'species', 'hoothoot'),
        ('Hive Badge',     'Bugsy',    'hex',      (190, 200, 60),  'species', 'ledyba'),
        ('Plain Badge',    'Whitney',  'ring',     (230, 190, 200), 'count',   20),
        ('Fog Badge',      'Morty',    'spiral',   (170, 140, 200), 'species', 'misdreavus'),
        ('Storm Badge',    'Chuck',    'fist',     (215, 90, 80),   'count',   40),
        ('Mineral Badge',  'Jasmine',  'gear',     (180, 185, 200), 'species', 'magnemite'),
        ('Glacier Badge',  'Pryce',    'snow',     (150, 215, 230), 'species', 'swinub'),
        ('Rising Badge',   'Clair',    'diamond',  (120, 100, 220), 'all',     None),
    ],
    'Hoenn': [
        ('Stone Badge',    'Roxanne',  'octagon',  (170, 150, 120), 'species', 'geodude'),
        ('Knuckle Badge',  'Brawly',   'fist',     (220, 110, 70),  'count',   25),
        ('Dynamo Badge',   'Wattson',  'bolt',     (245, 205, 60),  'species', 'electrike'),
        ('Heat Badge',     'Flannery', 'flame',    (230, 90, 60),   'species', 'numel'),
        ('Balance Badge',  'Norman',   'ring',     (200, 200, 210), 'count',   60),
        ('Feather Badge',  'Winona',   'feather',  (170, 175, 230), 'species', 'swablu'),
        ('Mind Badge',     'Tate&Liza','crescent', (230, 130, 190), 'species', 'spoink'),
        ('Rain Badge',     'Wallace',  'droplet',  (80, 165, 230),  'all',     None),
    ],
    'Sinnoh': [
        ('Coal Badge',     'Roark',    'octagon',  (130, 130, 140), 'species', 'cranidos'),
        ('Forest Badge',   'Gardenia', 'leaf',     (110, 200, 100), 'count',   25),
        ('Cobble Badge',   'Maylene',  'fist',     (215, 120, 90),  'species', 'riolu'),
        ('Fen Badge',      'Crasher',  'droplet',  (90, 175, 225),  'count',   50),
        ('Relic Badge',    'Fantina',  'spiral',   (180, 130, 210), 'species', 'drifloon'),
        ('Mine Badge',     'Byron',    'shield',   (175, 180, 195), 'species', 'shieldon'),
        ('Icicle Badge',   'Candice',  'snow',     (150, 215, 235), 'species', 'snover'),
        ('Beacon Badge',   'Volkner',  'bolt',     (245, 200, 50),  'all',     None),
    ],
    'Unova': [
        ('Trio Badge',     'Striaton', 'flower',   (200, 160, 200), 'count',   15),
        ('Basic Badge',    'Lenora',   'ring',     (190, 170, 140), 'species', 'lillipup'),
        ('Insect Badge',   'Burgh',    'hex',      (185, 200, 70),  'species', 'sewaddle'),
        ('Bolt Badge',     'Elesa',    'bolt',     (245, 205, 55),  'species', 'blitzle'),
        ('Quake Badge',    'Clay',     'diamond',  (215, 175, 110), 'count',   60),
        ('Jet Badge',      'Skyla',    'wing',     (160, 185, 235), 'species', 'ducklett'),
        ('Freeze Badge',   'Brycen',   'snow',     (145, 210, 230), 'species', 'cubchoo'),
        ('Legend Badge',   'Drayden',  'star',     (125, 95, 215),  'all',     None),
    ],
    'Kalos': [
        ('Bug Badge',      'Viola',    'hex',      (185, 200, 65),  'species', 'scatterbug'),
        ('Cliff Badge',    'Grant',    'octagon',  (160, 145, 125), 'count',   15),
        ('Rumble Badge',   'Korrina',  'fist',     (220, 115, 80),  'species', 'lucario'),
        ('Plant Badge',    'Ramos',    'leaf',     (115, 200, 95),  'species', 'chespin'),
        ('Voltage Badge',  'Clemont',  'bolt',     (245, 205, 55),  'species', 'dedenne'),
        ('Fairy Badge',    'Valerie',  'star',     (240, 165, 200), 'species', 'flabebe'),
        ('Psychic Badge',  'Olympia',  'crescent', (235, 130, 190), 'count',   45),
        ('Iceberg Badge',  'Wulfric',  'snow',     (150, 215, 235), 'all',     None),
    ],
    'Alola': [
        ('Melemele Trial', 'Ilima',    'ring',     (245, 180, 80),  'species', 'yungoos'),
        ('Akala Trial',    'Lana',     'droplet',  (85, 170, 230),  'count',   15),
        ('Fire Trial',     'Kiawe',    'flame',    (230, 95, 55),   'species', 'salandit'),
        ('Grass Trial',    'Mallow',   'leaf',     (110, 200, 100), 'species', 'fomantis'),
        ('Electric Trial', 'Sophocles','bolt',     (245, 205, 55),  'species', 'charjabug'),
        ('Ghost Trial',    'Acerola',  'spiral',   (175, 135, 205), 'species', 'mimikyu'),
        ('Dragon Trial',   'Mina',     'star',     (240, 170, 205), 'count',   50),
        ('Champion Stamp', 'Kukui',    'globe',    (140, 190, 115), 'all',     None),
    ],
    'Galar': [
        ('Grass Badge',    'Milo',     'leaf',     (110, 200, 100), 'species', 'gossifleur'),
        ('Water Badge',    'Nessa',    'droplet',  (85, 170, 230),  'count',   15),
        ('Fire Badge',     'Kabu',     'flame',    (230, 95, 55),   'species', 'sizzlipede'),
        ('Fighting Badge', 'Bea',      'fist',     (220, 115, 80),  'species', 'clobbopus'),
        ('Fairy Badge',    'Opal',     'star',     (240, 165, 200), 'species', 'impidimp'),
        ('Rock Badge',     'Gordie',   'octagon',  (165, 150, 130), 'count',   45),
        ('Ice Badge',      'Melony',   'snow',     (150, 215, 235), 'species', 'snom'),
        ('Dark Badge',     'Piers',    'crescent', (110, 90, 120),  'all',     None),
    ],
    'Paldea': [
        ('Bug Badge',      'Katy',     'hex',      (185, 200, 65),  'species', 'tarountula'),
        ('Grass Badge',    'Brassius', 'leaf',     (110, 200, 100), 'species', 'smoliv'),
        ('Electric Badge', 'Iono',     'bolt',     (245, 205, 55),  'species', 'pawmi'),
        ('Water Badge',    'Kofu',     'droplet',  (85, 170, 230),  'count',   20),
        ('Normal Badge',   'Larry',    'ring',     (195, 190, 175), 'species', 'lechonk'),
        ('Ghost Badge',    'Ryme',     'spiral',   (175, 135, 205), 'species', 'greavard'),
        ('Psychic Badge',  'Tulip',    'crescent', (235, 130, 190), 'count',   55),
        ('Ice Badge',      'Grusha',   'snow',     (150, 215, 235), 'all',     None),
    ],
}


def region_of(pid):
    for r, (lo, hi) in REGION_RANGE.items():
        if lo <= pid <= hi:
            return r
    return 'Paldea'


def region_size(region):
    lo, hi = REGION_RANGE[region]
    return hi - lo + 1


def region_progress(region, caught_ids):
    """(caught_in_region, total_in_region, fraction)"""
    lo, hi = REGION_RANGE[region]
    n = sum(1 for p in caught_ids if lo <= p <= hi)
    total = hi - lo + 1
    return n, total, (n / total if total else 0.0)


def unlock_target(region):
    """How many pokemon you actually need to unlock this region's badges.
    Rounded UP so the number shown is always the true requirement - 60% of
    Kanto is 90.6, so you need 91, not 90."""
    import math as _m
    return _m.ceil(region_size(region) * BADGE_UNLOCK_PCT)


def badges_unlocked(region, caught_ids):
    """True once you've caught unlock_target(region) of the region."""
    n, total, frac = region_progress(region, caught_ids)
    return n >= unlock_target(region)


def badge_earned(region, badge, caught_ids, caught_names):
    """Is this specific badge earned? Requires the region to be unlocked first."""
    if not badges_unlocked(region, caught_ids):
        return False
    name, leader, shape, col, kind, val = badge
    n, total, _ = region_progress(region, caught_ids)
    if kind == 'count':
        return n >= val
    if kind == 'species':
        return val in caught_names
    if kind == 'all':
        return n >= total
    return False


def badge_requirement_text(region, badge):
    name, leader, shape, col, kind, val = badge
    if kind == 'count':
        return 'Catch %d %s Pokemon' % (val, region)
    if kind == 'species':
        return 'Catch %s' % val.title()
    if kind == 'all':
        return 'Complete the %s Pokedex (%d)' % (region, region_size(region))
    return '?'


def all_badges_flat():
    out = []
    for r in REGION_ORDER:
        for b in BADGES_BY_REGION[r]:
            out.append((r, b))
    return out


def earned_badge_count(caught_ids, caught_names):
    n = 0
    for r in REGION_ORDER:
        for b in BADGES_BY_REGION[r]:
            if badge_earned(r, b, caught_ids, caught_names):
                n += 1
    return n


TOTAL_BADGES = sum(len(v) for v in BADGES_BY_REGION.values())


_badge_img_cache = {}


def badge_image(name, size, region=None):
    """Look for a user-supplied badge PNG. None if there isn't one.

    Checks the region subfolder first, then the flat folder:
        badges/kalos/fairy_badge.png     <- region-specific
        badges/fairy_badge.png           <- shared fallback

    Badge names repeat across regions (Kalos and Galar both have a Fairy
    Badge; Galar and Paldea share Grass/Water/Fire/Ice), so the subfolder is
    what keeps them apart. The flat path stays supported so older setups that
    dumped everything in one folder keep working.
    """
    key = (name, size, region)
    if key in _badge_img_cache:
        return _badge_img_cache[key]
    fn = name.lower().replace(' ', '_').replace('&', '') + '.png'
    paths = []
    if region:
        paths.append(os.path.join(BADGE_IMG_DIR, region.lower(), fn))
    paths.append(os.path.join(BADGE_IMG_DIR, fn))
    img = None
    for path in paths:
        if os.path.exists(path):
            try:
                img = pygame.image.load(path).convert_alpha()
                img = pygame.transform.smoothscale(img, (size, size))
                break
            except Exception:
                img = None
    _badge_img_cache[key] = img
    return img


def _poly(cx, cy, r, n, rot=0.0):
    return [(cx + r*math.cos(rot + i*2*math.pi/n),
             cy + r*math.sin(rot + i*2*math.pi/n)) for i in range(n)]


def _star_pts(cx, cy, r, points=5, inner=0.45):
    pts = []
    for i in range(points*2):
        a = -math.pi/2 + i*math.pi/points
        rad = r if i % 2 == 0 else r*inner
        pts.append((cx + rad*math.cos(a), cy + rad*math.sin(a)))
    return pts


def draw_badge(surf, cx, cy, r, shape, colour, earned, name=None, region=None):
    """Draw one badge. Uses a user-supplied PNG if there is one, otherwise
    draws the shape. Grey silhouette when not earned."""
    if name:
        img = badge_image(name, r*2, region)
        if img:
            if not earned:
                img = img.copy()
                dark = pygame.Surface(img.get_size(), pygame.SRCALPHA)
                dark.fill((30, 32, 40, 200))
                img.blit(dark, (0, 0))
            surf.blit(img, (cx-r, cy-r))
            return
    col = colour if earned else (70, 74, 90)
    edge = (20, 20, 24) if earned else (55, 58, 72)
    hl = tuple(min(255, c + 60) for c in col)

    if shape == 'octagon':
        pts = _poly(cx, cy, r, 8, math.pi/8)
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.polygon(surf, hl, _poly(cx, cy, r*0.5, 8, math.pi/8), 2)

    elif shape == 'droplet':
        pygame.draw.circle(surf, col, (cx, cy+int(r*0.2)), int(r*0.75))
        pygame.draw.polygon(surf, col, [(cx, cy-r), (cx-int(r*0.6), cy+int(r*0.3)),
                                        (cx+int(r*0.6), cy+int(r*0.3))])
        pygame.draw.circle(surf, edge, (cx, cy+int(r*0.2)), int(r*0.75), 2)
        pygame.draw.circle(surf, hl, (cx-int(r*0.25), cy), max(2, int(r*0.18)))

    elif shape == 'bolt':
        pts = [(cx+r*0.15, cy-r), (cx-r*0.55, cy+r*0.15), (cx-r*0.05, cy+r*0.15),
               (cx-r*0.25, cy+r), (cx+r*0.6, cy-r*0.2), (cx+r*0.05, cy-r*0.2)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)

    elif shape == 'flower':
        for i in range(5):
            a = -math.pi/2 + i*2*math.pi/5
            px = cx + r*0.55*math.cos(a); py = cy + r*0.55*math.sin(a)
            pygame.draw.circle(surf, col, (int(px), int(py)), int(r*0.42))
            pygame.draw.circle(surf, edge, (int(px), int(py)), int(r*0.42), 2)
        pygame.draw.circle(surf, hl, (cx, cy), int(r*0.3))
        pygame.draw.circle(surf, edge, (cx, cy), int(r*0.3), 2)

    elif shape == 'heart':
        pygame.draw.circle(surf, col, (cx-int(r*0.35), cy-int(r*0.2)), int(r*0.45))
        pygame.draw.circle(surf, col, (cx+int(r*0.35), cy-int(r*0.2)), int(r*0.45))
        pygame.draw.polygon(surf, col, [(cx-r*0.78, cy-r*0.05), (cx+r*0.78, cy-r*0.05),
                                        (cx, cy+r*0.85)])
        pygame.draw.circle(surf, hl, (cx-int(r*0.4), cy-int(r*0.32)), max(2, int(r*0.14)))

    elif shape == 'crescent':
        pygame.draw.circle(surf, col, (cx, cy), r)
        pygame.draw.circle(surf, edge, (cx, cy), r, 2)
        pygame.draw.circle(surf, BG, (cx+int(r*0.42), cy-int(r*0.12)), int(r*0.8))

    elif shape == 'star':
        pts = _star_pts(cx, cy, r)
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)

    elif shape == 'globe':
        pygame.draw.circle(surf, col, (cx, cy), r)
        pygame.draw.circle(surf, edge, (cx, cy), r, 2)
        pygame.draw.ellipse(surf, edge, (cx-r, cy-int(r*0.42), r*2, int(r*0.84)), 2)
        pygame.draw.line(surf, edge, (cx, cy-r), (cx, cy+r), 2)

    elif shape == 'diamond':
        pts = [(cx, cy-r), (cx+r*0.72, cy), (cx, cy+r), (cx-r*0.72, cy)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.line(surf, hl, (cx, cy-int(r*0.7)), (cx-int(r*0.35), cy), 2)

    elif shape == 'hex':
        pts = _poly(cx, cy, r, 6, math.pi/6)
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.polygon(surf, hl, _poly(cx, cy, r*0.45, 6, math.pi/6), 2)

    elif shape == 'shield':
        pts = [(cx-r*0.7, cy-r*0.8), (cx+r*0.7, cy-r*0.8), (cx+r*0.7, cy+r*0.2),
               (cx, cy+r), (cx-r*0.7, cy+r*0.2)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.line(surf, hl, (cx, cy-int(r*0.6)), (cx, cy+int(r*0.6)), 2)

    elif shape == 'wing':
        pts = [(cx-r, cy+r*0.3), (cx-r*0.3, cy-r*0.6), (cx+r*0.2, cy-r*0.2),
               (cx+r, cy-r*0.7), (cx+r*0.5, cy+r*0.5), (cx-r*0.2, cy+r*0.7)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)

    elif shape == 'leaf':
        pts = [(cx, cy-r), (cx+r*0.7, cy-r*0.1), (cx, cy+r), (cx-r*0.7, cy-r*0.1)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.line(surf, edge, (cx, cy-int(r*0.8)), (cx, cy+int(r*0.8)), 2)

    elif shape == 'flame':
        pts = [(cx, cy-r), (cx+r*0.55, cy-r*0.1), (cx+r*0.35, cy+r*0.75),
               (cx, cy+r), (cx-r*0.35, cy+r*0.75), (cx-r*0.55, cy-r*0.1)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        pygame.draw.circle(surf, hl, (cx, cy+int(r*0.3)), max(2, int(r*0.25)))

    elif shape == 'gear':
        pygame.draw.circle(surf, col, (cx, cy), int(r*0.75))
        for i in range(8):
            a = i*2*math.pi/8
            x1 = cx + int(r*0.7*math.cos(a)); y1 = cy + int(r*0.7*math.sin(a))
            x2 = cx + int(r*1.0*math.cos(a)); y2 = cy + int(r*1.0*math.sin(a))
            pygame.draw.line(surf, col, (x1, y1), (x2, y2), max(3, int(r*0.3)))
        pygame.draw.circle(surf, edge, (cx, cy), int(r*0.75), 2)
        pygame.draw.circle(surf, BG, (cx, cy), int(r*0.28))
        pygame.draw.circle(surf, edge, (cx, cy), int(r*0.28), 2)

    elif shape == 'snow':
        for i in range(6):
            a = i*math.pi/3
            x = cx + int(r*math.cos(a)); y = cy + int(r*math.sin(a))
            pygame.draw.line(surf, col, (cx, cy), (x, y), max(2, int(r*0.18)))
            mx = cx + int(r*0.6*math.cos(a)); my = cy + int(r*0.6*math.sin(a))
            for s in (-1, 1):
                bx = mx + int(r*0.3*math.cos(a + s*math.pi/3))
                by = my + int(r*0.3*math.sin(a + s*math.pi/3))
                pygame.draw.line(surf, col, (mx, my), (bx, by), max(1, int(r*0.12)))
        pygame.draw.circle(surf, hl, (cx, cy), max(2, int(r*0.16)))

    elif shape == 'ring':
        pygame.draw.circle(surf, col, (cx, cy), r)
        pygame.draw.circle(surf, edge, (cx, cy), r, 2)
        pygame.draw.circle(surf, BG, (cx, cy), int(r*0.45))
        pygame.draw.circle(surf, edge, (cx, cy), int(r*0.45), 2)

    elif shape == 'fist':
        pygame.draw.rect(surf, col, (cx-int(r*0.7), cy-int(r*0.55),
                                     int(r*1.4), int(r*1.2)), border_radius=int(r*0.3))
        pygame.draw.rect(surf, edge, (cx-int(r*0.7), cy-int(r*0.55),
                                      int(r*1.4), int(r*1.2)), 2, border_radius=int(r*0.3))
        for i in range(3):
            y = cy - int(r*0.25) + i*int(r*0.3)
            pygame.draw.line(surf, edge, (cx-int(r*0.4), y), (cx+int(r*0.4), y), 1)

    elif shape == 'spiral':
        pts = []
        for i in range(40):
            t = i/40.0
            a = t * 4*math.pi
            rad = r*t
            pts.append((cx + rad*math.cos(a), cy + rad*math.sin(a)))
        if len(pts) > 1:
            pygame.draw.lines(surf, col, False, pts, max(2, int(r*0.2)))
        pygame.draw.circle(surf, edge, (cx, cy), r, 2)

    elif shape == 'feather':
        pts = [(cx, cy-r), (cx+r*0.4, cy), (cx+r*0.15, cy+r*0.9), (cx, cy+r),
               (cx-r*0.15, cy+r*0.9), (cx-r*0.4, cy)]
        pygame.draw.polygon(surf, col, pts); pygame.draw.polygon(surf, edge, pts, 2)
        for i in range(4):
            y = cy - int(r*0.5) + i*int(r*0.35)
            pygame.draw.line(surf, edge, (cx, y), (cx+int(r*0.3), y-int(r*0.12)), 1)
            pygame.draw.line(surf, edge, (cx, y), (cx-int(r*0.3), y-int(r*0.12)), 1)

    else:   # fallback
        pygame.draw.circle(surf, col, (cx, cy), r)
        pygame.draw.circle(surf, edge, (cx, cy), r, 2)


TEAMS = ['Red', 'Blue', 'Yellow']
TEAM_COLORS = {'Red':(220,50,50), 'Blue':(60,130,240), 'Yellow':(245,200,40)}

XP_PER_CATCH  = 100    # every catch
XP_FIRST_TIME = 400    # bonus for a species never caught before


def level_from_xp(xp):
    """Level curve: each level N costs 500*N xp. Caps at 50.
    Returns (level, xp_into_level, xp_needed_for_next)."""
    lvl = 1
    while lvl < 50 and xp >= 500 * lvl:
        xp -= 500 * lvl
        lvl += 1
    return lvl, xp, 500 * lvl


class CatchDB:
    """Trainer profiles, catches, XP, favourites and a chronological log.

    Everything is keyed by trainer id, so multiple profiles each keep their own
    catches in one database file.
    """

    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS trainers(
            tid INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, city TEXT, age INTEGER, gender TEXT,
            team TEXT, xp INTEGER DEFAULT 0, created TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS catches(
            tid INTEGER, pid INTEGER, name TEXT, count INTEGER,
            first_caught TEXT, last_caught TEXT,
            PRIMARY KEY (tid, pid))""")
        c.execute("""CREATE TABLE IF NOT EXISTS favourites(
            tid INTEGER, pid INTEGER, PRIMARY KEY (tid, pid))""")
        c.execute("""CREATE TABLE IF NOT EXISTS log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tid INTEGER, pid INTEGER, name TEXT, ts TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            k TEXT PRIMARY KEY, v TEXT)""")
        c.commit()
        self._migrate()
        self.tid = self._load_active()

    def _migrate(self):
        """Old builds had a catches table with no tid column. Move those rows
        onto a 'Trainer' profile so nobody loses their catches."""
        cols = [r[1] for r in self.conn.execute('PRAGMA table_info(catches)')]
        if 'tid' in cols:
            return
        old = self.conn.execute(
            'SELECT pid,name,count,first_caught,last_caught FROM catches').fetchall()
        self.conn.execute('DROP TABLE catches')
        self.conn.execute("""CREATE TABLE catches(
            tid INTEGER, pid INTEGER, name TEXT, count INTEGER,
            first_caught TEXT, last_caught TEXT,
            PRIMARY KEY (tid, pid))""")
        if old:
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            cur = self.conn.execute(
                'INSERT INTO trainers(name,city,age,gender,team,xp,created) '
                "VALUES('Trainer','','','','Red',?,?)",
                (len(old) * (XP_PER_CATCH + XP_FIRST_TIME), now))
            tid = cur.lastrowid
            for pid, name, cnt, f, l in old:
                self.conn.execute('INSERT INTO catches VALUES(?,?,?,?,?,?)',
                                  (tid, pid, name, cnt, f, l))
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES('active_tid',?)",
                              (str(tid),))
        self.conn.commit()

    # ---------- active trainer ----------
    def _load_active(self):
        r = self.conn.execute("SELECT v FROM settings WHERE k='active_tid'").fetchone()
        if r:
            tid = int(r[0])
            if self.conn.execute('SELECT 1 FROM trainers WHERE tid=?', (tid,)).fetchone():
                return tid
        r = self.conn.execute('SELECT tid FROM trainers ORDER BY tid LIMIT 1').fetchone()
        return r[0] if r else None

    def set_active(self, tid):
        self.tid = tid
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES('active_tid',?)",
                          (str(tid),))
        self.conn.commit()

    # ---------- trainers ----------
    def create_trainer(self, name, city, age, gender, team):
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        cur = self.conn.execute(
            'INSERT INTO trainers(name,city,age,gender,team,xp,created) '
            'VALUES(?,?,?,?,?,0,?)', (name, city, age, gender, team, now))
        self.conn.commit()
        tid = cur.lastrowid
        self.set_active(tid)
        return tid

    def update_trainer(self, tid, name, city, age, gender, team):
        self.conn.execute(
            'UPDATE trainers SET name=?,city=?,age=?,gender=?,team=? WHERE tid=?',
            (name, city, age, gender, team, tid))
        self.conn.commit()

    def trainer(self, tid=None):
        tid = self.tid if tid is None else tid
        if tid is None:
            return None
        r = self.conn.execute(
            'SELECT tid,name,city,age,gender,team,xp,created FROM trainers WHERE tid=?',
            (tid,)).fetchone()
        if not r:
            return None
        return {'tid': r[0], 'name': r[1], 'city': r[2], 'age': r[3],
                'gender': r[4], 'team': r[5], 'xp': r[6], 'created': r[7]}

    def all_trainers(self):
        return [{'tid': r[0], 'name': r[1], 'team': r[2], 'xp': r[3]}
                for r in self.conn.execute(
                    'SELECT tid,name,team,xp FROM trainers ORDER BY tid')]

    def delete_trainer(self, tid):
        for t in ('catches', 'favourites', 'log'):
            self.conn.execute('DELETE FROM %s WHERE tid=?' % t, (tid,))
        self.conn.execute('DELETE FROM trainers WHERE tid=?', (tid,))
        self.conn.commit()
        if self.tid == tid:
            self.tid = self._load_active()
            if self.tid is not None:
                self.set_active(self.tid)

    def wipe_current(self):
        """Erase this trainer's catches, favourites, log and XP. Keeps profile."""
        if self.tid is None:
            return
        for t in ('catches', 'favourites', 'log'):
            self.conn.execute('DELETE FROM %s WHERE tid=?' % t, (self.tid,))
        self.conn.execute('UPDATE trainers SET xp=0 WHERE tid=?', (self.tid,))
        self.conn.commit()

    def wipe_everything(self):
        for t in ('catches', 'favourites', 'log', 'trainers', 'settings'):
            self.conn.execute('DELETE FROM %s' % t)
        self.conn.commit()
        self.tid = None

    # ---------- catches ----------
    def record(self, pid, name):
        """Record a catch. Returns (xp_gained, leveled_up, new_badges)."""
        if self.tid is None:
            return (0, False, [])
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        before_lvl = level_from_xp(self.trainer()['xp'])[0]
        before_badges = self.earned_badges()

        row = self.conn.execute('SELECT count FROM catches WHERE tid=? AND pid=?',
                                (self.tid, pid)).fetchone()
        if row:
            self.conn.execute(
                'UPDATE catches SET count=count+1, last_caught=? WHERE tid=? AND pid=?',
                (now, self.tid, pid))
            xp = XP_PER_CATCH
        else:
            self.conn.execute('INSERT INTO catches VALUES(?,?,?,1,?,?)',
                              (self.tid, pid, name, now, now))
            xp = XP_PER_CATCH + XP_FIRST_TIME
        self.conn.execute('INSERT INTO log(tid,pid,name,ts) VALUES(?,?,?,?)',
                          (self.tid, pid, name, now))
        self.conn.execute('UPDATE trainers SET xp=xp+? WHERE tid=?', (xp, self.tid))
        self.conn.commit()

        after_lvl = level_from_xp(self.trainer()['xp'])[0]
        gained = self.earned_badges() - before_badges
        new_badges = ['%s (%s)' % (bn, rg) for rg, bn in sorted(gained)]
        return (xp, after_lvl > before_lvl, new_badges)

    def get(self, pid):
        if self.tid is None:
            return None
        r = self.conn.execute(
            'SELECT pid,name,count,first_caught,last_caught FROM catches '
            'WHERE tid=? AND pid=?', (self.tid, pid)).fetchone()
        if not r:
            return None
        return {'pid': r[0], 'name': r[1], 'count': r[2], 'first': r[3], 'last': r[4]}

    def all_caught(self, sort='dex'):
        """sort: 'dex' | 'count' | 'date'"""
        if self.tid is None:
            return []
        order = {'dex': 'pid ASC',
                 'count': 'count DESC, pid ASC',
                 'date': 'last_caught DESC'}.get(sort, 'pid ASC')
        rows = self.conn.execute(
            'SELECT pid,name,count,first_caught,last_caught FROM catches '
            'WHERE tid=? ORDER BY ' + order, (self.tid,)).fetchall()
        return [{'pid': r[0], 'name': r[1], 'count': r[2],
                 'first': r[3], 'last': r[4]} for r in rows]

    def stats(self):
        caught = self.all_caught()
        total = sum(c['count'] for c in caught)
        most = max(caught, key=lambda c: c['count'], default=None)
        latest = max(caught, key=lambda c: c['last'], default=None)
        return {'unique': len(caught), 'total': total,
                'most': most['name'] if most else '-',
                'latest': latest['name'] if latest else '-'}

    # ---------- favourites ----------
    def is_fav(self, pid):
        if self.tid is None:
            return False
        return self.conn.execute('SELECT 1 FROM favourites WHERE tid=? AND pid=?',
                                 (self.tid, pid)).fetchone() is not None

    def toggle_fav(self, pid):
        if self.tid is None:
            return False
        if self.is_fav(pid):
            self.conn.execute('DELETE FROM favourites WHERE tid=? AND pid=?',
                              (self.tid, pid))
            self.conn.commit()
            return False
        self.conn.execute('INSERT INTO favourites VALUES(?,?)', (self.tid, pid))
        self.conn.commit()
        return True

    def all_favs(self):
        if self.tid is None:
            return []
        return [r[0] for r in self.conn.execute(
            'SELECT pid FROM favourites WHERE tid=? ORDER BY pid', (self.tid,))]

    # ---------- log ----------
    def recent_log(self, limit=200):
        if self.tid is None:
            return []
        return [{'pid': r[0], 'name': r[1], 'ts': r[2]} for r in self.conn.execute(
            'SELECT pid,name,ts FROM log WHERE tid=? ORDER BY id DESC LIMIT ?',
            (self.tid, limit))]

    # ---------- badges ----------
    def caught_sets(self):
        """(set of ids, set of names) - what the badge rules check against."""
        rows = self.all_caught()
        return {c['pid'] for c in rows}, {c['name'] for c in rows}

    def earned_badges(self):
        """Set of (region, badge_name) currently earned."""
        ids, names = self.caught_sets()
        out = set()
        for r in REGION_ORDER:
            if not badges_unlocked(r, ids):
                continue
            for b in BADGES_BY_REGION[r]:
                if badge_earned(r, b, ids, names):
                    out.add((r, b[0]))
        return out

    def badge_count(self):
        return len(self.earned_badges())

    def latest_badge(self):
        """The most recently earned badge, as (region, badge_tuple).

        Badges aren't stored - they're derived from what you've caught. So we
        replay the catch log oldest-first, recomputing after each catch, and
        keep whichever badge appeared last. None if you have no badges.
        """
        earned_now = self.earned_badges()
        if not earned_now:
            return None
        if self.tid is None:
            return None
        rows = self.conn.execute(
            'SELECT pid, name FROM log WHERE tid=? ORDER BY id ASC',
            (self.tid,)).fetchall()
        ids, names = set(), set()
        seen = set()
        last = None
        for pid, nm in rows:
            ids.add(pid); names.add(nm)
            for r in REGION_ORDER:
                if not badges_unlocked(r, ids):
                    continue
                for b in BADGES_BY_REGION[r]:
                    key = (r, b[0])
                    if key in seen:
                        continue
                    if badge_earned(r, b, ids, names):
                        seen.add(key)
                        last = (r, b)
        if last:
            return last
        # fallback: log is empty but badges exist (migrated data)
        r, bn = sorted(earned_now)[0]
        for b in BADGES_BY_REGION[r]:
            if b[0] == bn:
                return (r, b)
        return None


# ─── Recognition (UNCHANGED logic) ────────────────────────
def upload_image(path):
    """Push the capture into a public GitHub repo and return its raw URL.

    Google Lens only accepts publicly-hosted image URLs - SerpApi has no file
    upload. Every free anonymous host we tried has since blocked us:
      tmpfiles.org  - Lens silently gets 0 matches
      catbox.moe    - same
      0x0.st        - unreachable from this network
      imgur         - blocked in India
      litterbox     - now returns 403 to any upload
    A GitHub repo you own doesn't have that problem: you're an authenticated
    user with your own token, not an anonymous uploader they need to rate
    limit. raw.githubusercontent.com serves the file publicly, which is all
    Lens needs.

    Old captures are deleted after upload so the repo doesn't fill up.
    """
    import base64
    with open(path, 'rb') as f:
        content = base64.b64encode(f.read()).decode()

    fname = f'capture_{int(time.time())}.jpg'
    api = (f'https://api.github.com/repos/{GH_USER}/{GH_REPO}'
           f'/contents/{GH_DIR}/{fname}')
    hdr = {'Authorization': f'token {GH_TOKEN}',
           'Accept': 'application/vnd.github+json'}

    last = None
    for attempt in range(3):
        try:
            r = requests.put(api, headers=hdr,
                             json={'message': 'capture', 'content': content},
                             timeout=90)
            r.raise_for_status()
            break
        except Exception as e:
            last = e
            time.sleep(2)
    else:
        raise last

    threading.Thread(target=_prune_captures, daemon=True).start()

    time.sleep(2)   # give the CDN a moment before Lens fetches it
    return (f'https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}'
            f'/main/{GH_DIR}/{fname}')


def _prune_captures(keep=20):
    """Delete old captures so the repo doesn't grow forever. Runs in the
    background - a failure here must never break a scan."""
    try:
        hdr = {'Authorization': f'token {GH_TOKEN}',
               'Accept': 'application/vnd.github+json'}
        api = f'https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{GH_DIR}'
        r = requests.get(api, headers=hdr, timeout=30)
        if r.status_code != 200:
            return
        files = [f for f in r.json()
                 if f['name'].startswith('capture_') and f['name'].endswith('.jpg')]
        files.sort(key=lambda f: f['name'])
        for f in files[:-keep]:
            requests.delete(f'{api}/{f["name"]}', headers=hdr, timeout=30,
                            json={'message': 'prune', 'sha': f['sha']})
    except Exception:
        pass


def search_image(url):
    params={'engine':'google_lens','url':url,'api_key':SERP_API_KEY}
    results=GoogleSearch(params).get_dict()
    return [i.get('title','') for i in results.get('visual_matches',[]) if i.get('title')]

def extract_candidates(titles):
    words=[]
    for t in titles: words.extend(t.lower().split())
    freq=Counter(words)
    stop={'the','a','an','of','in','on','at','to','for','and','or','with','is','it','this','that','pokemon','pokémon','#'}
    return [w for w,_ in freq.most_common(20) if w not in stop and len(w)>2]

def match_pokemon(cands, db):
    names=list(db.keys())
    for c in cands:
        r=process.extractOne(c, names, scorer=fuzz.WRatio, score_cutoff=SCORE_CUTOFF)
        if r:
            e=dict(db[r[0]]); e['name']=r[0]; return e
    return None

# ─── Audio ────────────────────────────────────────────────
_MUTED=[False]   # module-level so speak/play_ting can see it without self

def set_muted(m):
    _MUTED[0]=bool(m)

# The currently-playing audio process, so mute can kill it instantly instead
# of waiting for the sentence to finish. A lock guards it because speak() runs
# in the identify() thread while the main loop calls stop_audio() on mute.
_audio_proc = [None]
_audio_lock = threading.Lock()

def _led(state):
    """Tell the ESP32's WS2812 to blink (audio on) or stop (audio off), by
    writing to a file key_serial.py forwards over serial - the app can't open
    the serial port itself since key_serial.py holds it. state: True/False.
    Best-effort: a failure here must never break audio."""
    try:
        with open('/tmp/led_trigger', 'w') as f:
            f.write('1' if state else '0')
    except Exception:
        pass

def stop_audio():
    """Kill whatever is speaking right now. Called the instant mute is pressed."""
    with _audio_lock:
        p = _audio_proc[0]
        if p and p.poll() is None:
            try:
                p.kill()          # SIGKILL - espeak/aplay stop immediately
            except Exception:
                pass
        _audio_proc[0] = None
    # aplay can linger holding the device; make sure it's gone
    subprocess.run(['pkill', '-9', 'aplay'], stderr=subprocess.DEVNULL)
    subprocess.run(['pkill', '-9', 'espeak'], stderr=subprocess.DEVNULL)
    _led(False)   # audio stopped - stop the blink

def play_ting():
    if _MUTED[0]: return
    freq=2000; dur=0.4; sr=44100; s=[]
    for i in range(int(sr*dur)):
        fade=1.0-(i/(sr*dur))
        s.append(struct.pack('<h', int(32767*fade*math.sin(2*math.pi*freq*i/sr))))
    with wave.open('/tmp/ting.wav','w') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes(b''.join(s))
    p = subprocess.Popen(['aplay','-D',AUDIO_DEV,'/tmp/ting.wav'], stderr=subprocess.DEVNULL)
    with _audio_lock:
        _audio_proc[0] = p
    _led(True)
    p.wait()
    _led(False)

def speak(text):
    if _MUTED[0]: return
    # Popen (not run) so the process handle is stored and mute can kill it
    # mid-sentence. The shell pipe means we track the shell; killing it takes
    # the espeak|aplay children with it, and stop_audio() pkills any strays.
    p = subprocess.Popen(f'espeak -a 200 "{text}" --stdout | aplay -D {AUDIO_DEV}',
                         shell=True, stderr=subprocess.DEVNULL)
    with _audio_lock:
        _audio_proc[0] = p
    _led(True)     # blink blue while speaking
    p.wait()
    _led(False)    # done - stop the blink

# ═══════════ PHYAI - on-device Pokemon recognition ═══════════
# Runs entirely on shimi: no wifi, no API, no per-scan cost, instant. The
# tradeoff, explained to the user up front (see PHYAI_MANUAL): it only knows
# the Pokemon it was trained on - four, for now - versus Reverse Image
# Version's full 1025 via Google Lens. Two modes, two strengths.

_phyai_interpreter = [None]
_phyai_labels = [None]

_phyai_last_error = ['']

def phyai_load():
    """Load the TFLite model once and cache it. Returns True if ready.
    Safe to call every time PhyAI opens - a no-op after the first success.

    Three import paths are tried, in order of preference: tflite_runtime
    (tiny, but stopped getting wheels for some platforms), ai_edge_litert
    (Google's current replacement for it), then full tensorflow's bundled
    interpreter as a last resort (works everywhere but is a much bigger
    install - avoid it on this board's limited storage if the others work).
    Any failures are kept in _phyai_last_error so the UI can show *why*
    loading failed instead of a bare "couldn't load the model."
    """
    if _phyai_interpreter[0] is not None:
        return True
    interp = None
    errors = []
    try:
        import tflite_runtime.interpreter as tflite
        interp = tflite.Interpreter(model_path=PHYAI_MODEL)
    except Exception as e:
        errors.append(f'tflite_runtime: {e}')
    if interp is None:
        try:
            from ai_edge_litert.interpreter import Interpreter as LiteRTInterpreter
            interp = LiteRTInterpreter(model_path=PHYAI_MODEL)
        except Exception as e:
            errors.append(f'ai_edge_litert: {e}')
    if interp is None:
        try:
            interp = tf_lite_interpreter_fallback()
        except Exception as e:
            errors.append(f'tensorflow: {e}')
    if interp is None:
        _phyai_last_error[0] = ' | '.join(errors)
        return False
    try:
        interp.allocate_tensors()
        labels = open(PHYAI_LABELS).read().strip().splitlines()
        _phyai_interpreter[0] = interp
        _phyai_labels[0] = labels
        return True
    except Exception as e:
        _phyai_last_error[0] = f'model/labels: {e}'
        return False

def tf_lite_interpreter_fallback():
    import tensorflow as tf
    return tf.lite.Interpreter(model_path=PHYAI_MODEL)

def phyai_classify(frame_bgr):
    """One BGR camera frame (as OpenCV gives us) -> (label, confidence) or
    (None, 0.0) if the model isn't loaded, or confidence is below threshold.
    """
    interp = _phyai_interpreter[0]
    if interp is None:
        return (None, 0.0)
    try:
        img = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (PHYAI_SIZE, PHYAI_SIZE))
        img = img.astype('uint8')[None, ...]   # add batch dim

        inp = interp.get_input_details()[0]
        out = interp.get_output_details()[0]
        interp.set_tensor(inp['index'], img)
        interp.invoke()
        result = interp.get_tensor(out['index'])[0]

        # the model is int8-quantized: 0-255 stands in for a 0.0-1.0 probability
        idx = int(result.argmax())
        conf = float(result[idx]) / 255.0
        label = _phyai_labels[0][idx] if idx < len(_phyai_labels[0]) else '?'

        if conf < PHYAI_CONF_THRESHOLD:
            return (None, conf)
        return (label, conf)
    except Exception:
        return (None, 0.0)


# ═══════════ PROFESSOR OAK - voice assistant backend ═══════════
# Three pieces, each isolated so a failure in one shows a message rather than
# crashing the app:
#   oak_record_start/stop  - arecord to a wav (local, free)
#   oak_transcribe         - whisper.cpp on that wav (local, free)
#   oak_ask                - Claude Haiku answers in Oak's voice (API, paid)

_oak_rec = [None]   # the running arecord process, if any

def oak_record_start():
    """Begin recording the mic to a wav. Returns True if it started."""
    try:
        _oak_rec[0] = subprocess.Popen(
            ['arecord', '-D', MIC_DEV, '-f', 'S16_LE', '-r', '16000',
             '-c', '1', OAK_WAV],
            stderr=subprocess.DEVNULL)
        return True
    except Exception:
        _oak_rec[0] = None
        return False

def oak_record_stop():
    """Stop recording. Returns True if there's a usable wav.

    arecord must be stopped with SIGINT (like Ctrl-C), not SIGTERM/SIGKILL:
    on SIGINT it finalizes the WAV header (writes the real sample count)
    before exiting. Killed any other way, the header is left corrupt - the
    file reports ~2^30 samples and whisper reads only noise. That was the
    "YOU SAID: (empty)" bug.
    """
    import signal, wave
    p = _oak_rec[0]
    if not p:
        return False
    try:
        p.send_signal(signal.SIGINT)
        p.wait(timeout=3)
    except Exception:
        try: p.kill()
        except Exception: pass
    _oak_rec[0] = None
    return _fix_wav_header(OAK_WAV)

def _fix_wav_header(path):
    """arecord interrupted by SIGINT leaves the WAV header claiming ~2^30
    frames - it never rewrites the real count. The audio bytes are all there;
    only the header lies. So we recompute the sizes from the actual file
    length and patch the two length fields in place. Returns True if the file
    now holds a sane amount of audio.

    WAV layout: bytes 4-7 = RIFF chunk size (filesize-8), bytes 40-43 = data
    chunk size (filesize-44 for a standard 44-byte header).
    """
    import struct
    try:
        total = os.path.getsize(path)
        if total <= 44:
            return False
        data_size = total - 44
        with open(path, 'r+b') as f:
            f.seek(4);  f.write(struct.pack('<I', total - 8))
            f.seek(40); f.write(struct.pack('<I', data_size))
        # 16-bit mono: frames = data_size / 2
        frames = data_size // 2
        return 0 < frames < 16000*120      # >0 and under 2 minutes
    except Exception:
        return os.path.exists(path)

def oak_transcribe():
    """whisper.cpp -> text. Empty string on any failure."""
    try:
        out = subprocess.run(
            [WHISPER_BIN, '-m', WHISPER_MODEL, '-f', OAK_WAV, '-nt'],
            capture_output=True, text=True, timeout=60)
        text = out.stdout.strip()
        text = re.sub(r'\[.*?\]', '', text).strip()   # strip any [timestamps]
        return text
    except Exception:
        return ''

OAK_DEVICE_CONTEXT = (
    "You are built into a real handheld Pokedex device with two ways to "
    "identify Pokemon: 'Reverse Image Version' uses the camera and Google "
    "Lens over the internet to recognize any of the 1025 Pokemon, and this "
    "is the mode that actually counts toward the trainer's catches, XP, and "
    "region/badge progress. 'PhyAI Challenge' is a separate on-device demo "
    "mode - a small trained model that recognizes only four Pokemon "
    "(Bulbasaur, Charizard, Pikachu, Squirtle) with no internet needed, but "
    "it's just a demo and does NOT count toward catches or progress. If "
    "asked how the device works, explain both modes accurately."
)

# Progress questions only need trainer-progress context injected - most Oak
# questions don't, and skipping it there saves tokens on every question that
# isn't about catches/badges/regions. This is a plain keyword check, not a
# second API call, which would cost more than the tokens it saves.
PROGRESS_KEYWORDS = (
    'how many', 'left', 'remaining', 'unlock', 'badge', 'progress',
    'catch next', 'what should i catch', 'need to catch', 'missing',
    'region', 'caught', 'my dex', 'my pokedex', 'level', 'xp'
)

def oak_is_progress_question(question):
    q = question.lower()
    return any(k in q for k in PROGRESS_KEYWORDS)

def oak_progress_summary(app):
    """A compact, plain-text briefing on the trainer's actual progress -
    caught count, per-region status, and up to 3 suggested next catches for
    the nearest locked region. Built from real data (catchdb + the region
    tables), never invented, so Claude answers from ground truth rather than
    guessing at numbers.
    """
    try:
        caught = app.catchdb.all_caught()
        caught_ids = {c['pid'] for c in caught}
        stats = app.catchdb.stats()
        t = app.catchdb.trainer()
        lvl = level_from_xp(t['xp'])[0] if t else 1

        lines = [f"Trainer level {lvl}. {stats['unique']} unique Pokemon caught, "
                 f"{stats['total']} total catches."]

        # Only from Reverse Image Version - PhyAI catches don't count, so
        # this is already accurate without needing to filter anything extra.
        nearest_locked = None
        for r in REGION_ORDER:
            n, total, frac = region_progress(r, caught_ids)
            target = unlock_target(r)
            unlocked = badges_unlocked(r, caught_ids)
            status = "UNLOCKED" if unlocked else f"needs {target}, has {n}"
            lines.append(f"{r}: {n}/{total} caught ({status})")
            if not unlocked and nearest_locked is None:
                nearest_locked = r

        if nearest_locked:
            need = unlock_target(nearest_locked) - region_progress(nearest_locked, caught_ids)[0]
            missing_ids = [pid for pid in app.regions[nearest_locked] if pid not in caught_ids]
            suggestions = [app.by_id[pid]['name'].title() for pid in missing_ids[:3]]
            lines.append(f"Nearest region to unlock next: {nearest_locked}, "
                        f"needs {need} more. Suggest catching: {', '.join(suggestions)}.")
        else:
            lines.append("All regions are unlocked.")

        return '\n'.join(lines)
    except Exception:
        return ""

def _oak_trainer_blurb(trainer):
    """A small always-on line of who's talking to Oak - name, city, age,
    gender, team, level. Cheap (well under 100 tokens) so it's worth
    including on every question, unlike the bigger progress data below."""
    if not trainer:
        return "The trainer hasn't set up a profile yet."
    lvl = level_from_xp(trainer.get('xp', 0))[0]
    bits = [f"Name: {trainer.get('name') or 'unknown'}"]
    if trainer.get('city'):   bits.append(f"from {trainer['city']}")
    if trainer.get('age'):    bits.append(f"age {trainer['age']}")
    if trainer.get('gender'): bits.append(trainer['gender'])
    if trainer.get('team'):   bits.append(f"Team {trainer['team']}")
    bits.append(f"Level {lvl}")
    return ', '.join(bits) + '.'

def _oak_system(trainer, progress_context=None):
    """Oak's persona. Answers everything straight - no in-character dodging
    of "real world" topics like politics or current events - while keeping
    the warm Professor Oak voice. Ordinary safety limits still apply; that's
    Claude's own judgement, not something this prompt controls or should try
    to override.

    trainer is the full profile dict from CatchDB.trainer() (name, city, age,
    gender, team, xp) - small, so it's always included, not gated like
    progress_context is.

    progress_context, when given, is the trainer's real catch/region data -
    only included when the question looks progress-related, to keep token
    cost down on ordinary questions.
    """
    name = (trainer.get('name') if trainer else None) or "trainer"
    blurb = _oak_trainer_blurb(trainer)
    base = (
        f"You are Professor Oak from the Pokemon world, acting as a "
        f"knowledgeable, friendly voice assistant built into a real Pokedex "
        f"device. The person talking to you is a trainer named {name} - "
        f"address them by name sometimes, naturally, not every reply. Here "
        f"is their profile, for natural personal touches when it fits (don't "
        f"force it into every reply): {blurb}\n\n"
        f"Answer ANY question directly and accurately, whether it's about "
        f"Pokemon or anything else - current events, general knowledge, "
        f"maths, whatever they ask. Don't deflect real-world questions as "
        f"outside your expertise; just answer them, in your own warm and "
        f"encouraging voice. Keep answers to 2-3 short sentences, since they "
        f"are read aloud and shown in a small speech bubble. If you "
        f"genuinely don't know something, say so briefly rather than "
        f"making it up.\n\n{OAK_DEVICE_CONTEXT}"
    )
    if progress_context:
        base += (
            f"\n\nThe trainer just asked something about their own progress. "
            f"Here is their real, current data - use it to answer specifically "
            f"and accurately. If suggesting what to catch next, name at most "
            f"2-3 Pokemon, not a full list - keep it brief.\n\n{progress_context}"
        )
    return base

def oak_ask(question, history, trainer=None, progress_context=None):
    """Ask Claude, in Oak's voice. history is a list of {'role','content'}
    from earlier in this session. trainer is the full profile dict (or None).
    Returns (answer_text, new_history).

    Retries up to 3 times on failure. The wifi on this device drops packets
    intermittently (full signal, but the power rail disrupts the radio), so a
    single request often times out even though the connection basically works.
    Retrying turns most of those transient failures into success instead of a
    "couldn't reach my knowledge banks" message.
    """
    if not CLAUDE_KEY:
        return ("My assistant circuits aren't connected yet - no API key was "
                "found on the device.", history)
    msgs = history + [{'role': 'user', 'content': question}]
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': CLAUDE_KEY,
                         'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5',
                      'max_tokens': 150,
                      'system': _oak_system(trainer, progress_context),
                      'messages': msgs},
                timeout=20)
            r.raise_for_status()
            answer = r.json()['content'][0]['text'].strip()
            new_hist = msgs + [{'role': 'assistant', 'content': answer}]
            # keep only the last 3 exchanges (6 messages) so tokens stay small
            new_hist = new_hist[-6:]
            return (answer, new_hist)
        except Exception as e:
            last_err = e
            _oak_last_error[0] = f'{type(e).__name__}: {e}'
            print('OAK ERROR:', type(e).__name__, e)
            time.sleep(1.5)   # brief pause before retry - lets a blip pass
    # all attempts failed
    return ("Sorry, I couldn't reach my knowledge banks just now - the "
            "connection dropped. Try asking again.", history)

_oak_last_error = ['']


# ─── Helpers ──────────────────────────────────────────────
_img_cache={}
def poke_img(pid, size):
    key=f'{pid}_{size}'
    if key not in _img_cache:
        path=f'{UI_IMG_DIR}/{pid}.png'
        if os.path.exists(path):
            img=pygame.image.load(path).convert_alpha()
            _img_cache[key]=pygame.transform.smoothscale(img,(size,size))
        else:
            _img_cache[key]=None
    return _img_cache[key]

def trig(name):
    p=TRIG[name]
    if os.path.exists(p):
        os.remove(p); return True
    return False

def clear_trigs():
    for p in TRIG.values():
        if os.path.exists(p): os.remove(p)

# ─── Screen states ────────────────────────────────────────
MAIN_MENU=0; RIV_MENU=1; GAMEPLAY=2; BROWSER=3; DETAIL=4; CAUGHT=5; PHYAI=6
TRAINER=7; TRAINER_NEW=8; TRAINER_LIST=9; DATA_MENU=11
MANUAL=16; HELP_MENU=17; OAK=18; MORE_GAMES=19
GAME_FLAPPY=20; GAME_TETRIS=21; GAME_SNAKE=22
SEARCH=12; LOG=13; FAVS=14; CONFIRM=15

def find_camera():
    """Auto-detect the USB camera. Device number shifts between reboots, so
    pick the Hy- device that actually returns a frame."""
    import glob, subprocess
    cands = []
    for dev in sorted(glob.glob('/dev/video*')):
        try:
            out = subprocess.run(['v4l2-ctl','-d',dev,'--all'],
                capture_output=True, text=True, timeout=5).stdout.lower()
            if 'hy-' in out and 'video capture' in out:
                cands.append(dev)
        except Exception:
            continue
    for dev in cands:
        try:
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                return dev
        except Exception:
            continue
    return cands[0] if cands else '/dev/video0'


def _usb_audio_cards():
    """{card_number: usb_path} for every USB sound card, from /proc/asound/cards."""
    import re
    cards = {}
    try:
        txt = open('/proc/asound/cards').read()
        for m in re.finditer(r'^\s*(\d+)\s+\[.*?\].*?USB-Audio.*?(?:\n.*?)?at usb-[^,]*?-([\d.]+)',
                             txt, re.MULTILINE):
            cards[int(m.group(1))] = m.group(2)
    except Exception:
        pass
    return cards

def _find_usb_card():
    """The USB sound adapter as card number N, or None.

    This build uses ONE C-Media USB dongle for both mic (its input jack) and
    speaker (its output jack), so the same card serves both. It renumbers
    between reboots/reconnects, so we find it fresh each call rather than
    trusting a fixed number. If more than one USB card is present we take the
    lowest-numbered one.
    """
    cards = _usb_audio_cards()
    if cards:
        return sorted(cards)[0]
    return None

def find_audio():
    """Speaker device 'plughw:N,0' - the USB dongle, else the board's card 0."""
    n = _find_usb_card()
    return f'plughw:{n},0' if n is not None else 'plughw:0,0'

def find_mic():
    """Mic device 'plughw:N,0' - same USB dongle as the speaker."""
    n = _find_usb_card()
    return f'plughw:{n},0' if n is not None else 'plughw:0,0'

AUDIO_DEV = find_audio()
MIC_DEV   = find_mic()


_ball_cache = {}


def _render_ball_frame(size, yaw, pitch=0.0):
    """One frame of the ball, lit and rotated. Returns an RGBA surface.

    yaw   - rotation about the vertical axis (the ball spinning)
    pitch - tilt of the band toward/away from the viewer
    """
    r = size / 2.0
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    px = pygame.PixelArray(surf)

    # light coming from the upper left, slightly toward the viewer
    lx, ly, lz = -0.55, -0.62, 0.56
    ln = math.sqrt(lx*lx + ly*ly + lz*lz)
    lx, ly, lz = lx/ln, ly/ln, lz/ln

    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    cp_, sp_ = math.cos(pitch), math.sin(pitch)

    RED   = (222, 48, 40)
    WHITE = (242, 242, 246)
    BLACK = (24, 24, 30)

    for iy in range(size):
        # y in [-1, 1] across the sphere
        ny = (iy - r + 0.5) / r
        for ix in range(size):
            nx = (ix - r + 0.5) / r
            d2 = nx*nx + ny*ny
            if d2 > 1.0:
                continue                      # outside the circle
            nz = math.sqrt(1.0 - d2)          # front hemisphere

            # rotate the surface point into the ball's own frame so the
            # texture turns with it
            # yaw about Y
            bx = nx*cy_ + nz*sy_
            bz = -nx*sy_ + nz*cy_
            by = ny
            # pitch about X
            by2 = by*cp_ - bz*sp_
            bz2 = by*sp_ + bz*cp_
            by, bz = by2, bz2

            # texture: red top, white bottom, black band across the middle.
            # screen y grows downward, so the TOP of the ball is by < 0.
            if abs(by) < 0.13:
                base = BLACK
            elif by < 0:
                base = RED
            else:
                base = WHITE

            # The button sits on the band, and rides around the ball as it
            # spins - so it's centred where the band meets the front face.
            # Distance from that point, measured on the sphere surface.
            btn_d = math.sqrt(bx*bx + by*by*1.0)
            if bz > 0.0 and btn_d < 0.26:
                base = BLACK if btn_d > 0.19 else (250, 250, 252)

            # lambert, plus a weak fill light from below-right so the white
            # half doesn't read as dark grey. Real product shots do the same
            # thing with a bounce card.
            lam = max(0.0, nx*lx + ny*ly + nz*lz)
            fill = max(0.0, nx*0.4 + ny*0.5 + nz*0.5) * 0.22
            shade = 0.42 + 0.58*lam + fill

            # specular highlight
            # reflect the light about the normal, compare to the view vector
            rdot = 2.0*lam
            rx_, ry_, rz_ = rdot*nx - lx, rdot*ny - ly, rdot*nz - lz
            spec = max(0.0, rz_) ** 28
            spec *= 0.9

            # rim darkening - the edge of a sphere falls away from the eye
            rim = 0.55 + 0.45*nz

            cr = base[0]*shade*rim + 255*spec
            cg = base[1]*shade*rim + 255*spec
            cb = base[2]*shade*rim + 255*spec

            # antialias the silhouette
            edge = (1.0 - d2)
            a = 255 if edge > 0.02 else int(255 * (edge/0.02))

            px[ix, iy] = (min(255,int(cr)), min(255,int(cg)),
                          min(255,int(cb)), max(0, min(255, a)))
    del px
    return surf


def ball_frames(size, steps=24):
    """All rotation frames at this size. Rendered once, then cached."""
    key = (size, steps)
    if key in _ball_cache:
        return _ball_cache[key]
    frames = [_render_ball_frame(size, i*2*math.pi/steps)
              for i in range(steps)]
    _ball_cache[key] = frames
    return frames


def draw_ball3d(surf, cx, cy, size, spin, shadow=False):
    """Blit the right pre-rendered frame. Cheap - the maths already happened."""
    frames = ball_frames(size)
    f = frames[int(spin / (2*math.pi) * len(frames)) % len(frames)]
    if shadow:
        sh = pygame.Surface((size, size//3), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0, 0, 0, 90), (0, 0, size, size//3))
        surf.blit(sh, (cx - size//2, cy + size//2 - size//8))
    surf.blit(f, (cx - size//2, cy - size//2))


def draw_throw_ball(surf, x, y, r, spin, squash=1.0):
    """A pokeball in flight - spins as it travels."""
    import math as _m
    RED_=(220,50,50); WH_=(245,245,250); BK_=(20,20,24)
    rx = max(2, int(r*squash)); ry = r
    box = pygame.Rect(int(x-rx), int(y-ry), rx*2, ry*2)
    # the band tilts as the ball spins, which reads as rotation
    band_dy = _m.sin(spin) * ry * 0.8
    prev = surf.get_clip()
    surf.set_clip(pygame.Rect(int(x-rx), int(y-ry), rx*2, int(ry+band_dy)))
    pygame.draw.ellipse(surf, RED_, box)
    surf.set_clip(pygame.Rect(int(x-rx), int(y+band_dy), rx*2, int(ry-band_dy)+ry))
    pygame.draw.ellipse(surf, WH_, box)
    surf.set_clip(prev)
    pygame.draw.ellipse(surf, BK_, box, 2)
    pygame.draw.line(surf, BK_, (x-rx, y+band_dy), (x+rx, y+band_dy), 3)
    br = max(2, int(r*0.3))
    pygame.draw.circle(surf, WH_, (int(x), int(y+band_dy)), br)
    pygame.draw.circle(surf, BK_, (int(x), int(y+band_dy)), br, 2)


def draw_burst(surf, cx, cy, r, t):
    """Ball opens - white flash and rays."""
    import math as _m
    alpha = max(0, 255 - int(t*400))
    if alpha <= 0:
        return
    flash = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    pygame.draw.circle(flash, (255,255,255,alpha), (int(cx),int(cy)), int(r + t*300))
    for i in range(8):
        a = i*_m.pi/4 + t*2
        x2 = cx + _m.cos(a)*(r + t*420)
        y2 = cy + _m.sin(a)*(r + t*420)
        pygame.draw.line(flash, (255,240,150,alpha), (cx,cy), (x2,y2), 4)
    surf.blit(flash, (0,0))


def draw_star(surf, cx, cy, r, filled):
    """Favourite marker."""
    import math as _m
    pts = []
    for i in range(10):
        a = _m.pi/2 + i * _m.pi/5
        rad = r if i % 2 == 0 else r*0.45
        pts.append((cx + rad*_m.cos(a), cy - rad*_m.sin(a)))
    if filled:
        pygame.draw.polygon(surf, (245,200,40), pts)
        pygame.draw.polygon(surf, (20,20,24), pts, 1)
    else:
        pygame.draw.polygon(surf, (110,116,134), pts, 1)


def draw_pokeball(surf, cx, cy, r, t):
    """Spinning pokeball cursor. Squashes horizontally over time t to read as
    rotation, since a flat circle can't actually spin."""
    import math as _m
    sq = abs(_m.cos(t * 3.0))              # 1 -> 0 -> 1
    rx = max(2, int(r * (0.15 + 0.85*sq)))
    ry = r
    RED_=(220,50,50); WH_=(245,245,250); BK_=(20,20,24)
    box = pygame.Rect(cx-rx, cy-ry, rx*2, ry*2)

    prev = surf.get_clip()
    surf.set_clip(pygame.Rect(cx-rx, cy-ry, rx*2, ry))     # red top half
    pygame.draw.ellipse(surf, RED_, box)
    surf.set_clip(pygame.Rect(cx-rx, cy, rx*2, ry))        # white bottom half
    pygame.draw.ellipse(surf, WH_, box)
    surf.set_clip(prev)

    pygame.draw.ellipse(surf, BK_, box, 2)                    # outline
    pygame.draw.line(surf, BK_, (cx-rx, cy), (cx+rx, cy), 2)  # centre band

    br  = max(2, int(r*0.34))
    brx = max(1, int(br * (0.15 + 0.85*sq)))
    btn = pygame.Rect(cx-brx, cy-br, brx*2, br*2)
    pygame.draw.ellipse(surf, WH_, btn)
    pygame.draw.ellipse(surf, BK_, btn, 2)


RIV_MANUAL = [
    ('THE GOAL', [
        'You are a Pokemon trainer with a real Pokedex.',
        '',
        'Point the camera at a Pokemon - a card, a figure, a picture - and '
        'press SCAN. The device photographs it, identifies it, and adds it '
        'to your Pokedex.',
        '',
        'Catch all 1025 and earn all 72 gym badges across 9 regions.',
    ]),
    ('CATCHING', [
        '* Main Menu > Reverse Image Version > Play Catch Em All',
        '* Aim using the live camera feed',
        '* Press PAGELEFT to scan',
        '* The screen freezes on the photo it is checking',
        '',
        'On a hit you get the full Pokedex entry, it speaks the name out '
        'loud, records the catch and awards XP.',
        '',
        'Press BACK once to return to the camera, twice to leave.',
    ]),
    ('XP AND LEVELS', [
        '* 100 XP for any catch',
        '* +400 bonus the first time you catch a species',
        '',
        'Level N costs 500 x N XP. Level 2 needs 500, level 3 needs another '
        '1000, and so on up to level 50.',
        '',
        'Catching new species is worth far more than re-catching the same '
        'one. Go wide, not deep.',
    ]),
    ('REGIONS', [
        'The 1025 Pokemon are split across 9 regions, in order:',
        '',
        'Kanto 151, Johto 100, Hoenn 135, Sinnoh 107, Unova 156, '
        'Kalos 72, Alola 88, Galar 96, Paldea 120.',
        '',
        'Every region is open from the start - browse and catch anything, '
        'any time. Nothing is locked away.',
    ]),
    ('UNLOCKING BADGES', [
        'Each region has 8 gym badges. To earn ANY of a region\'s badges you '
        'must first catch 60% of that region.',
        '',
        '* Kalos: 44 of 72 (the easiest)',
        '* Alola: 53 of 88',
        '* Galar: 58 of 96',
        '* Johto: 60 of 100',
        '* Sinnoh: 65 of 107',
        '* Paldea: 72 of 120',
        '* Hoenn: 81 of 135',
        '* Kanto: 91 of 151',
        '* Unova: 94 of 156 (the hardest)',
        '',
        'The yellow line on each region bar marks the unlock point.',
    ]),
    ('EARNING BADGES', [
        'Once a region is unlocked, each badge has its own requirement:',
        '',
        '* Catch a specific Pokemon (Thunder Badge: catch Pikachu)',
        '* Catch a number from that region (Cascade Badge: 25 Kanto)',
        '* Complete the whole regional dex (Earth Badge: all 151)',
        '',
        'Trainer > Badges tab shows every badge and what it needs.',
    ]),
    ('WHERE TO START', [
        'Kalos is the smallest region at 72 Pokemon - only 44 to unlock its '
        'badges. Alola is next at 53, then Galar at 58.',
        '',
        'Kanto is the most famous but needs 91. Unova is the biggest at 156 '
        'and needs 94.',
        '',
        'You do not have to go in order. Chase whichever region you can '
        'actually find Pokemon for.',
    ]),
    ('THE SCREENS', [
        '* Pokedex List - all 1025 by region, caught ones green',
        '* Search by Name - letter grid, up/down cycles matches',
        '* Favourites - press ENTER on any Pokemon to star it',
        '* Caught Pokemon - TAB cycles sort: dex / most / recent',
        '* Catch Log - every catch, newest first',
        '* Trainer - TAB cycles: Info / Regions / Badges',
    ]),
    ('BUTTONS', [
        '* ENTER - open, confirm, star a Pokemon',
        '* CANCEL - back one step',
        '* TAB - switch tab or region, cycle sort',
        '* DPAD - move around',
        '* PAGELEFT - scan (only while playing)',
        '* PAGERIGHT - back',
    ]),
    ('DATA', [
        'Everything saves automatically and survives a reboot.',
        '',
        'Multiple trainers each keep their own catches, XP and badges. '
        'Switch from Trainer > Info > Switch / New Trainer.',
        '',
        'Main Menu > Data can erase one trainer\'s catches, or wipe the '
        'device completely. Both ask first.',
    ]),
]


PHYAI_MANUAL = [
    ('WHAT IT IS', [
        'PhyAI Challenge is a second way to play - the same Pokedex, but the '
        'recognition happens ON THE DEVICE instead of on the internet.',
        '',
        'It is not finished yet. This page explains what it will do and why '
        'it is worth having.',
    ]),
    ('WHY BOTHER', [
        'Reverse Image Version sends every photo to Google Lens. That means:',
        '',
        '* it needs wifi',
        '* it costs an API search every scan',
        '* it breaks when the image host stops working',
        '* it takes a few seconds per scan',
        '',
        'PhyAI has none of those problems.',
    ]),
    ('HOW IT WILL WORK', [
        'A vision model runs directly on the UNO Q. You point, you press '
        'SCAN, and the answer comes back from the board itself.',
        '',
        '* no internet',
        '* no API key, no quota, no monthly limit',
        '* no image upload to anywhere',
        '* instant',
    ]),
    ('THE TRADE-OFF', [
        'Google Lens knows all 1025 Pokemon and has seen millions of photos '
        'of each. A model small enough to run on this board will not.',
        '',
        'So PhyAI will start with a small set of Pokemon it knows well, and '
        'grow from there. Reverse Image Version stays as the mode that can '
        'identify anything.',
        '',
        'Two modes, two strengths.',
    ]),
    ('STATUS', [
        'Coming soon.',
        '',
        'Until it lands, use Reverse Image Version - it is the full game, '
        'all 1025 Pokemon, all 72 badges.',
        '',
        'Your catches, XP and badges are shared. Nothing is locked to one '
        'mode.',
    ]),
]

MANUALS = {
    'riv':   ('HOW TO PLAY - REVERSE IMAGE', RIV_MANUAL),
    'phyai': ('HOW TO PLAY - PHYAI', PHYAI_MANUAL),
}


class TextInput:
    """On-screen letter grid driven by the dpad. There's no keyboard on the
    device, so this is how any text gets entered.

    dpad moves the cursor, enter picks the highlighted key, cancel exits.
    The bottom row has DEL / SPACE / DONE.
    """
    ROWS = [
        list('ABCDEFGHIJ'),
        list('KLMNOPQRST'),
        list('UVWXYZ0123'),
        list('456789'),
        ['DEL', 'SPACE', 'DONE'],
    ]

    def __init__(self, title, value='', maxlen=14):
        self.title = title
        self.value = value
        self.maxlen = maxlen
        self.r = 0
        self.c = 0
        self.done = False
        self.cancelled = False

    def move(self, dr, dc):
        self.r = (self.r + dr) % len(self.ROWS)
        self.c = min(self.c, len(self.ROWS[self.r]) - 1)
        if dc:
            self.c = (self.c + dc) % len(self.ROWS[self.r])

    def press(self):
        key = self.ROWS[self.r][self.c]
        if key == 'DEL':
            self.value = self.value[:-1]
        elif key == 'SPACE':
            if len(self.value) < self.maxlen:
                self.value += ' '
        elif key == 'DONE':
            self.done = True
        elif len(self.value) < self.maxlen:
            self.value += key

    def draw(self, screen, F):
        screen.fill(BG)
        pygame.draw.rect(screen, RED, (0, 0, SCREEN_W, 36))
        screen.blit(F['med'].render(self.title, True, WHITE), (12, 7))

        # current value
        pygame.draw.rect(screen, PANEL, (40, 50, SCREEN_W - 80, 34), border_radius=6)
        pygame.draw.rect(screen, CYAN, (40, 50, SCREEN_W - 80, 34), 1, border_radius=6)
        shown = self.value + ('_' if int(time.time() * 2) % 2 else '')
        screen.blit(F['name'].render(shown, True, WHITE), (50, 56))

        # grid
        y = 100
        for ri, row in enumerate(self.ROWS):
            wide = ri == len(self.ROWS) - 1
            bw = 100 if wide else 52
            total = len(row) * (bw + 6) - 6
            x = SCREEN_W // 2 - total // 2
            for ci, key in enumerate(row):
                sel = (ri == self.r and ci == self.c)
                col = RED if sel else PANEL
                pygame.draw.rect(screen, col, (x, y, bw, 42), border_radius=5)
                pygame.draw.rect(screen, CYAN if sel else GREY,
                                 (x, y, bw, 42), 1, border_radius=5)
                f = F['sml'] if wide else F['name']
                t = f.render(key, True, WHITE)
                screen.blit(t, (x + bw // 2 - t.get_width() // 2,
                                y + 21 - t.get_height() // 2))
                x += bw + 6
            y += 48

        hint = F['tiny'].render('dpad = move   enter = pick   cancel = back',
                                True, GREY)
        screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 22))


class NumberInput:
    """Same idea as TextInput but for age - a simple up/down spinner."""

    def __init__(self, title, value=10, lo=1, hi=99):
        self.title = title
        self.value = value
        self.lo = lo
        self.hi = hi
        self.done = False
        self.cancelled = False

    def move(self, delta):
        self.value = max(self.lo, min(self.hi, self.value + delta))

    def draw(self, screen, F):
        screen.fill(BG)
        pygame.draw.rect(screen, RED, (0, 0, SCREEN_W, 36))
        screen.blit(F['med'].render(self.title, True, WHITE), (12, 7))

        pygame.draw.rect(screen, PANEL, (SCREEN_W // 2 - 70, 170, 140, 90),
                         border_radius=10)
        pygame.draw.rect(screen, CYAN, (SCREEN_W // 2 - 70, 170, 140, 90),
                         2, border_radius=10)
        t = F['big'].render(str(self.value), True, YELLOW)
        screen.blit(t, (SCREEN_W // 2 - t.get_width() // 2, 200))

        up = F['med'].render('/\\', True, CYAN)
        dn = F['med'].render('\\/', True, CYAN)
        screen.blit(up, (SCREEN_W // 2 - up.get_width() // 2, 140))
        screen.blit(dn, (SCREEN_W // 2 - dn.get_width() // 2, 268))

        hint = F['tiny'].render('up/down = change   enter = confirm   cancel = back',
                                True, GREY)
        screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 22))


class ChoiceInput:
    """Pick one from a short list (gender, team)."""

    def __init__(self, title, options, value=0, colors=None):
        self.title = title
        self.options = options
        self.sel = value
        self.colors = colors or {}
        self.done = False
        self.cancelled = False

    def move(self, delta):
        self.sel = (self.sel + delta) % len(self.options)

    def draw(self, screen, F):
        screen.fill(BG)
        pygame.draw.rect(screen, RED, (0, 0, SCREEN_W, 36))
        screen.blit(F['med'].render(self.title, True, WHITE), (12, 7))

        y = 120
        for i, opt in enumerate(self.options):
            sel = i == self.sel
            col = self.colors.get(opt, HILITE) if sel else PANEL
            pygame.draw.rect(screen, col, (140, y, 360, 46), border_radius=8)
            pygame.draw.rect(screen, CYAN if sel else GREY,
                             (140, y, 360, 46), 1, border_radius=8)
            if sel:
                draw_pokeball(screen, 165, y + 23, 11, time.time())
            t = F['med'].render(opt, True, WHITE if sel else GREY)
            screen.blit(t, (200, y + 13))
            y += 58

        hint = F['tiny'].render('up/down = move   enter = confirm   cancel = back',
                                True, GREY)
        screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 22))


class App:
    def __init__(self):
        with open(DB_PATH) as f:
            self.db=json.load(f)
        # id -> name lookup and per-region lists
        self.by_id={v['id']:{**v,'name':k} for k,v in self.db.items()}
        self.regions={r:[] for r in REGIONS}
        for pid in sorted(self.by_id):
            self.regions[self.by_id[pid]['region']].append(pid)
        self.catchdb=CatchDB(CATCH_DB)

        pygame.init()
        # Fullscreen: covers the XFCE panel so the device looks like a
        # handheld, not a Linux box with a Pokedex window on it. The panel
        # comes back on Exit because pygame.quit() releases the display.
        # FULLSCREEN alone can trigger a mode switch on some drivers; the
        # display is a fixed 640x480 panel, so we ask for exactly that and
        # let SCALED handle any mismatch rather than fighting the driver.
        try:
            self.screen=pygame.display.set_mode(
                (SCREEN_W,SCREEN_H), pygame.FULLSCREEN | pygame.SCALED)
        except pygame.error:
            # No fullscreen available (running headless / odd driver) - fall
            # back to a plain window rather than refusing to start.
            self.screen=pygame.display.set_mode((SCREEN_W,SCREEN_H))
        pygame.display.set_caption("Pokedex")
        pygame.mouse.set_visible(False)

        # The real panel surface. Handlers draw to self.screen (an off-screen
        # canvas the same size); at flip time we scale that canvas into the
        # area left visible by the bezel. This shifts/pads the whole UI with
        # one blit instead of offsetting hundreds of draw calls.
        self._display = self.screen
        self.screen = pygame.Surface((SCREEN_W, SCREEN_H))
        self._visible = pygame.Rect(
            BEZEL_LEFT, BEZEL_TOP,
            SCREEN_W - BEZEL_LEFT - BEZEL_RIGHT,
            SCREEN_H - BEZEL_TOP - BEZEL_BOTTOM)

        # Pre-render the 3D pokeball frames now, at startup, rather than
        # stuttering on the first throw. Costs well under a second and about
        # 400KB; after this the animation is just blitting.
        if THROW_ANIM:
            _t0=time.time()
            ball_frames(BALL_BIG); ball_frames(BALL_SMALL)
            print('3D pokeball frames ready in %.2fs' % (time.time()-_t0))
        self.clock=pygame.time.Clock()
        self.F={
            'big': pygame.font.SysFont('arialblack',28,bold=True),
            'name':pygame.font.SysFont('arialblack',20,bold=True),
            'med': pygame.font.SysFont('arial',17,bold=True),
            'sml': pygame.font.SysFont('arial',14,bold=True),
            'tiny':pygame.font.SysFont('arial',11,bold=True),
            # larger set, used on the detail/stats screen to fill the empty
            # space that was there before - see _tab_stats / _left_panel
            'dname':pygame.font.SysFont('arialblack',30,bold=True),
            'dbig': pygame.font.SysFont('arialblack',26,bold=True),
            'dmed': pygame.font.SysFont('arial',22,bold=True),
            'dsml': pygame.font.SysFont('arial',18,bold=True),
        }

        self.state=MAIN_MENU
        self.main_sel=0
        self.riv_sel=0
        self.region_idx=0
        self.browse_sel=0
        self.browse_scroll=0
        self.caught_sel=0
        self.caught_scroll=0
        self.detail_pid=None
        self.detail_from=BROWSER
        self.result_tab=0
        # trainer / profile
        self.tr_sel=0
        self.tr_tab=0
        self.tr_scroll=0
        self.man_page=0
        self.man_which='riv'
        self.help_sel=0
        self.mg_sel=0
        self.tl_sel=0
        self.new_step=0
        self.new_data={}
        self.widget=None
        # data menu / confirm
        self.dm_sel=0
        self.cf_sel=1
        self.confirm=None
        # search / favs / log
        self.search_msg=''
        self.search_hits=[]
        self.fav_sel=0
        self.fav_scroll=0
        self.log_scroll=0
        self.caught_sort='dex'
        # catch feedback popup
        self.popup=None
        self.popup_until=0
        self.running=True
        self.muted=False   # GPIO10 toggles; resets to unmuted every launch
        self.oak_phase='idle'   # idle|recording|thinking|done
        self.oak_q=''; self.oak_a=''
        self.oak_hist=[]
        self.phyai_ready=False
        self.phyai_label=None; self.phyai_conf=0.0
        self.phyai_last_infer=0.0

        # gameplay state
        self.cap=None
        self.scan_holder={'entry':None,'status':'','busy':False,'show':False}
        self.scan_start=0
        self.scan_img=None
        self.throw=None      # {'t0':float, 'phase':str}
        self.live_surf=None
        self.last_cam_read=0.0
        self.gameplay_result=False  # showing scanned result vs live

    # ── camera lifecycle ──
    def start_cam(self):
        if self.cap is None:
            dev=find_camera()
            print('Using camera:', dev)
            self.cap=cv2.VideoCapture(dev, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    def stop_cam(self):
        if self.cap is not None:
            self.cap.release(); self.cap=None

    # ── recognition thread ──
    def identify(self):
        h=self.scan_holder
        try:
            h['status']='Uploading...'
            url=upload_image(CAPTURE_PATH)
            h['status']='Searching...'
            titles=search_image(url)
            entry=match_pokemon(extract_candidates(titles), self.db)
            if entry:
                # let the ball burst open before the result screen replaces it
                if THROW_ANIM and self.throw and self.throw['phase']=='wobble':
                    self.throw['phase']='burst'
                    self.throw['t0']=time.time()
                    time.sleep(0.65)
                self.throw=None
                h['entry']=entry
                h['show']=True
                self.result_tab=0
                xp, leveled, new_badges = self.catchdb.record(entry['id'], entry['name'])
                play_ting()
                lines = ['+%d XP' % xp] if xp else []
                if leveled:
                    lvl = level_from_xp(self.catchdb.trainer()['xp'])[0]
                    lines.append('LEVEL %d!' % lvl)
                for b in new_badges:
                    lines.append('Badge: ' + b)
                if lines:
                    self.popup = lines
                    self.popup_until = time.time() + 4
                types=' and '.join(entry.get('types',[]))
                ab=' and '.join(entry.get('abilities',[])[:2]).replace('-',' ')
                mv=', '.join(m.replace('-',' ') for m in entry.get('moves',[])[:3])
                speak(f"{entry['name']}, {types} type pokemon. Abilities are {ab}. Moves include {mv}.")
                if leveled:
                    speak(f"Level up! You are now level {level_from_xp(self.catchdb.trainer()['xp'])[0]}")
                for b in new_badges:
                    speak(f"New badge earned. {b}")
            else:
                self.throw=None          # ball stops wobbling - it got away
                h['status']='Pokemon not found'
                speak("Pokemon not found")
                time.sleep(2)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.throw=None
            h['status']='Error'
            time.sleep(2)
        finally:
            h['busy']=False

    # ── main loop ──
    def run(self):
        clear_trigs()
        self.running=True
        while self.running:
            for ev in pygame.event.get():
                if ev.type==pygame.QUIT: self.running=False
                if ev.type==pygame.KEYDOWN and ev.key==pygame.K_q: self.running=False

            handler={
                MAIN_MENU:self.h_main, RIV_MENU:self.h_riv, GAMEPLAY:self.h_game,
                BROWSER:self.h_browser, DETAIL:self.h_detail, CAUGHT:self.h_caught,
                PHYAI:self.h_phyai, OAK:self.h_oak, TRAINER:self.h_trainer,
                TRAINER_NEW:self.h_trainer_new, TRAINER_LIST:self.h_trainer_list,
                MANUAL:self.h_manual, HELP_MENU:self.h_help_menu, DATA_MENU:self.h_data_menu,
                MORE_GAMES:self.h_more_games,
                GAME_FLAPPY:self.h_game_flappy, GAME_TETRIS:self.h_game_tetris,
                GAME_SNAKE:self.h_game_snake,
                SEARCH:self.h_search, LOG:self.h_log, FAVS:self.h_favs,
                CONFIRM:self.h_confirm,
            }[self.state]
            # mute is global - check it before the per-screen handler so it
            # works everywhere. GPIO10 toggles; a brief popup confirms.
            if trig('mute'):
                self.muted = not self.muted
                set_muted(self.muted)
                if self.muted:
                    stop_audio()       # cut off whatever is speaking right now
                self.popup = 'Sound OFF' if self.muted else 'Sound ON'
                self.popup_until = time.time()+1.2

            handler()
            self._draw_popup()
            self._draw_mute()

            # composite the off-screen canvas into the bezel-visible area
            self._present()
            # 30fps with the throw animation off. 60 only existed to make the
            # throw smooth, and burning CPU for frames nothing needs is a bad
            # trade on a board that's browning out. THROW_ANIM=True -> put
            # this back to 60.
            self.clock.tick(60 if THROW_ANIM else 30)
        self.stop_cam()
        pygame.quit()

    # ── MAIN MENU ──
    def h_main(self):
        items=['Reverse Image Version','PhyAI Challenge','How to Play',
               'Professor Oak','Trainer Status','Data','More Games','Exit']
        if trig('down'): self.main_sel=(self.main_sel+1)%len(items)
        if trig('up'):   self.main_sel=(self.main_sel-1)%len(items)
        if trig('select'):
            if self.main_sel==0: self.state=RIV_MENU; self.riv_sel=0
            elif self.main_sel==1:
                self.state=PHYAI
                self.phyai_ready = phyai_load()
                self.phyai_label=None; self.phyai_conf=0.0
                self.scan_holder={'entry':None,'status':'','busy':False,'show':False}
                self.live_surf=None
                if self.phyai_ready:
                    self.start_cam()
            elif self.main_sel==2: self.state=HELP_MENU; self.help_sel=0
            elif self.main_sel==3:
                self.state=OAK; self.oak_phase='idle'
                self.oak_q=''; self.oak_a=''; self.oak_hist=[]
            elif self.main_sel==4: self.state=TRAINER; self.tr_sel=0; self.tr_tab=0
            elif self.main_sel==5: self.state=DATA_MENU; self.dm_sel=0
            elif self.main_sel==6: self.state=MORE_GAMES; self.mg_sel=0
            else:
                self.confirm={'msg':'Exit Pokedex?',
                              'sub':'The app will close and you will be back at the desktop.',
                              'action':('exit',None), 'back':MAIN_MENU}
                self.state=CONFIRM; self.cf_sel=1
        trig('back')  # exit ignored; Q quits
        clear_trigs()

        s=self.screen; s.fill(BG)
        self._title("MAIN MENU")
        self._menu_items(items, self.main_sel, 62, gap=37)

        # trainer strip along the bottom
        t=self.catchdb.trainer()
        if t:
            lvl,into,need = level_from_xp(t['xp'])
            tc = TEAM_COLORS.get(t['team'], GREY)
            pygame.draw.rect(s, PANEL, (0, SCREEN_H-46, SCREEN_W, 46))
            pygame.draw.rect(s, tc, (0, SCREEN_H-46, 4, 46))
            draw_pokeball(s, 26, SCREEN_H-23, 10, time.time())
            s.blit(self.F['sml'].render(t['name'][:14], True, WHITE), (46, SCREEN_H-38))
            s.blit(self.F['tiny'].render('Lv %d  -  Team %s'%(lvl,t['team']), True, tc),
                   (46, SCREEN_H-20))
            st=self.catchdb.stats()
            s.blit(self.F['tiny'].render('%d/1025 caught'%st['unique'], True, GREY),
                   (SCREEN_W-150, SCREEN_H-38))
            s.blit(self.F['tiny'].render('%d/%d badges'%(self.catchdb.badge_count(),
                   TOTAL_BADGES), True, YELLOW), (SCREEN_W-150, SCREEN_H-22))
        else:
            hint=self.F['tiny'].render('No trainer yet - open Trainer Status to create one',
                                       True, GREY)
            s.blit(hint,(SCREEN_W//2-hint.get_width()//2, SCREEN_H-40))
        self._footer("enter = open    up/down = move")

    # ── REVERSE IMAGE VERSION MENU ──
    def h_riv(self):
        items=['Play Catch \'Em All','Pokedex List','Search by Name',
               'Favourites','Caught Pokemon','Catch Log','Back']
        if trig('down'): self.riv_sel=(self.riv_sel+1)%len(items)
        if trig('up'):   self.riv_sel=(self.riv_sel-1)%len(items)
        if trig('select'):
            if self.riv_sel==0:
                self.state=GAMEPLAY; self.gameplay_result=False
                self.scan_holder={'entry':None,'status':'','busy':False,'show':False}
                self.scan_img=None
                self.throw=None
                self.live_surf=None
                self.start_cam()
            elif self.riv_sel==1:
                self.state=BROWSER; self.browse_sel=0; self.browse_scroll=0
            elif self.riv_sel==2:
                self.state=SEARCH; self.widget=TextInput('SEARCH POKEMON')
                self.search_msg=''
            elif self.riv_sel==3:
                self.state=FAVS; self.fav_sel=0; self.fav_scroll=0
            elif self.riv_sel==4:
                self.state=CAUGHT; self.caught_sel=0; self.caught_scroll=0
            elif self.riv_sel==5:
                self.state=LOG; self.log_scroll=0
            else:
                self.state=MAIN_MENU
        if trig('back'): self.state=MAIN_MENU
        clear_trigs()

        s=self.screen; s.fill(BG)
        self._title("Reverse Image Version")
        self._menu_items(items, self.riv_sel, 70, gap=44)
        self._footer("enter = open    cancel = back")

    # ── GAMEPLAY (existing scan logic) ──
    def h_game(self):
        h=self.scan_holder
        # showing a result: back goes ONE step (result -> live), not to the menu
        if h['show']:
            if trig('back'):
                h['show']=False; h['entry']=None; self.throw=None
                clear_trigs()
                return
            if trig('scan'):
                h['show']=False; h['entry']=None; self.throw=None   # rescan
            if trig('tab') or trig('right'):
                self.result_tab=(self.result_tab+1)%len(RESULT_TABS)
            if trig('left'):
                self.result_tab=(self.result_tab-1)%len(RESULT_TABS)
            trig('up'); trig('down'); trig('select')
        else:
            # live: back exits gameplay to the menu
            if trig('back'):
                self.stop_cam()
                self.throw=None
                self.state=RIV_MENU
                clear_trigs()
                return
            if trig('scan') and not h['busy']:
                for _ in range(5): self.cap.read()   # flush stale buffered frames
                ret,frame=self.cap.read()
                if ret:
                    cv2.imwrite(CAPTURE_PATH, frame)
                    # keep the exact frame we're uploading, to show during the scan
                    frm=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.scan_img=pygame.surfarray.make_surface(
                        cv2.resize(frm,(SCREEN_W,SCREEN_H)).swapaxes(0,1))
                    h['entry']=None; h['status']='Scanning...'; h['busy']=True
                    self.scan_start=time.time()
                    if THROW_ANIM:
                        self.throw={'t0':time.time(), 'phase':'fly'}
                    threading.Thread(target=self.identify, daemon=True).start()
            clear_trigs()

        s=self.screen
        if h['show'] and h['entry']:
            self._draw_result(h['entry'])
        elif h['busy']:
            self._draw_scanning(h)
        else:
            # live feed. cap.read() is the single most expensive call in the
            # app - it halves the frame rate on its own. The camera delivers
            # ~15fps regardless, so reading it every 60fps frame just burns
            # CPU for identical pixels. Read at most 20/sec and reuse the last
            # frame in between.
            if self.cap:
                now=time.time()
                if now-self.last_cam_read >= 0.05:
                    ret,frame=self.cap.read()
                    if ret:
                        frm=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        self.live_surf=pygame.surfarray.make_surface(
                            cv2.resize(frm,(SCREEN_W,SCREEN_H)).swapaxes(0,1))
                    self.last_cam_read=now
                if self.live_surf is not None:
                    s.blit(self.live_surf,(0,0))
            if THROW_ANIM:
                draw_ball3d(s, SCREEN_W//2, SCREEN_H-46, BALL_BIG,
                            time.time()*0.7, shadow=True)
                hint=self.F['tiny'].render('SCAN to throw', True, WHITE)
                hsc=pygame.Surface((hint.get_width()+10, hint.get_height()+4), pygame.SRCALPHA)
                hsc.fill((0,0,0,150))
                s.blit(hsc,(SCREEN_W//2-hint.get_width()//2-5, SCREEN_H-96))
                s.blit(hint,(SCREEN_W//2-hint.get_width()//2, SCREEN_H-94))
            pygame.draw.rect(s, RED,(0,0,SCREEN_W,40))
            s.blit(self.F['med'].render("CATCH 'EM ALL", True, WHITE),(12,8))
            s.blit(self.F['sml'].render("SCAN = detect   BACK = exit", True, WHITE),(SCREEN_W-260,12))

    def _draw_scanning(self, h):
        # Frozen photo + "WHO'S THAT POKEMON?" underneath, ball animation on top.
        s=self.screen
        s.fill(BLACK)
        if self.scan_img is not None:
            s.blit(self.scan_img,(0,0))
        # dark scrim behind the text band so it stays readable on bright photos
        scrim=pygame.Surface((SCREEN_W,220), pygame.SRCALPHA)
        scrim.fill((0,0,0,190))
        s.blit(scrim,(0,110))
        t1=self.F['big'].render("WHO'S THAT",True,YELLOW)
        t2=self.F['big'].render("POKEMON?",True,YELLOW)
        s.blit(t1,(SCREEN_W//2-t1.get_width()//2,130))
        s.blit(t2,(SCREEN_W//2-t2.get_width()//2,170))
        bw=400;bh=22;bx=SCREEN_W//2-bw//2;by=270
        pygame.draw.rect(s,PANEL,(bx,by,bw,bh),border_radius=11)
        el=time.time()-self.scan_start; pulse=(math.sin(el*4)+1)/2
        pygame.draw.rect(s,RED,(bx+3,by+3,int((0.3+0.7*pulse)*(bw-6)),bh-6),border_radius=9)
        st=self.F['med'].render(h['status'],True,WHITE)
        s.blit(st,(SCREEN_W//2-st.get_width()//2,by+34))
        self._draw_throw()

    def _draw_throw(self):
        """The pokeball: flies up the screen, then wobbles until Lens answers.

        Purely cosmetic - the upload and search run in a thread regardless.
        The animation just fills the wait, which is 5-15s.
        """
        if not THROW_ANIM or not self.throw:
            return
        s=self.screen
        t=time.time()-self.throw['t0']
        x0,y0 = SCREEN_W//2, SCREEN_H-46        # where it sits on the live feed
        x1,y1 = SCREEN_W//2, 210                # where it lands

        if self.throw['phase']=='fly':
            FLY=0.80          # at 60fps that's ~48 frames of arc
            if t>=FLY:
                self.throw['phase']='wobble'
                self.throw['t0']=time.time()
                return
            p=t/FLY
            x=x0+(x1-x0)*p
            y=y0+(y1-y0)*p - math.sin(p*math.pi)*90     # arc
            sz=int(BALL_BIG-(BALL_BIG-BALL_SMALL)*p)    # shrinks as it flies away
            draw_ball3d(s, int(x), int(y), sz, t*14)

        elif self.throw['phase']=='wobble':
            # rocks left-right, pausing between rocks. runs as long as the
            # search takes - no fixed number of wobbles.
            cyc=t%1.4
            ang=0.0
            if cyc<0.9:
                ang=math.sin(cyc*7.0)*0.30*(1-cyc/0.9)
            f=ball_frames(BALL_SMALL)[0]
            rot=pygame.transform.rotate(f, math.degrees(ang))
            sh=pygame.Surface((BALL_SMALL,BALL_SMALL//3), pygame.SRCALPHA)
            pygame.draw.ellipse(sh,(0,0,0,90),(0,0,BALL_SMALL,BALL_SMALL//3))
            s.blit(sh,(x1-BALL_SMALL//2, y1+BALL_SMALL//2-4))
            s.blit(rot, (x1-rot.get_width()//2, y1-rot.get_height()//2))

        elif self.throw['phase']=='burst':
            draw_burst(s, x1, y1, 18, t)
            if t>0.7:
                self.throw=None

    # ── result screen with tabs (used in gameplay) ──
    def _draw_result(self, e):
        s=self.screen; s.fill(BG)
        pygame.draw.rect(s,RED,(0,0,SCREEN_W,36))
        s.blit(self.F['med'].render("POKEDEX",True,WHITE),(12,7))
        hint=self.F['tiny'].render("tab=next  scan=rescan  back=exit",True,WHITE)
        s.blit(hint,(SCREEN_W-hint.get_width()-12,12))
        self._left_panel(e)
        self._result_tabs(self.result_tab)
        t=self.result_tab
        if t==0: self._tab_stats(e)
        elif t==1: self._tab_location(e)
        elif t==2: self._tab_evolution(e)
        elif t==3: self._tab_moves(e)
        elif t==4: self._tab_placeholder("CRY")

    def _left_panel(self, e):
        s=self.screen; F=self.F
        # bigger image box (was 150) and image (was 140) to use the space
        pygame.draw.rect(s,PANEL,(18,64,196,196),border_radius=8)
        pygame.draw.rect(s,CYAN,(18,64,196,196),1,border_radius=8)
        img=poke_img(e['id'],184)
        if img: s.blit(img,(24,70))
        s.blit(F['dsml'].render(f"#{e['id']:03d}",True,RED),(18,266))
        s.blit(F['dname'].render(e['name'].upper(),True,CYAN),(18,290))
        if e.get('genus'): s.blit(F['dsml'].render(e['genus'],True,WHITE),(18,326))
        y=356
        for t in e.get('types',[]):
            tc=TYPE_COLORS.get(t,GREY); badge=F['dsml'].render(t.upper(),True,WHITE)
            bw=badge.get_width()+18
            pygame.draw.rect(s,tc,(18,y,bw,28),border_radius=12)
            s.blit(badge,(27,y+5)); y+=34

    def _result_tabs(self, active):
        s=self.screen; F=self.F; x=180
        for i,name in enumerate(RESULT_TABS):
            w=F['tiny'].render(name,True,WHITE).get_width()+16
            pygame.draw.rect(s, RED if i==active else PANEL,(x,42,w,20),border_radius=4)
            pygame.draw.rect(s,CYAN,(x,42,w,20),1,border_radius=4)
            s.blit(F['tiny'].render(name,True,WHITE),(x+8,45)); x+=w+4

    def _tab_stats(self, e):
        s=self.screen; F=self.F
        s.blit(F['dbig'].render("BASE STATS",True,CYAN),(230,72))
        y=118
        for key,label in STAT_LABELS:
            val=e.get('stats',{}).get(key,0)
            s.blit(F['dmed'].render(label,True,CYAN),(230,y))
            bx,bw=350,190
            pygame.draw.rect(s,PANEL,(bx,y+2,bw,22),border_radius=4)
            fill=int((min(val,180)/180.0)*bw)
            col=GREEN if val>=90 else (YELLOW if val>=60 else ORANGE)
            pygame.draw.rect(s,col,(bx,y+2,fill,22),border_radius=4)
            s.blit(F['dmed'].render(str(val),True,WHITE),(bx+bw+10,y)); y+=52

    def _tab_evolution(self, e):
        s=self.screen; F=self.F
        s.blit(F['dbig'].render("EVOLUTION",True,CYAN),(230,72))
        evo=e.get('evolution',[])
        if len(evo)<2:
            s.blit(F['dmed'].render("Does not evolve",True,WHITE),(230,180)); return
        n=min(len(evo),3); start=225; right_limit=620
        # fit n boxes with a fixed gap between them, inside start..right_limit
        gap=40
        box=(right_limit-start-gap*(n-1))//n
        box=min(box,120)
        x=start
        for idx in range(n):
            nm=evo[idx]['name']; pid=self.db.get(nm,{}).get('id')
            pygame.draw.rect(s,PANEL,(x,140,box,box),border_radius=10)
            pygame.draw.rect(s,CYAN,(x,140,box,box),1,border_radius=10)
            if pid:
                img=poke_img(pid,box-18)
                if img: s.blit(img,(x+9,149))
            lb=F['dsml'].render(nm.upper()[:9],True,WHITE)
            s.blit(lb,(x+box//2-lb.get_width()//2,box+150))
            if idx<n-1:
                ax=x+box+gap//2
                s.blit(F['dbig'].render(">",True,ORANGE),(ax-8,185))
                lvl=evo[idx+1].get('level')
                if lvl:
                    lt=F['dsml'].render(f"Lv{lvl}",True,GREY)
                    s.blit(lt,(ax-lt.get_width()//2,225))
            x+=box+gap

    def _tab_moves(self, e):
        s=self.screen; F=self.F
        s.blit(F['dbig'].render("MOVES",True,CYAN),(230,72))
        y=124
        for mv in e.get('moves',[])[:6]:
            s.blit(F['dmed'].render(f"- {mv.replace('-',' ').title()}",True,WHITE),(240,y)); y+=48

    def _tab_location(self, e):
        s=self.screen; F=self.F
        s.blit(F['dbig'].render("LOCATION",True,CYAN),(230,72))
        locs=e.get('locations')
        if locs is None:
            s.blit(F['dmed'].render("No location data.",True,GREY),(230,150))
            s.blit(F['dsml'].render("Run build_locations.py to add it.",True,GREY),(230,182))
            return
        if not locs:
            s.blit(F['dmed'].render("Not found in the wild",True,GREY),(230,150))
            s.blit(F['dsml'].render("Evolve or trade to get this one.",True,GREY),(230,182))
            return
        y=120
        for loc in locs[:5]:
            area=loc['area'][:32]
            s.blit(F['dmed'].render("- "+area,True,WHITE),(235,y)); y+=30
            if loc.get('games'):
                g=', '.join(loc['games'][:3])[:38]
                s.blit(F['dsml'].render("  "+g,True,GREY),(245,y)); y+=32
            else:
                y+=8
            if y>430: break

    def _tab_placeholder(self, title):
        s=self.screen; F=self.F
        s.blit(F['dbig'].render(title,True,CYAN),(230,72))
        s.blit(F['dmed'].render("Coming soon",True,GREY),(230,150))

    # ── POKEDEX BROWSER ──
    def h_browser(self):
        region=REGIONS[self.region_idx]
        ids=self.regions[region]
        visible=11
        if trig('tab') or trig('right'):
            self.region_idx=(self.region_idx+1)%len(REGIONS); self.browse_sel=0; self.browse_scroll=0
        if trig('left'):
            self.region_idx=(self.region_idx-1)%len(REGIONS); self.browse_sel=0; self.browse_scroll=0
        if trig('down'):
            if self.browse_sel < len(ids)-1: self.browse_sel+=1
            if self.browse_sel >= self.browse_scroll+visible: self.browse_scroll+=1
        if trig('up'):
            if self.browse_sel>0: self.browse_sel-=1
            if self.browse_sel < self.browse_scroll: self.browse_scroll-=1
        if trig('select') and ids:
            self.detail_pid=ids[self.browse_sel]; self.detail_from=BROWSER; self.state=DETAIL
        if trig('back'): self.state=RIV_MENU
        clear_trigs()

        s=self.screen; s.fill(BG)
        pygame.draw.rect(s,RED,(0,0,SCREEN_W,36))
        s.blit(self.F['med'].render("POKEDEX LIST",True,WHITE),(12,7))
        # region tabs
        x=12; y=44
        for i,r in enumerate(REGIONS):
            w=self.F['tiny'].render(r,True,WHITE).get_width()+12
            if x+w>SCREEN_W-12: break
            pygame.draw.rect(s, RED if i==self.region_idx else PANEL,(x,y,w,20),border_radius=4)
            s.blit(self.F['tiny'].render(r,True,WHITE),(x+6,y+3)); x+=w+4
        # current region label if off-screen
        s.blit(self.F['sml'].render(f"[{region}]  {len(ids)} Pokemon",True,CYAN),(12,72))
        # list
        yy=98
        for i in range(self.browse_scroll, min(self.browse_scroll+visible, len(ids))):
            pid=ids[i]; nm=self.by_id[pid]['name'].title()
            sel=(i==self.browse_sel)
            if sel:
                pygame.draw.rect(s,HILITE,(12,yy-2,SCREEN_W-24,26),border_radius=4)
                draw_pokeball(s, 25, yy+10, 9, time.time())
            caught=self.catchdb.get(pid) is not None
            col=GREEN if caught else WHITE
            s.blit(self.F['sml'].render(f"#{pid:04d}  {nm}",True,col),(40,yy))
            yy+=28
        self._footer("UP/DOWN=move  TAB=region  SELECT=open  BACK=return")

    # ── DETAIL SCREEN ──
    def h_detail(self):
        e=self.by_id[self.detail_pid]
        if trig('back'):
            self.state=self.detail_from
            clear_trigs(); return
        if trig('tab') or trig('right'):
            self.result_tab=(self.result_tab+1)%len(RESULT_TABS)
        if trig('left'):
            self.result_tab=(self.result_tab-1)%len(RESULT_TABS)
        if trig('select'):
            self.catchdb.toggle_fav(e['id'])   # enter = star / unstar
        if trig('up') and self.search_hits:
            i=self.search_hits.index(self.detail_pid) if self.detail_pid in self.search_hits else 0
            self.detail_pid=self.search_hits[(i-1)%len(self.search_hits)]
        if trig('down') and self.search_hits:
            i=self.search_hits.index(self.detail_pid) if self.detail_pid in self.search_hits else 0
            self.detail_pid=self.search_hits[(i+1)%len(self.search_hits)]
        trig('scan')
        clear_trigs()
        # reuse the same tabbed result view
        self._draw_result(e)
        c=self.catchdb.get(e['id'])
        s=self.screen; F=self.F
        # favourite star
        fav=self.catchdb.is_fav(e['id'])
        draw_star(s, SCREEN_W-24, 458, 9, fav)
        s.blit(F['tiny'].render('enter = star' if not fav else 'enter = unstar',
                                True, YELLOW if fav else GREY),(SCREEN_W-120,454))
        if c:
            s.blit(F['tiny'].render(f"Caught x{c['count']}  Last {c['last']}",True,GREEN),(18,458))
        else:
            s.blit(F['tiny'].render("Not Caught Yet",True,GREY),(18,458))
        if self.search_hits and len(self.search_hits)>1:
            i=self.search_hits.index(self.detail_pid)+1 if self.detail_pid in self.search_hits else 1
            s.blit(F['tiny'].render(f"match {i}/{len(self.search_hits)}  up/down",
                                    True,CYAN),(200,458))

    def _mini_evo(self, evo, x0, y0):
        s=self.screen; F=self.F
        n=min(len(evo),3); box=46; x=x0
        for idx in range(n):
            nm=evo[idx]['name']; pid=self.db.get(nm,{}).get('id')
            img=poke_img(pid,box) if pid else None
            if img: s.blit(img,(x,y0))
            if idx<n-1:
                s.blit(F['sml'].render(">",True,ORANGE),(x+box+4,y0+box//2-6))
            x+=box+22

    # ── CAUGHT SCREEN ──
    def h_caught(self):
        caught=self.catchdb.all_caught(self.caught_sort)
        visible=6
        if trig('tab'):
            modes=['dex','count','date']
            self.caught_sort=modes[(modes.index(self.caught_sort)+1)%len(modes)]
            self.caught_sel=0; self.caught_scroll=0
            caught=self.catchdb.all_caught(self.caught_sort)
        if trig('down'):
            if self.caught_sel<len(caught)-1: self.caught_sel+=1
            if self.caught_sel>=self.caught_scroll+visible: self.caught_scroll+=1
        if trig('up'):
            if self.caught_sel>0: self.caught_sel-=1
            if self.caught_sel<self.caught_scroll: self.caught_scroll-=1
        if trig('select') and caught:
            self.detail_pid=caught[self.caught_sel]['pid']; self.detail_from=CAUGHT
            self.state=DETAIL; self.result_tab=0
        if trig('back'): self.state=RIV_MENU
        clear_trigs()

        s=self.screen; F=self.F; s.fill(BG)
        pygame.draw.rect(s,RED,(0,0,SCREEN_W,36))
        s.blit(F['med'].render("CAUGHT POKEMON",True,WHITE),(12,7))
        st=self.catchdb.stats()
        pct=100.0*st['unique']/1025
        s.blit(F['sml'].render(f"Caught: {st['unique']}/1025   ({pct:.1f}%)",True,CYAN),(12,44))
        s.blit(F['tiny'].render(f"Total Catches: {st['total']}   Most: {st['most']}   Latest: {st['latest']}",True,WHITE),(12,66))
        sort_label={'dex':'Dex No.','count':'Most Caught','date':'Recent'}[self.caught_sort]
        sl=F['tiny'].render('Sort: '+sort_label+'  (tab)',True,YELLOW)
        s.blit(sl,(SCREEN_W-sl.get_width()-12,44))

        if not caught:
            s.blit(F['sml'].render("No Pokemon caught yet!",True,GREY),(12,120))
            self._footer("BACK = return"); return

        yy=90
        for i in range(self.caught_scroll, min(self.caught_scroll+visible,len(caught))):
            c=caught[i]; sel=(i==self.caught_sel)
            if sel:
                pygame.draw.rect(s,HILITE,(10,yy-2,SCREEN_W-20,58),border_radius=6)
                draw_pokeball(s, SCREEN_W-24, yy+28, 9, time.time())
            img=poke_img(c['pid'],50)
            if img: s.blit(img,(16,yy))
            s.blit(F['sml'].render(f"#{c['pid']:04d} {c['name'].title()}",True,WHITE),(74,yy+2))
            s.blit(F['tiny'].render(f"Catches: {c['count']}",True,CYAN),(74,yy+22))
            s.blit(F['tiny'].render(f"First {c['first']}  Last {c['last']}",True,GREY),(74,yy+38))
            yy+=60
        self._footer("up/down = move    tab = sort    enter = open    cancel = back")

    # ── PHYAI - on-device recognition, no internet ──
    def h_phyai(self):
        """Live camera + on-device classification. Unlike Reverse Image
        Version there's no network round-trip, so we classify continuously
        rather than waiting for a SCAN press - the moment you point at a
        Pokemon and hold it steady, an answer appears. SCAN still works, to
        catch it (same catch/XP/badge path as Reverse Image Version)."""
        if not self.phyai_ready:
            if trig('back') or trig('select'): self.state=MAIN_MENU
            clear_trigs()
            s=self.screen; s.fill(BG)
            self._title("PhyAI Challenge")
            if not os.path.exists(PHYAI_MODEL):
                msg = "Model file not found."
                detail = f"Expected at {PHYAI_MODEL}"
            else:
                msg = "Couldn't load the model."
                detail = _phyai_last_error[0][:70] or "(no error captured)"
            t=self.F['med'].render(msg, True, YELLOW)
            s.blit(t,(SCREEN_W//2-t.get_width()//2,170))
            sub=self.F['tiny'].render(detail, True, GREY)
            s.blit(sub,(SCREEN_W//2-sub.get_width()//2,204))
            self._footer("cancel = back")
            return

        h = self.scan_holder
        if h['show']:
            # viewing a caught result - back goes ONE step (result -> live),
            # matching Reverse Image Version's behaviour. This has to be
            # checked BEFORE the general "back exits to menu" case below, or
            # back would always jump straight to the menu from a result.
            if trig('back'):
                h['show']=False; h['entry']=None
                clear_trigs(); return
            if trig('tab') or trig('right'):
                self.result_tab=(self.result_tab+1)%len(RESULT_TABS)
            if trig('left'):
                self.result_tab=(self.result_tab-1)%len(RESULT_TABS)
            trig('up'); trig('down'); trig('select'); trig('scan')
            clear_trigs()
            self._draw_result(h['entry'])
            return

        if trig('back'):
            self.stop_cam()
            self.state=MAIN_MENU
            clear_trigs(); return

        if trig('scan') and self.phyai_label:
            # PhyAI is a demo mode - it shows the result and speaks the name,
            # same feel as a real catch, but does NOT call catchdb.record().
            # No XP, no badge progress, no region-unlock counting from here -
            # only Reverse Image Version advances actual trainer progress.
            raw = self.db.get(self.phyai_label)
            entry = {**raw, 'name': self.phyai_label} if raw else None
            if entry:
                self.scan_holder = {'entry': entry, 'status': '', 'busy': False, 'show': True}
                self.result_tab = 0
                play_ting()
                types=' and '.join(entry.get('types',[]))
                ab=' and '.join(entry.get('abilities',[])[:2]).replace('-',' ')
                mv=', '.join(m.replace('-',' ') for m in entry.get('moves',[])[:3])
                speak(f"{entry['name']}, {types} type pokemon. Abilities are {ab}. Moves include {mv}.")
                clear_trigs()
                return
        clear_trigs()

        s=self.screen
        now = time.time()
        if self.cap:
            if now - self.last_cam_read >= 0.05:
                ret, frame = self.cap.read()
                if ret:
                    frm = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.live_surf = pygame.surfarray.make_surface(
                        cv2.resize(frm,(SCREEN_W,SCREEN_H)).swapaxes(0,1))
                    # classify roughly 2x/sec - plenty responsive, keeps CPU
                    # free for everything else running on this board
                    if now - self.phyai_last_infer >= 0.5:
                        self.phyai_label, self.phyai_conf = phyai_classify(frame)
                        self.phyai_last_infer = now
                self.last_cam_read = now
            if self.live_surf is not None:
                s.blit(self.live_surf, (0,0))
        else:
            s.fill(BLACK)

        pygame.draw.rect(s, RED, (0,0,SCREEN_W,40))
        t=self.F['med'].render("PhyAI Challenge", True, WHITE)
        s.blit(t,(SCREEN_W//2-t.get_width()//2,4))

        # live label, bottom banner - green when confident, nothing when not
        if self.phyai_label:
            name = self.phyai_label.capitalize()
            pct = int(self.phyai_conf*100)
            banner = pygame.Surface((SCREEN_W, 56), pygame.SRCALPHA)
            banner.fill((0,0,0,170))
            s.blit(banner, (0, SCREEN_H-96))
            nt=self.F['big'].render(name, True, GREEN)
            s.blit(nt,(SCREEN_W//2-nt.get_width()//2, SCREEN_H-90))
            ct=self.F['tiny'].render(f"{pct}% sure - SCAN to identify", True, WHITE)
            s.blit(ct,(SCREEN_W//2-ct.get_width()//2, SCREEN_H-56))
        else:
            hint=self.F['sml'].render("Point at Bulbasaur, Charizard, Pikachu or Squirtle",
                                      True, GREY)
            s.blit(hint,(SCREEN_W//2-hint.get_width()//2, SCREEN_H-70))

        self._footer("SCAN = identify    cancel = back")

    def h_oak(self):
        """Professor Oak - a spoken Q&A between Ash (you) and Oak (Claude).

        SCAN starts recording your question; SCAN again stops it. Then, off the
        draw thread: whisper transcribes -> bubble over Ash -> Claude answers
        -> bubble over Oak -> espeak speaks it. self.oak_phase drives what's on
        screen; the heavy work runs in _oak_worker so the UI never freezes.
        """
        F=self.F; s=self.screen

        if trig('back'):
            if self.oak_phase=='recording':
                oak_record_stop()
            self.state=MAIN_MENU
            clear_trigs(); return

        if trig('scan'):
            if self.oak_phase in ('idle','done'):
                # start listening
                if oak_record_start():
                    self.oak_phase='recording'
                    self.oak_q=''; self.oak_a=''
                else:
                    self.oak_a="I couldn't open the microphone."
                    self.oak_phase='done'
            elif self.oak_phase=='recording':
                # stop and process, in the background
                self.oak_phase='thinking'
                threading.Thread(target=self._oak_worker, daemon=True).start()
        clear_trigs()

        # ---- draw ----
        s.fill(BG)
        self._title("Professor Oak")

        # two characters: Ash left, Oak right (placeholders until real art)
        t = self.catchdb.trainer()
        trainer_label = (t['name'] if t else 'TRAINER').upper()
        self._draw_oak_char(70, 250, 'ash', trainer_label)
        self._draw_oak_char(SCREEN_W-70, 250, 'oak', 'PROF. OAK')

        # Ash's speech bubble (your question)
        if self.oak_q:
            self._oak_bubble(self.oak_q, 70, 150, left=True)
        # Oak's speech bubble (the answer)
        if self.oak_a:
            self._oak_bubble(self.oak_a, SCREEN_W-70, 150, left=False)

        # status line + prompt
        status = {'idle':   'Press SCAN and ask Professor Oak a question',
                  'recording':'Listening...  press SCAN when done',
                  'thinking':'Professor Oak is thinking...',
                  'done':   'Press SCAN to ask another'}.get(self.oak_phase,'')
        col = RED if self.oak_phase=='recording' else CYAN
        st=F['sml'].render(status, True, col)
        s.blit(st,(SCREEN_W//2-st.get_width()//2, SCREEN_H-64))

        if self.oak_phase=='recording':
            # pulsing red dot
            r=int(6+3*abs(math.sin(time.time()*4)))
            pygame.draw.circle(s, RED, (SCREEN_W//2-st.get_width()//2-16, SCREEN_H-58), r)

        self._footer("SCAN = talk    cancel = back")

    def _draw_oak_char(self, cx, cy, kind, label):
        """Placeholder characters. Drop ash.png / oak.png in the folder later
        and they'll be used instead."""
        s=self.screen; F=self.F
        img = badge_image(kind, 120) if False else None  # reserved for PNGs
        png = os.path.join(BASE, f'{kind}.png')
        if os.path.exists(png):
            try:
                pic=pygame.image.load(png).convert_alpha()
                pic=pygame.transform.smoothscale(pic,(110,110))
                s.blit(pic,(cx-55,cy-55))
                lbl=F['tiny'].render(label,True,WHITE)
                s.blit(lbl,(cx-lbl.get_width()//2,cy+58))
                return
            except Exception:
                pass
        # drawn placeholder: a coloured figure
        body = (230,90,60) if kind=='ash' else (90,140,220)
        pygame.draw.circle(s, body, (cx,cy-20), 26)          # head
        pygame.draw.rect(s, body, (cx-24,cy+6,48,54), border_radius=10)  # body
        if kind=='ash':
            pygame.draw.arc(s,(255,255,255),(cx-26,cy-48,52,40),3.6,6.0,6)  # cap brim
            pygame.draw.circle(s,(220,40,40),(cx,cy-30),14)
        else:
            pygame.draw.rect(s,(240,240,240),(cx-26,cy+10,52,30),border_radius=6) # coat
            pygame.draw.circle(s,(230,230,230),(cx,cy-24),20,3)  # grey hair hint
        lbl=F['tiny'].render(label,True,WHITE)
        s.blit(lbl,(cx-lbl.get_width()//2,cy+58))

    def _oak_bubble(self, text, cx, top, left=True):
        """A speech bubble with wrapped text, tail pointing down to the speaker."""
        s=self.screen; F=self.F
        maxw=220
        words=text.split(); lines=[]; cur=''
        for w in words:
            t=(cur+' '+w).strip()
            if F['tiny'].size(t)[0]<=maxw-20: cur=t
            else: lines.append(cur); cur=w
        if cur: lines.append(cur)
        lines=lines[:6]
        lh=F['tiny'].get_height()+2
        bw=min(maxw, max((F['tiny'].size(l)[0] for l in lines), default=40)+20)
        bh=len(lines)*lh+14
        bx=cx-bw//2
        bx=max(6,min(bx,SCREEN_W-bw-6))
        by=top-bh
        pygame.draw.rect(s,(250,250,252),(bx,by,bw,bh),border_radius=10)
        pygame.draw.rect(s,(40,44,60),(bx,by,bw,bh),2,border_radius=10)
        # tail
        tx=max(bx+12,min(cx,bx+bw-12))
        pygame.draw.polygon(s,(250,250,252),[(tx-8,by+bh-1),(tx+8,by+bh-1),(tx,by+bh+12)])
        for i,l in enumerate(lines):
            s.blit(F['tiny'].render(l,True,(20,22,30)),(bx+10,by+7+i*lh))

    def _oak_worker(self):
        """Off the draw thread: transcribe -> ask Claude -> speak."""
        ok = oak_record_stop()
        q = oak_transcribe() if ok else ''
        if not q:
            self.oak_q=''
            self.oak_a="I didn't catch that - try again and speak clearly."
            self.oak_phase='done'
            return
        self.oak_q = q
        t = self.catchdb.trainer()
        # only build and send the progress briefing when the question looks
        # progress-related - keeps token cost down on ordinary questions
        progress_ctx = oak_progress_summary(self) if oak_is_progress_question(q) else None
        ans, self.oak_hist = oak_ask(q, self.oak_hist, t, progress_ctx)
        self.oak_a = ans
        self.oak_phase='done'
        speak(ans)   # respects mute; killed instantly if you press mute

    # ══════════ TRAINER (3 tabs: Info / Regions / Badges) ══════════
    def h_trainer(self):
        t = self.catchdb.trainer()
        if t is None:
            self.state = TRAINER_NEW
            self.new_step = 0
            self.new_data = {}
            self.widget = TextInput('TRAINER NAME')
            clear_trigs()
            return

        if trig('tab') or trig('right'):
            self.tr_tab = (self.tr_tab + 1) % 3
            self.tr_scroll = 0
        if trig('left'):
            self.tr_tab = (self.tr_tab - 1) % 3
            self.tr_scroll = 0
        if trig('back'):
            self.state = MAIN_MENU
            clear_trigs(); return

        if self.tr_tab == 0:
            items = ['Switch / New Trainer', 'Edit Profile']
            if trig('down'): self.tr_sel = (self.tr_sel + 1) % len(items)
            if trig('up'):   self.tr_sel = (self.tr_sel - 1) % len(items)
            if trig('select'):
                if self.tr_sel == 0:
                    self.state = TRAINER_LIST; self.tl_sel = 0
                else:
                    self.state = TRAINER_NEW; self.new_step = 0
                    self.new_data = {'edit': t['tid']}
                    self.widget = TextInput('TRAINER NAME', t['name'])
        elif self.tr_tab == 1:
            if trig('down') and self.tr_scroll < len(REGION_ORDER) - 5: self.tr_scroll += 1
            if trig('up') and self.tr_scroll > 0: self.tr_scroll -= 1
            trig('select')
        else:
            rows = (TOTAL_BADGES + 5) // 6
            if trig('down') and self.tr_scroll < len(REGION_ORDER) - 2: self.tr_scroll += 1
            if trig('up') and self.tr_scroll > 0: self.tr_scroll -= 1
            trig('select')
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        team_col = TEAM_COLORS.get(t['team'], GREY)
        pygame.draw.rect(s, team_col, (0, 0, SCREEN_W, 34))
        s.blit(F['med'].render('TRAINER', True, WHITE), (12, 6))

        # tabs
        x = 150
        for i, nm in enumerate(['Info', 'Regions', 'Badges']):
            w = F['tiny'].render(nm, True, WHITE).get_width() + 20
            pygame.draw.rect(s, RED if i == self.tr_tab else PANEL, (x, 7, w, 20),
                             border_radius=4)
            pygame.draw.rect(s, CYAN, (x, 7, w, 20), 1, border_radius=4)
            s.blit(F['tiny'].render(nm, True, WHITE), (x + 10, 10))
            x += w + 5

        if self.tr_tab == 0:
            self._trainer_info(t, team_col)
        elif self.tr_tab == 1:
            self._trainer_regions()
        else:
            self._trainer_badges()

    def _trainer_info(self, t, team_col):
        s = self.screen; F = self.F
        lvl, into, need = level_from_xp(t['xp'])

        CARD_W = 272
        pygame.draw.rect(s, PANEL, (16, 44, CARD_W, 210), border_radius=10)
        pygame.draw.rect(s, team_col, (16, 44, CARD_W, 210), 2, border_radius=10)
        draw_pokeball(s, 46, 74, 16, time.time())
        s.blit(F['name'].render(t['name'][:12], True, WHITE), (72, 64))
        s.blit(F['tiny'].render('Team ' + t['team'], True, team_col), (72, 88))

        y = 112
        for label, val in (('City', t['city'] or '-'),
                           ('Age', str(t['age'] or '-')),
                           ('Gender', t['gender'] or '-'),
                           ('Since', (t['created'] or '')[:10])):
            s.blit(F['tiny'].render(label, True, CYAN), (30, y))
            s.blit(F['sml'].render(str(val)[:12], True, WHITE), (98, y - 2))
            y += 24

        # latest badge, in the space to the right of the details
        bcx = 240
        latest = self.catchdb.latest_badge()
        pygame.draw.line(s, (60, 64, 80), (196, 108), (196, 200), 1)
        if latest:
            rg, b = latest
            draw_badge(s, bcx, 138, 26, b[2], b[3], True, b[0], rg)
            lbl = b[0].replace(' Badge', '').replace(' Trial', '').replace(' Stamp', '')
            t1 = F['tiny'].render(lbl[:10], True, WHITE)
            s.blit(t1, (bcx - t1.get_width()//2, 172))
            t2 = F['tiny'].render(rg, True, CYAN)
            s.blit(t2, (bcx - t2.get_width()//2, 186))
        else:
            first = BADGES_BY_REGION['Kanto'][0]
            draw_badge(s, bcx, 138, 26, first[2], first[3], False, first[0], 'Kanto')
            t1 = F['tiny'].render('No badges', True, GREY)
            s.blit(t1, (bcx - t1.get_width()//2, 172))
            t2 = F['tiny'].render('yet', True, GREY)
            s.blit(t2, (bcx - t2.get_width()//2, 186))
        cap = F['tiny'].render('LATEST', True, GREY)
        s.blit(cap, (bcx - cap.get_width()//2, 110))

        s.blit(F['med'].render('LEVEL %d' % lvl, True, YELLOW), (30, 216))
        bx, bw = 118, 152
        pygame.draw.rect(s, BG, (bx, 220, bw, 14), border_radius=7)
        pygame.draw.rect(s, GREEN, (bx, 220, int(bw * (into/need if need else 0)), 14),
                         border_radius=7)
        s.blit(F['tiny'].render('%d/%d' % (into, need), True, WHITE), (bx + 4, 221))

        st = self.catchdb.stats()
        pct = 100.0 * st['unique'] / 1025
        rx = 296
        s.blit(F['med'].render('PROGRESS', True, CYAN), (rx, 50))
        y = 78
        for label, val in (('Caught', '%d / 1025' % st['unique']),
                           ('Complete', '%.1f %%' % pct),
                           ('Total catches', str(st['total'])),
                           ('Total XP', str(t['xp'])),
                           ('Badges', '%d / %d' % (self.catchdb.badge_count(), TOTAL_BADGES)),
                           ('Favourites', str(len(self.catchdb.all_favs())))):
            s.blit(F['tiny'].render(label, True, GREY), (rx, y))
            s.blit(F['sml'].render(val, True, WHITE), (rx + 130, y - 2))
            y += 26

        items = ['Switch / New Trainer', 'Edit Profile']
        self._menu_items(items, self.tr_sel, 268, x0=180, w=290, gap=40)
        self._footer('tab = switch tab    enter = open    cancel = back')

    def _trainer_regions(self):
        s = self.screen; F = self.F
        ids, names = self.catchdb.caught_sets()
        s.blit(F['tiny'].render('Catch 60%% of a region to unlock its %d badges'
                                % 8, True, GREY), (16, 42))

        y = 62
        visible = 5
        for i in range(self.tr_scroll, min(self.tr_scroll + visible, len(REGION_ORDER))):
            r = REGION_ORDER[i]
            n, total, frac = region_progress(r, ids)
            target = unlock_target(r)
            unlocked = n >= target
            earned = sum(1 for b in BADGES_BY_REGION[r]
                         if badge_earned(r, b, ids, names))

            pygame.draw.rect(s, PANEL, (16, y, SCREEN_W - 32, 72), border_radius=8)
            pygame.draw.rect(s, GREEN if unlocked else GREY, (16, y, SCREEN_W - 32, 72),
                             1, border_radius=8)

            s.blit(F['med'].render(r, True, WHITE if unlocked else GREY), (28, y + 8))
            s.blit(F['tiny'].render('%d / %d caught' % (n, total), True, CYAN),
                   (28, y + 32))

            # progress bar with the 60% marker
            bx, bw = 150, 300
            pygame.draw.rect(s, BG, (bx, y + 14, bw, 16), border_radius=8)
            col = GREEN if unlocked else ORANGE
            pygame.draw.rect(s, col, (bx, y + 14, int(bw * frac), 16), border_radius=8)
            mx = bx + int(bw * BADGE_UNLOCK_PCT)
            pygame.draw.line(s, YELLOW, (mx, y + 11), (mx, y + 33), 2)
            s.blit(F['tiny'].render('%.0f%%' % (frac * 100), True, WHITE), (bx + bw + 8, y + 14))

            if unlocked:
                s.blit(F['tiny'].render('BADGES UNLOCKED  -  %d/8 earned' % earned,
                                        True, GREEN), (150, y + 40))
            else:
                s.blit(F['tiny'].render('%d more to unlock badges (need %d)' % (
                    target - n, target), True, GREY), (150, y + 40))

            # mini badges
            bxx = 470
            for b in BADGES_BY_REGION[r][:8]:
                got = badge_earned(r, b, ids, names)
                draw_badge(s, bxx, y + 36, 8, b[2], b[3], got, b[0], r)
                bxx += 20
            y += 78

        if len(REGION_ORDER) > visible:
            s.blit(F['tiny'].render('up/down = scroll   (%d-%d of %d)' % (
                self.tr_scroll + 1, min(self.tr_scroll + visible, len(REGION_ORDER)),
                len(REGION_ORDER)), True, GREY), (16, SCREEN_H - 40))
        self._footer('tab = switch tab    cancel = back')

    def _trainer_badges(self):
        s = self.screen; F = self.F
        ids, names = self.catchdb.caught_sets()
        total_earned = self.catchdb.badge_count()
        s.blit(F['tiny'].render('%d / %d badges earned' % (total_earned, TOTAL_BADGES),
                                True, CYAN), (16, 42))

        y = 60
        visible = 2
        for i in range(self.tr_scroll, min(self.tr_scroll + visible, len(REGION_ORDER))):
            r = REGION_ORDER[i]
            unlocked = badges_unlocked(r, ids)
            n, total, frac = region_progress(r, ids)

            s.blit(F['sml'].render(r, True, WHITE if unlocked else GREY), (16, y))
            if not unlocked:
                s.blit(F['tiny'].render('locked - %d/%d caught (need %d)' % (
                    n, total, unlock_target(r)), True, GREY), (80, y + 2))

            bx = 16
            yy = y + 24
            for b in BADGES_BY_REGION[r]:
                got = badge_earned(r, b, ids, names)
                draw_badge(s, bx + 26, yy + 26, 20, b[2], b[3], got, b[0], r)
                nm = b[0].replace(' Badge', '').replace(' Trial', '').replace(' Stamp', '')
                t = F['tiny'].render(nm[:9], True, WHITE if got else GREY)
                s.blit(t, (bx + 26 - t.get_width()//2, yy + 50))
                if got:
                    draw_star(s, bx + 44, yy + 10, 5, True)
                bx += 78
            y += 92

        self._footer('tab = switch tab    up/down = region    cancel = back')

    # ══════════ CREATE / EDIT TRAINER ══════════
    def h_trainer_new(self):
        w = self.widget
        steps = ['name', 'city', 'age', 'gender', 'team']

        if trig('back'):
            if self.new_step == 0:
                self.state = TRAINER if self.catchdb.trainer() else MAIN_MENU
            else:
                self.new_step -= 1
                self.widget = self._make_widget(self.new_step)
            clear_trigs(); return

        if isinstance(w, TextInput):
            if trig('up'):    w.move(-1, 0)
            if trig('down'):  w.move(1, 0)
            if trig('left'):  w.move(0, -1)
            if trig('right'): w.move(0, 1)
            if trig('select'): w.press()
        else:
            if trig('up'):   w.move(-1) if isinstance(w, ChoiceInput) else w.move(1)
            if trig('down'): w.move(1) if isinstance(w, ChoiceInput) else w.move(-1)
            if trig('select'): w.done = True
        trig('tab'); trig('scan'); clear_trigs()

        if w.done:
            key = steps[self.new_step]
            if isinstance(w, TextInput):
                self.new_data[key] = w.value.strip() or ('Trainer' if key == 'name' else '')
            elif isinstance(w, NumberInput):
                self.new_data[key] = w.value
            else:
                self.new_data[key] = w.options[w.sel]
            self.new_step += 1
            if self.new_step >= len(steps):
                d = self.new_data
                nm  = d.get('name') or 'Trainer'
                cty = d.get('city', '')
                age = d.get('age', 0)
                gen = d.get('gender', 'Other')
                tm  = d.get('team', 'Red')
                if 'edit' in d:
                    self.catchdb.update_trainer(d['edit'], nm, cty, age, gen, tm)
                else:
                    self.catchdb.create_trainer(nm, cty, age, gen, tm)
                self.state = TRAINER
                self.tr_sel = 0
            else:
                self.widget = self._make_widget(self.new_step)
            return

        w.draw(self.screen, self.F)
        step_txt = self.F['tiny'].render(
            'step %d of %d' % (self.new_step + 1, len(steps)), True, GREY)
        self.screen.blit(step_txt, (SCREEN_W - step_txt.get_width() - 12, 14))

    def _make_widget(self, step):
        d = self.new_data or {}
        if step == 0: return TextInput('TRAINER NAME', d.get('name', ''))
        if step == 1: return TextInput('CITY', d.get('city', ''))
        if step == 2: return NumberInput('AGE', d.get('age', 15))
        if step == 3:
            opts = ['Male', 'Female', 'Other']
            v = opts.index(d['gender']) if d.get('gender') in opts else 0
            return ChoiceInput('GENDER', opts, v)
        opts = TEAMS
        v = opts.index(d['team']) if d.get('team') in opts else 0
        return ChoiceInput('CHOOSE YOUR TEAM', opts, v, TEAM_COLORS)

    # ══════════ TRAINER LIST / SWITCH ══════════
    def h_trainer_list(self):
        ts = self.catchdb.all_trainers()
        items = ts + [{'tid': None, 'name': '+ New Trainer', 'team': '', 'xp': 0}]
        if trig('down'): self.tl_sel = (self.tl_sel + 1) % len(items)
        if trig('up'):   self.tl_sel = (self.tl_sel - 1) % len(items)
        if trig('select'):
            pick = items[self.tl_sel]
            if pick['tid'] is None:
                self.state = TRAINER_NEW; self.new_step = 0
                self.new_data = {}; self.widget = TextInput('TRAINER NAME')
            else:
                self.catchdb.set_active(pick['tid'])
                self.state = TRAINER; self.tr_sel = 0
        if trig('tab') and items[self.tl_sel]['tid'] is not None and len(ts) > 1:
            self.confirm = {'msg': 'Delete trainer %s?' % items[self.tl_sel]['name'],
                            'sub': 'All their catches will be lost.',
                            'action': ('del_trainer', items[self.tl_sel]['tid']),
                            'back': TRAINER_LIST}
            self.state = CONFIRM; self.cf_sel = 1
        if trig('back'): self.state = TRAINER
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        pygame.draw.rect(s, RED, (0, 0, SCREEN_W, 36))
        s.blit(F['med'].render('TRAINERS', True, WHITE), (12, 7))

        y = 60
        for i, t in enumerate(items):
            sel = i == self.tl_sel
            if sel:
                pygame.draw.rect(s, HILITE, (30, y - 4, SCREEN_W - 60, 46),
                                 border_radius=8)
                draw_pokeball(s, 52, y + 19, 11, time.time())
            active = (t['tid'] is not None and t['tid'] == self.catchdb.tid)
            col = TEAM_COLORS.get(t['team'], WHITE)
            s.blit(F['med'].render(t['name'][:16], True, col if t['tid'] else CYAN),
                   (80, y + 8))
            if t['tid'] is not None:
                lvl = level_from_xp(t['xp'])[0]
                s.blit(F['tiny'].render('Lv %d  %s' % (lvl, t['team']), True, GREY),
                       (300, y + 14))
                if active:
                    s.blit(F['tiny'].render('ACTIVE', True, GREEN), (SCREEN_W - 90, y + 14))
            y += 52

        self._footer('enter = switch    tab = delete    cancel = back')

    # ══════════ HOW TO PLAY - MODE PICKER ══════════
    # ══════════════════════════════════════════════════════════
    #  MORE GAMES  -  a little arcade that runs on the Pokedex.
    #  Three native pygame games (Flappy, Tetris, Snake) play right
    #  on this screen using the keypad, plus a launcher for real DOOM.
    #  Every game is driven by the same edge-triggered buttons the rest
    #  of the app uses (trig()), so no new input plumbing is needed.
    # ══════════════════════════════════════════════════════════
    def h_more_games(self):
        items = ['Flappy Bird', 'Tetris', 'Snake', 'DOOM  (yes, really)', 'Back']
        if trig('down'): self.mg_sel = (self.mg_sel + 1) % len(items)
        if trig('up'):   self.mg_sel = (self.mg_sel - 1) % len(items)
        if trig('select'):
            if   self.mg_sel == 0: self._flappy_init();  self.state = GAME_FLAPPY
            elif self.mg_sel == 1: self._tetris_init();  self.state = GAME_TETRIS
            elif self.mg_sel == 2: self._snake_init();   self.state = GAME_SNAKE
            elif self.mg_sel == 3: self._launch_doom()
            else:                  self.state = MAIN_MENU
        if trig('back'): self.state = MAIN_MENU
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        self._title('MORE GAMES')
        self._menu_items(items, self.mg_sel, 96, gap=52)
        self._footer('enter = play    cancel = back')

    # ---- DOOM: launch the real thing as an external program ----
    # DOOM runs as a timed demo: we launch the real engine, let its built-in
    # attract/demo loop play for DOOM_DEMO_SECS, then close it and come back.
    # No key injection needed - it is a "yes, it really runs DOOM" showcase
    # that always returns cleanly on its own.
    DOOM_DEMO_SECS = 25

    def _launch_doom(self):
        """Play a short DOOM demo, then automatically return to the games menu.
        The real chocolate-doom engine renders its own attract demo; we time it
        and kill it, so the Pokedex always comes back without any input."""
        import shutil, subprocess
        engine = None
        for cand in ('chocolate-doom', 'prboom-plus', 'prboom'):
            if shutil.which(cand):
                engine = cand; break
        if engine is None:
            self.popup = ['DOOM not installed', 'run the setup command', 'in the guide']
            self.popup_until = time.time() + 4.0
            return

        # free the camera so DOOM has the machine to itself
        try: self.stop_cam()
        except Exception: pass

        # draw a quick "LOADING DOOM" frame so the handoff is not a black flash
        s = self.screen; s.fill((20, 0, 0))
        t1 = self.F['big'].render('LOADING DOOM...', True, (230, 60, 40))
        s.blit(t1, (SCREEN_W//2 - t1.get_width()//2, 200))
        t2 = self.F['sml'].render('yes, it really runs DOOM', True, YELLOW)
        s.blit(t2, (SCREEN_W//2 - t2.get_width()//2, 250))
        self._present()   # push this frame to the display before DOOM takes over

        proc = None
        try:
            # -nomouse keeps DOOM from grabbing the pointer; it plays its demo.
            proc = subprocess.Popen([engine, '-nomouse'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + self.DOOM_DEMO_SECS
            while time.time() < deadline:
                if proc.poll() is not None:
                    break            # DOOM exited early on its own
                # let the user cut it short with BACK / MUTE
                if trig('back') or trig('mute'):
                    break
                time.sleep(0.1)
        except Exception as e:
            self.popup = ['Could not start DOOM', str(e)[:28]]
            self.popup_until = time.time() + 4.0
        finally:
            # always shut DOOM down and reclaim the screen
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=2)
                except Exception:
                    proc.kill()
            import subprocess as _sp
            _sp.run(['pkill', '-9', 'chocolate-doom'], stderr=_sp.DEVNULL)
            clear_trigs()

        self.popup = ['DOOM demo complete', 'and yes - it runs DOOM']
        self.popup_until = time.time() + 3.0
        self.state = MORE_GAMES

    # ══════════════════ FLAPPY BIRD ══════════════════
    def _flappy_init(self):
        self.fb = {
            'y': SCREEN_H / 2, 'vy': 0.0, 'pipes': [], 'spawn': 0,
            'score': 0, 'best': getattr(self, '_fb_best', 0),
            'dead': False, 'started': False,
        }

    def h_game_flappy(self):
        g = self.fb
        FLAP, GRAV, GAP, SPEED, PW = -6.2, 0.45, 150, 3.2, 52
        BIRD_X = 120

        if trig('back'):
            self.state = MORE_GAMES; clear_trigs(); return
        # SCAN or SELECT = flap (either button, whichever is comfy)
        flap = trig('scan') or trig('select')
        trig('up'); trig('down'); trig('left'); trig('right'); trig('tab')

        if g['dead']:
            if flap: self._flappy_init()
            clear_trigs()
        else:
            if flap:
                g['started'] = True
                g['vy'] = FLAP
            if g['started']:
                g['vy'] += GRAV
                g['y']  += g['vy']
                g['spawn'] -= 1
                if g['spawn'] <= 0:
                    g['spawn'] = 92
                    import random as _r
                    cy = _r.randint(110, SCREEN_H - 110)
                    g['pipes'].append({'x': SCREEN_W + 10, 'cy': cy, 'scored': False})
                for p in g['pipes']:
                    p['x'] -= SPEED
                    if not p['scored'] and p['x'] + PW < BIRD_X:
                        p['scored'] = True; g['score'] += 1
                        if g['score'] > g['best']:
                            g['best'] = g['score']; self._fb_best = g['best']
                g['pipes'] = [p for p in g['pipes'] if p['x'] > -PW]
                # collisions
                if g['y'] < 0 or g['y'] > SCREEN_H:
                    g['dead'] = True
                for p in g['pipes']:
                    if BIRD_X + 14 > p['x'] and BIRD_X - 14 < p['x'] + PW:
                        if g['y'] - 14 < p['cy'] - GAP/2 or g['y'] + 14 > p['cy'] + GAP/2:
                            g['dead'] = True
            clear_trigs()

        s = self.screen
        s.fill((78, 168, 220))  # sky
        for p in g['pipes']:
            pygame.draw.rect(s, (60, 180, 75), (p['x'], 0, PW, p['cy'] - GAP//2))
            pygame.draw.rect(s, (60, 180, 75), (p['x'], p['cy'] + GAP//2, PW, SCREEN_H))
            pygame.draw.rect(s, (40, 140, 55), (p['x'], 0, PW, p['cy'] - GAP//2), 3)
            pygame.draw.rect(s, (40, 140, 55), (p['x'], p['cy'] + GAP//2, PW, SCREEN_H), 3)
        pygame.draw.rect(s, (222, 184, 90), (0, SCREEN_H - 24, SCREEN_W, 24))
        pygame.draw.circle(s, YELLOW, (BIRD_X, int(g['y'])), 15)
        pygame.draw.circle(s, (30, 30, 30), (BIRD_X + 6, int(g['y']) - 4), 3)
        pygame.draw.polygon(s, ORANGE, [(BIRD_X + 12, int(g['y'])),
                            (BIRD_X + 24, int(g['y']) - 4), (BIRD_X + 24, int(g['y']) + 4)])
        s.blit(self.F['dbig'].render(str(g['score']), True, WHITE), (SCREEN_W//2 - 8, 20))
        if not g['started']:
            t = self.F['med'].render('SCAN / SELECT to flap', True, WHITE)
            s.blit(t, (SCREEN_W//2 - t.get_width()//2, SCREEN_H//2 + 40))
        if g['dead']:
            self._game_over(s, g['score'], g['best'])
        self._footer('scan/select = flap    cancel = back')

    # ══════════════════ TETRIS ══════════════════
    def _tetris_init(self):
        self.tet = {
            'grid': [[0]*10 for _ in range(20)], 'piece': None, 'px': 0, 'py': 0,
            'rot': 0, 'kind': 0, 'fall': 0, 'score': 0, 'lines': 0,
            'dead': False, 'best': getattr(self, '_tet_best', 0),
        }
        self._tetris_new_piece()

    TET_SHAPES = [
        [[1,1,1,1]],                     # I
        [[1,1],[1,1]],                   # O
        [[0,1,0],[1,1,1]],               # T
        [[1,0,0],[1,1,1]],               # J
        [[0,0,1],[1,1,1]],               # L
        [[0,1,1],[1,1,0]],               # S
        [[1,1,0],[0,1,1]],               # Z
    ]
    TET_COLS = [(80,200,235),(245,205,60),(190,110,205),(70,110,220),
                (240,150,50),(70,200,90),(220,70,70)]

    def _tetris_rotate(self, shape):
        return [list(row) for row in zip(*shape[::-1])]

    def _tetris_collide(self, shape, px, py):
        g = self.tet['grid']
        for r, row in enumerate(shape):
            for c, v in enumerate(row):
                if not v: continue
                x, y = px + c, py + r
                if x < 0 or x >= 10 or y >= 20: return True
                if y >= 0 and g[y][x]: return True
        return False

    def _tetris_new_piece(self):
        import random as _r
        t = self.tet
        t['kind'] = _r.randint(0, 6)
        t['piece'] = [list(row) for row in self.TET_SHAPES[t['kind']]]
        t['px'] = 3; t['py'] = -len(t['piece'])
        if self._tetris_collide(t['piece'], t['px'], 0):
            t['dead'] = True

    def _tetris_lock(self):
        t = self.tet; g = t['grid']
        for r, row in enumerate(t['piece']):
            for c, v in enumerate(row):
                if v and t['py'] + r >= 0:
                    g[t['py'] + r][t['px'] + c] = t['kind'] + 1
        # clear full lines
        newg = [row for row in g if not all(row)]
        cleared = 20 - len(newg)
        if cleared:
            t['lines'] += cleared
            t['score'] += (0, 40, 100, 300, 1200)[cleared]
            if t['score'] > t['best']:
                t['best'] = t['score']; self._tet_best = t['best']
            newg = [[0]*10 for _ in range(cleared)] + newg
        t['grid'] = newg
        self._tetris_new_piece()

    def h_game_tetris(self):
        t = self.tet
        if trig('back'):
            self.state = MORE_GAMES; clear_trigs(); return
        if t['dead']:
            if trig('select') or trig('scan'): self._tetris_init()
            clear_trigs()
        else:
            # tap controls: left/right move, up rotate, down soft-drop one row
            if trig('left')  and not self._tetris_collide(t['piece'], t['px']-1, t['py']): t['px'] -= 1
            if trig('right') and not self._tetris_collide(t['piece'], t['px']+1, t['py']): t['px'] += 1
            if trig('up'):
                rot = self._tetris_rotate(t['piece'])
                if not self._tetris_collide(rot, t['px'], t['py']): t['piece'] = rot
            drop = trig('down')
            trig('scan'); trig('select'); trig('tab')
            # gravity
            t['fall'] += 1
            step = 2 if drop else 14   # ~ every 14 frames, faster on soft-drop
            if t['fall'] >= step:
                t['fall'] = 0
                if not self._tetris_collide(t['piece'], t['px'], t['py']+1):
                    t['py'] += 1
                else:
                    self._tetris_lock()
            clear_trigs()

        s = self.screen; s.fill(BLACK)
        CELL = 20; OX = SCREEN_W//2 - 5*CELL; OY = 30
        pygame.draw.rect(s, PANEL, (OX-3, OY-3, 10*CELL+6, 20*CELL+6), border_radius=4)
        g = t['grid']
        for r in range(20):
            for c in range(10):
                if g[r][c]:
                    col = self.TET_COLS[g[r][c]-1]
                    pygame.draw.rect(s, col, (OX+c*CELL, OY+r*CELL, CELL-1, CELL-1))
        if not t['dead']:
            for r, row in enumerate(t['piece']):
                for c, v in enumerate(row):
                    if v and t['py']+r >= 0:
                        pygame.draw.rect(s, self.TET_COLS[t['kind']],
                            (OX+(t['px']+c)*CELL, OY+(t['py']+r)*CELL, CELL-1, CELL-1))
        s.blit(self.F['med'].render('Score %d'%t['score'], True, WHITE), (OX+10*CELL+16, 40))
        s.blit(self.F['sml'].render('Lines %d'%t['lines'], True, GREY), (OX+10*CELL+16, 70))
        s.blit(self.F['sml'].render('Best %d'%t['best'], True, YELLOW), (OX+10*CELL+16, 92))
        if t['dead']:
            self._game_over(s, t['score'], t['best'])
        self._footer('left/right move  up rotate  down drop  cancel back')

    # ══════════════════ SNAKE ══════════════════
    def _snake_init(self):
        import random as _r
        self.snk = {
            'body': [(5, 10), (4, 10), (3, 10)], 'dir': (1, 0), 'ndir': (1, 0),
            'food': (14, 10), 'grow': 0, 'move': 0, 'score': 0,
            'dead': False, 'best': getattr(self, '_snk_best', 0),
        }

    def _snake_place_food(self):
        import random as _r
        g = self.snk
        while True:
            f = (_r.randint(0, self._SNK_W-1), _r.randint(0, self._SNK_H-1))
            if f not in g['body']:
                g['food'] = f; return

    _SNK_W = 24; _SNK_H = 18

    def h_game_snake(self):
        g = self.snk
        if trig('back'):
            self.state = MORE_GAMES; clear_trigs(); return
        if g['dead']:
            if trig('select') or trig('scan'): self._snake_init()
            clear_trigs()
        else:
            # queue a direction; can't reverse straight back
            dx, dy = g['dir']
            if trig('up')    and dy == 0: g['ndir'] = (0, -1)
            if trig('down')  and dy == 0: g['ndir'] = (0, 1)
            if trig('left')  and dx == 0: g['ndir'] = (-1, 0)
            if trig('right') and dx == 0: g['ndir'] = (1, 0)
            trig('scan'); trig('select'); trig('tab')
            g['move'] += 1
            if g['move'] >= 6:   # snake steps every 6 frames (~5/sec at 30fps)
                g['move'] = 0
                g['dir'] = g['ndir']
                hx, hy = g['body'][0]
                nh = (hx + g['dir'][0], hy + g['dir'][1])
                if (nh[0] < 0 or nh[0] >= self._SNK_W or nh[1] < 0 or
                        nh[1] >= self._SNK_H or nh in g['body']):
                    g['dead'] = True
                else:
                    g['body'].insert(0, nh)
                    if nh == g['food']:
                        g['score'] += 1
                        if g['score'] > g['best']:
                            g['best'] = g['score']; self._snk_best = g['best']
                        self._snake_place_food()
                    else:
                        g['body'].pop()
            clear_trigs()

        s = self.screen; s.fill((18, 26, 40))
        CELL = 20; OX = (SCREEN_W - self._SNK_W*CELL)//2; OY = 40
        pygame.draw.rect(s, PANEL, (OX-3, OY-3, self._SNK_W*CELL+6, self._SNK_H*CELL+6), border_radius=4)
        fx, fy = g['food']
        pygame.draw.circle(s, RED, (OX+fx*CELL+CELL//2, OY+fy*CELL+CELL//2), CELL//2-2)
        for i, (bx, by) in enumerate(g['body']):
            col = GREEN if i else (120, 240, 140)
            pygame.draw.rect(s, col, (OX+bx*CELL+1, OY+by*CELL+1, CELL-2, CELL-2), border_radius=4)
        s.blit(self.F['med'].render('Score %d'%g['score'], True, WHITE), (OX, 10))
        s.blit(self.F['sml'].render('Best %d'%g['best'], True, YELLOW), (SCREEN_W-110, 14))
        if g['dead']:
            self._game_over(s, g['score'], g['best'])
        self._footer('d-pad = steer    cancel = back')

    # ---- shared game-over overlay ----
    def _game_over(self, s, score, best):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170)); s.blit(ov, (0, 0))
        t1 = self.F['big'].render('GAME OVER', True, RED)
        s.blit(t1, (SCREEN_W//2 - t1.get_width()//2, 150))
        t2 = self.F['dmed'].render('Score %d    Best %d' % (score, best), True, WHITE)
        s.blit(t2, (SCREEN_W//2 - t2.get_width()//2, 205))
        t3 = self.F['sml'].render('SCAN / SELECT = play again    cancel = menu', True, YELLOW)
        s.blit(t3, (SCREEN_W//2 - t3.get_width()//2, 250))

    def h_help_menu(self):
        items = ['Reverse Image Version', 'PhyAI Challenge', 'Back']
        if trig('down'): self.help_sel = (self.help_sel + 1) % len(items)
        if trig('up'):   self.help_sel = (self.help_sel - 1) % len(items)
        if trig('select'):
            if self.help_sel == 0:
                self.state = MANUAL; self.man_which = 'riv'; self.man_page = 0
            elif self.help_sel == 1:
                self.state = MANUAL; self.man_which = 'phyai'; self.man_page = 0
            else:
                self.state = MAIN_MENU
        if trig('back'): self.state = MAIN_MENU
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        self._title('HOW TO PLAY')
        sub = F['tiny'].render('Two ways to play. Pick one to read about it.',
                               True, GREY)
        s.blit(sub, (SCREEN_W//2 - sub.get_width()//2, 64))

        self._menu_items(items, self.help_sel, 120, gap=52)

        blurb = {0: 'Camera + Google Lens. All 1025 pokemon. Needs wifi.',
                 1: 'On-device AI. No wifi, no quota. Coming soon.',
                 2: ''}.get(self.help_sel, '')
        if blurb:
            b = F['tiny'].render(blurb, True, CYAN)
            s.blit(b, (SCREEN_W//2 - b.get_width()//2, SCREEN_H - 70))
        self._footer('enter = read    cancel = back')

    # ══════════ IN-APP MANUAL ══════════
    def h_manual(self):
        title_txt, pages = MANUALS[self.man_which]
        if trig('right') or trig('down'):
            self.man_page = min(self.man_page + 1, len(pages) - 1)
        if trig('left') or trig('up'):
            self.man_page = max(self.man_page - 1, 0)
        if trig('back'):
            self.state = HELP_MENU
            clear_trigs(); return
        trig('select'); trig('tab'); trig('scan')
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        pygame.draw.rect(s, RED, (0, 0, SCREEN_W, 34))
        s.blit(F['med'].render(title_txt, True, WHITE), (12, 6))
        s.blit(F['tiny'].render('%d / %d' % (self.man_page + 1, len(pages)),
                                True, WHITE), (SCREEN_W - 50, 12))

        title, lines = pages[self.man_page]
        s.blit(F['name'].render(title, True, YELLOW), (20, 48))
        y = 84
        for ln in lines:
            if ln.startswith('* '):
                pygame.draw.circle(s, CYAN, (30, y + 8), 3)
                for w in self._wrap(ln[2:], F['sml'], SCREEN_W - 70):
                    s.blit(F['sml'].render(w, True, WHITE), (42, y)); y += 20
            elif ln == '':
                y += 10
            else:
                for w in self._wrap(ln, F['sml'], SCREEN_W - 50):
                    s.blit(F['sml'].render(w, True, WHITE), (24, y)); y += 20
            if y > SCREEN_H - 50:
                break

        self._footer('left/right = page    cancel = back')

    # ══════════ SEARCH ══════════
    def h_search(self):
        w = self.widget
        if trig('back'):
            self.state = RIV_MENU; clear_trigs(); return
        if trig('up'):    w.move(-1, 0)
        if trig('down'):  w.move(1, 0)
        if trig('left'):  w.move(0, -1)
        if trig('right'): w.move(0, 1)
        if trig('select'): w.press()
        trig('tab'); trig('scan'); clear_trigs()

        if w.done:
            q = w.value.strip().lower()
            if q:
                hits = [pid for pid in sorted(self.by_id)
                        if self.by_id[pid]['name'].startswith(q)]
                if not hits:
                    hits = [pid for pid in sorted(self.by_id)
                            if q in self.by_id[pid]['name']]
                if hits:
                    self.search_hits = hits
                    self.detail_pid = hits[0]
                    self.detail_from = RIV_MENU
                    self.state = DETAIL
                    self.result_tab = 0
                    return
            w.done = False
            self.search_msg = 'No match for "%s"' % w.value.strip()
            return

        w.draw(self.screen, self.F)
        if self.search_msg:
            t = self.F['sml'].render(self.search_msg, True, RED)
            self.screen.blit(t, (SCREEN_W // 2 - t.get_width() // 2, 88))

    # ══════════ FAVOURITES ══════════
    def h_favs(self):
        favs = self.catchdb.all_favs()
        visible = 8
        if favs:
            if trig('down'):
                self.fav_sel = min(self.fav_sel + 1, len(favs) - 1)
                if self.fav_sel >= self.fav_scroll + visible: self.fav_scroll += 1
            if trig('up'):
                self.fav_sel = max(self.fav_sel - 1, 0)
                if self.fav_sel < self.fav_scroll: self.fav_scroll -= 1
            if trig('select'):
                self.detail_pid = favs[self.fav_sel]
                self.detail_from = FAVS; self.state = DETAIL; self.result_tab = 0
            if trig('tab'):
                self.catchdb.toggle_fav(favs[self.fav_sel])
                self.fav_sel = max(0, min(self.fav_sel, len(self.catchdb.all_favs()) - 1))
        if trig('back'): self.state = RIV_MENU
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        pygame.draw.rect(s, RED, (0, 0, SCREEN_W, 36))
        s.blit(F['med'].render('FAVOURITES', True, WHITE), (12, 7))
        s.blit(F['sml'].render('%d starred' % len(favs), True, CYAN), (SCREEN_W - 110, 10))

        if not favs:
            s.blit(F['sml'].render('No favourites yet.', True, GREY), (16, 90))
            s.blit(F['tiny'].render('Open any Pokemon and press enter to star it.',
                                    True, GREY), (16, 116))
            self._footer('cancel = back'); return

        y = 50
        for i in range(self.fav_scroll, min(self.fav_scroll + visible, len(favs))):
            pid = favs[i]; e = self.by_id[pid]
            sel = i == self.fav_sel
            if sel:
                pygame.draw.rect(s, HILITE, (12, y - 2, SCREEN_W - 24, 42),
                                 border_radius=6)
            img = poke_img(pid, 36)
            if img: s.blit(img, (20, y))
            draw_star(s, 62, y + 18, 8, True)
            caught = self.catchdb.get(pid)
            col = GREEN if caught else WHITE
            s.blit(F['sml'].render('#%04d  %s' % (pid, e['name'].title()), True, col),
                   (82, y + 10))
            for ti, t in enumerate(e.get('types', [])[:2]):
                tc = TYPE_COLORS.get(t, GREY)
                b = F['tiny'].render(t.upper(), True, WHITE)
                pygame.draw.rect(s, tc, (300 + ti * 76, y + 8, b.get_width() + 12, 18),
                                 border_radius=9)
                s.blit(b, (306 + ti * 76, y + 10))
            y += 44

        self._footer('enter = open    tab = unstar    cancel = back')

    # ══════════ CATCH LOG ══════════
    def h_log(self):
        rows = self.catchdb.recent_log(200)
        visible = 9
        if rows:
            if trig('down') and self.log_scroll < len(rows) - visible: self.log_scroll += 1
            if trig('up') and self.log_scroll > 0: self.log_scroll -= 1
        if trig('back'): self.state = RIV_MENU
        trig('select'); trig('tab'); clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        pygame.draw.rect(s, RED, (0, 0, SCREEN_W, 36))
        s.blit(F['med'].render('CATCH LOG', True, WHITE), (12, 7))
        s.blit(F['sml'].render('%d catches' % len(rows), True, CYAN), (SCREEN_W - 110, 10))

        if not rows:
            s.blit(F['sml'].render('Nothing caught yet.', True, GREY), (16, 90))
            self._footer('cancel = back'); return

        y = 50
        for i in range(self.log_scroll, min(self.log_scroll + visible, len(rows))):
            r = rows[i]
            if i % 2 == 0:
                pygame.draw.rect(s, PANEL, (12, y - 2, SCREEN_W - 24, 40),
                                 border_radius=4)
            img = poke_img(r['pid'], 32)
            if img: s.blit(img, (18, y + 2))
            s.blit(F['sml'].render('#%04d  %s' % (r['pid'], r['name'].title()),
                                   True, WHITE), (60, y + 10))
            s.blit(F['tiny'].render(r['ts'], True, GREY), (SCREEN_W - 130, y + 12))
            y += 42

        self._footer('up/down = scroll    cancel = back')

    # ══════════ DATA / RESET ══════════
    def h_data_menu(self):
        items = ['Erase my catches', 'Erase EVERYTHING', 'Back']
        if trig('down'): self.dm_sel = (self.dm_sel + 1) % len(items)
        if trig('up'):   self.dm_sel = (self.dm_sel - 1) % len(items)
        if trig('select'):
            if self.dm_sel == 0:
                t = self.catchdb.trainer()
                self.confirm = {
                    'msg': 'Erase all catches for %s?' % (t['name'] if t else '-'),
                    'sub': 'Catches, XP, badges and favourites reset to zero.',
                    'action': ('wipe_current', None), 'back': DATA_MENU}
                self.state = CONFIRM; self.cf_sel = 1
            elif self.dm_sel == 1:
                self.confirm = {
                    'msg': 'Erase EVERYTHING?',
                    'sub': 'Every trainer, every catch, every badge. Gone.',
                    'action': ('wipe_all', None), 'back': DATA_MENU}
                self.state = CONFIRM; self.cf_sel = 1
            else:
                self.state = MAIN_MENU
        if trig('back'): self.state = MAIN_MENU
        clear_trigs()

        s = self.screen
        s.fill(BG)
        self._title('DATA')
        st = self.catchdb.stats()
        t = self.catchdb.trainer()
        info = '%s  -  %d caught, %d total' % (
            t['name'] if t else 'no trainer', st['unique'], st['total'])
        ti = self.F['tiny'].render(info, True, GREY)
        s.blit(ti, (SCREEN_W // 2 - ti.get_width() // 2, 62))
        self._menu_items(items, self.dm_sel, 130)
        self._footer('enter = choose    cancel = back')

    # ══════════ CONFIRM ══════════
    def h_confirm(self):
        c = self.confirm
        if trig('left') or trig('right') or trig('up') or trig('down'):
            self.cf_sel = 1 - self.cf_sel
        if trig('back'):
            self.state = c['back']; clear_trigs(); return
        if trig('select'):
            if self.cf_sel == 0:
                kind, arg = c['action']
                if kind == 'wipe_current':
                    self.catchdb.wipe_current()
                elif kind == 'wipe_all':
                    self.catchdb.wipe_everything()
                    self.state = MAIN_MENU; self.main_sel = 0
                    clear_trigs(); return
                elif kind == 'del_trainer':
                    self.catchdb.delete_trainer(arg)
                    self.tl_sel = 0
                elif kind == 'exit':
                    self.running = False
                    clear_trigs(); return
            self.state = c['back']
        clear_trigs()

        s = self.screen; F = self.F
        s.fill(BG)
        pygame.draw.rect(s, RED, (0, 0, SCREEN_W, 36))
        s.blit(F['med'].render('CONFIRM', True, WHITE), (12, 7))

        pygame.draw.rect(s, PANEL, (60, 120, SCREEN_W - 120, 160), border_radius=10)
        pygame.draw.rect(s, RED, (60, 120, SCREEN_W - 120, 160), 2, border_radius=10)

        m = F['med'].render(c['msg'], True, WHITE)
        s.blit(m, (SCREEN_W // 2 - m.get_width() // 2, 145))
        for i, line in enumerate(self._wrap(c['sub'], F['tiny'], SCREEN_W - 160)):
            t = F['tiny'].render(line, True, GREY)
            s.blit(t, (SCREEN_W // 2 - t.get_width() // 2, 178 + i * 16))
        w = F['tiny'].render('This cannot be undone.', True, RED)
        s.blit(w, (SCREEN_W // 2 - w.get_width() // 2, 218))

        for i, label in enumerate(['YES', 'NO']):
            x = 150 + i * 200
            sel = i == self.cf_sel
            col = RED if (sel and i == 0) else (GREEN if sel else PANEL)
            pygame.draw.rect(s, col, (x, 244, 140, 30), border_radius=6)
            pygame.draw.rect(s, WHITE if sel else GREY, (x, 244, 140, 30), 1,
                             border_radius=6)
            t = F['sml'].render(label, True, WHITE)
            s.blit(t, (x + 70 - t.get_width() // 2, 250))

        self._footer('left/right = choose    enter = confirm    cancel = back')

    # ── shared UI helpers ──
    def _title(self, text):
        s=self.screen
        pygame.draw.rect(s,RED,(0,0,SCREEN_W,50))
        t=self.F['big'].render(text,True,WHITE)
        s.blit(t,(SCREEN_W//2-t.get_width()//2,10))

    def _menu_items(self, items, sel, y0, x0=90, w=470, gap=54):
        s=self.screen; F=self.F; y=y0
        for i,it in enumerate(items):
            if i==sel:
                pygame.draw.rect(s,HILITE,(x0,y-8,w,46),border_radius=10)
                draw_pokeball(s, x0+26, y+13, 13, time.time())
            col=YELLOW if i==sel else WHITE
            s.blit(F['dmed'].render(it,True,col),(x0+52,y)); y+=gap

    def _draw_mute(self):
        """Small speaker-off icon top-right whenever sound is muted. Nothing
        drawn when sound is on, so it stays out of the way."""
        if not self.muted:
            return
        s = self.screen
        x, y = SCREEN_W-30, 12
        # speaker body
        pygame.draw.polygon(s, WHITE, [(x,y+4),(x+5,y+4),(x+10,y-1),(x+10,y+13),(x+5,y+8),(x,y+8)])
        # the "off" slash
        pygame.draw.line(s, RED, (x-2,y-2), (x+16,y+16), 3)

    def _draw_popup(self):
        """Transient XP / level / badge toast after a catch."""
        if not self.popup or time.time() > self.popup_until:
            self.popup=None; return
        s=self.screen; F=self.F
        n=len(self.popup)
        h=26*n+16
        w=250
        x=SCREEN_W-w-14; y=48
        box=pygame.Surface((w,h), pygame.SRCALPHA)
        box.fill((0,0,0,205))
        s.blit(box,(x,y))
        pygame.draw.rect(s, YELLOW, (x,y,w,h), 2, border_radius=6)
        yy=y+10
        for line in self.popup:
            col = GREEN if line.startswith('+') else YELLOW
            t=F['sml'].render(line, True, col)
            s.blit(t,(x+w//2-t.get_width()//2, yy)); yy+=26

    def _footer(self, text):
        s=self.screen
        t=self.F['tiny'].render(text,True,GREY)
        s.blit(t,(SCREEN_W//2-t.get_width()//2,SCREEN_H-24))

    def _present(self):
        """Composite the off-screen canvas into the bezel-visible area and flip.
        Used by the main loop and by the DOOM handoff frame."""
        self._display.fill((0, 0, 0))
        if self._visible.width == SCREEN_W and self._visible.height == SCREEN_H:
            self._display.blit(self.screen, (0, 0))
        else:
            scaled = pygame.transform.smoothscale(
                self.screen, (self._visible.width, self._visible.height))
            self._display.blit(scaled, (self._visible.x, self._visible.y))
        pygame.display.flip()

    def _wrap(self, text, font, maxw):
        words=text.split(); lines=[]; line=""
        for w in words:
            test=(line+" "+w).strip()
            if font.size(test)[0]<=maxw: line=test
            else:
                if line: lines.append(line)
                line=w
        if line: lines.append(line)
        return lines

if __name__=="__main__":
    App().run()
