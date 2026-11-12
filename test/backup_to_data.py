#!/usr/bin/env python3
"""Turn a Week by Week backup (.json, Settings → Setup → Download a backup) into the kit's DATA folder:
one folder per collection with one <id>.json per document (config/<name>.json, weeks/<week>.json).

usage: python3 -I test/backup_to_data.py BACKUP.json OUT_DIR
"""
import json, os, sys
B = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]
assert B.get('app') == 'Week by Week' and B.get('kind') == 'backup', 'not a Week by Week backup'
def put(coll, id_, doc):
    d = os.path.join(out, coll); os.makedirs(d, exist_ok=True)
    json.dump({k: v for k, v in doc.items() if k != 'id'}, open(os.path.join(d, f'{id_}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
n = 0
for k, v in B.get('config', {}).items():
    if v: put('config', k, v); n += 1
for k, v in B.get('weeks', {}).items(): put('weeks', k, v); n += 1
for coll, v in B.items():
    if isinstance(v, list):
        os.makedirs(os.path.join(out, coll), exist_ok=True)
        for d in v: put(coll, d['id'], d); n += 1
print(f'{n} documents from the backup of {B.get("savedAt")} in {out}')
