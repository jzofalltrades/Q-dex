"""
build_db.py - Full Pokemon database for all 1025.
Fetches: id, types, abilities, moves, stats, genus, height, weight,
description, evolution chain, region.
Saves to ~/pokedex/pokemon_db.json

Run: python3 ~/pokedex/build_db.py
Takes ~30-40 min (3 API calls per Pokemon).
"""

import requests, json, os

DB_PATH = os.path.expanduser('~/pokedex/pokemon_db.json')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
total = 1025

def region_of(i):
    if i <= 151: return 'Kanto'
    if i <= 251: return 'Johto'
    if i <= 386: return 'Hoenn'
    if i <= 493: return 'Sinnoh'
    if i <= 649: return 'Unova'
    if i <= 721: return 'Kalos'
    if i <= 809: return 'Alola'
    if i <= 905: return 'Galar'
    return 'Paldea'

def get_evo_chain(species):
    try:
        chain = requests.get(species['evolution_chain']['url'], timeout=10).json()['chain']
        res = []; node = chain
        while node:
            lvl = None
            if node['evolution_details']:
                lvl = node['evolution_details'][0].get('min_level')
            res.append({'name': node['species']['name'], 'level': lvl})
            node = node['evolves_to'][0] if node['evolves_to'] else None
        return res
    except:
        return []

db = {}
for i in range(1, total + 1):
    try:
        data = requests.get(f'https://pokeapi.co/api/v2/pokemon/{i}', timeout=15).json()
        name = data['name']
        types = [t['type']['name'] for t in data['types']]
        abilities = [a['ability']['name'] for a in data['abilities']]
        moves = [m['move']['name'] for m in data['moves'][:6]]
        stats = {s['stat']['name']: s['base_stat'] for s in data['stats']}
        height = data['height'] / 10.0   # meters
        weight = data['weight'] / 10.0   # kg
        sp = requests.get(data['species']['url'], timeout=15).json()
        genus = ''
        for g in sp.get('genera', []):
            if g['language']['name'] == 'en':
                genus = g['genus']; break
        desc = ''
        for ft in sp.get('flavor_text_entries', []):
            if ft['language']['name'] == 'en':
                desc = ft['flavor_text'].replace('\n', ' ').replace('\f', ' '); break
        evo = get_evo_chain(sp)
        db[name] = {'id': i, 'types': types, 'abilities': abilities, 'moves': moves,
                    'stats': stats, 'genus': genus, 'height': height, 'weight': weight,
                    'description': desc, 'evolution': evo, 'region': region_of(i)}
        print(f'{i}/{total} {name}       ', end='\r')
    except Exception as e:
        print(f'\nError {i}: {e}')

with open(DB_PATH, 'w') as f:
    json.dump(db, f)
print(f'\nDone! {len(db)} Pokemon')
