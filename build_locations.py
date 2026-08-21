"""
build_locations.py - Fetch encounter locations for every Pokemon and merge
them into pokemon_db.json as a 'locations' field.

Run: python3 ~/pokedexv3/build_locations.py
Takes ~25-35 min (one API call per Pokemon).

Safe to re-run: it skips Pokemon that already have a 'locations' field, and
saves progress every 25 Pokemon, so if it dies partway just run it again.

Many Pokemon have no encounter data at all (evolutions, legendaries, starters
that are only ever given to you). Those get an empty list and the app shows
"Not found in the wild".
"""

import requests, json, os, time

DB_PATH = os.path.expanduser('~/pokedex/pokemon_db.json')
TOTAL = 1025
MAX_LOCS = 8          # keep the biggest offenders from bloating the file

# The location_area names from PokeAPI are machine-readable, not pretty.
# "kanto-route-2-south-towards-viridian-city" -> "Kanto Route 2 South Towards Viridian City"
def pretty(name):
    return ' '.join(w.capitalize() for w in name.replace('-', ' ').split())


def fetch_locations(pid):
    """Returns [{'area': str, 'games': [str]}] for one pokemon."""
    r = requests.get(f'https://pokeapi.co/api/v2/pokemon/{pid}/encounters', timeout=20)
    r.raise_for_status()
    data = r.json()
    out = []
    for e in data:
        area = pretty(e['location_area']['name'])
        games = []
        for v in e.get('version_details', []):
            g = v['version']['name'].replace('-', ' ').title()
            if g not in games:
                games.append(g)
        out.append({'area': area, 'games': games[:4]})
    return out[:MAX_LOCS]


def main():
    if not os.path.exists(DB_PATH):
        print('No database at', DB_PATH)
        print('Run build_db.py first.')
        return

    with open(DB_PATH) as f:
        db = json.load(f)

    by_id = {v['id']: k for k, v in db.items()}
    done = sum(1 for v in db.values() if 'locations' in v)
    print(f'{len(db)} pokemon in db, {done} already have locations')

    changed = 0
    for pid in range(1, TOTAL + 1):
        name = by_id.get(pid)
        if not name:
            continue
        if 'locations' in db[name]:
            continue
        try:
            db[name]['locations'] = fetch_locations(pid)
            changed += 1
            n = len(db[name]['locations'])
            print(f'{pid}/{TOTAL} {name}: {n} areas          ', end='\r')
        except Exception as e:
            print(f'\nError {pid} {name}: {e}')
            db[name]['locations'] = []
        if changed % 25 == 0 and changed:
            with open(DB_PATH, 'w') as f:
                json.dump(db, f)
        time.sleep(0.05)

    with open(DB_PATH, 'w') as f:
        json.dump(db, f)

    with_locs = sum(1 for v in db.values() if v.get('locations'))
    print(f'\nDone. {with_locs}/{len(db)} pokemon have wild encounter data.')
    print('(The rest genuinely have none - evolutions, legendaries, starters.)')


if __name__ == '__main__':
    main()
