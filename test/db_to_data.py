#!/usr/bin/env python3
"""Turn the app's database, read through the Supabase connector, into the kit's DATA folder.

The scheduled "Weekly system update" reads public.docs with
  select coll, jsonb_object_agg(id, data) as docs from public.docs where coll <> 'changelog' group by coll;
  select jsonb_object_agg(id, data) as docs from (select id, data from public.docs where coll = 'changelog' order by data->>'at' desc limit 60) c;
and saves the rows as one file shaped {coll: {id: data}} (the changelog under "changelog").
This writes one folder per collection with one <id>.json per document, like test/backup_to_data.py.
Keep both files outside the repository: the repository is public.

usage: python3 -I test/db_to_data.py DB.json OUT_DIR
"""
import json, os, sys
D = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]
assert isinstance(D, dict) and isinstance(D.get('config'), dict), 'expected {coll: {id: data}} with a config collection'
n = 0
for coll, docs in D.items():
    os.makedirs(os.path.join(out, coll), exist_ok=True)
    for id_, data in (docs or {}).items():
        json.dump({k: v for k, v in data.items() if k != 'id'}, open(os.path.join(out, coll, f'{id_}.json'), 'w', encoding='utf-8'), ensure_ascii=False); n += 1
print(f'{n} documents in {out}')
