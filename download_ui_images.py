"""
download_ui_images.py - Download all 1025 official Pokemon artwork PNGs
(transparent) into ~/pokedex/ui_images/. Skips files already present.

Run: python3 ~/pokedex/download_ui_images.py
"""

import requests, os
from PIL import Image
from io import BytesIO

UI_DIR = os.path.expanduser('~/pokedex/ui_images')
os.makedirs(UI_DIR, exist_ok=True)

total = 1025
for i in range(1, total + 1):
    path = f'{UI_DIR}/{i}.png'
    if os.path.exists(path):
        continue
    try:
        url = (f'https://raw.githubusercontent.com/PokeAPI/sprites/master/'
               f'sprites/pokemon/other/official-artwork/{i}.png')
        r = requests.get(url, timeout=10)
        img = Image.open(BytesIO(r.content)).convert('RGBA')
        img.save(path)
        print(f'{i}/{total}', end='\r')
    except Exception as e:
        print(f'\nError {i}: {e}')
print('\nDone!')
