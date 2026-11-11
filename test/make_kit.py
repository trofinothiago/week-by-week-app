#!/usr/bin/env python3
"""Make the app's test kit: the kit's wbw_check.py runs the page with mock.js; for the app, mock.js becomes
the real supabase-js + the fake Supabase (test/fake_supabase.js) + the app's bridge + the download recorder.
So the kit plays the page through the very same connection the app uses.

usage: python3 test/make_kit.py OUT_DIR   (the app's own copy of the kit's wbw_check.py is test/wbw_check.py)
"""
import os, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
parts = ['app/vendor/supabase.js', 'test/fake_supabase.js', 'app/bridge.js', 'test/after_bridge.js']
open(os.path.join(out, 'mock.js'), 'w', encoding='utf-8').write('\n;\n'.join(open(os.path.join(ROOT, p), encoding='utf-8').read() for p in parts))
shutil.copy(os.path.join(ROOT, 'test/wbw_check.py'), os.path.join(out, 'wbw_check.py'))
print('app kit ready in', out)
