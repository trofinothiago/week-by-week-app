#!/usr/bin/env python3
"""Build the app from the page.

src/week-by-week.html is the page (tested with the kit).
This writes:
  index.html   the page + the app's head (icon, manifest, app.css) + its data connection (config, Supabase, bridge),
               placed right after <body>, where the kit puts its mock.
  import.html  the account page (sign out, bring in a backup), with the page's own stylesheet so it looks the same.

usage: python3 tools/build.py
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
page = open(os.path.join(ROOT, 'src/week-by-week.html'), encoding='utf-8').read()

import hashlib
v = lambda f: f + '?v=' + hashlib.sha1(open(os.path.join(ROOT, f), 'rb').read()).hexdigest()[:10]   # a new version of a file gets a new address, so phones never keep an old copy
APP_HEAD = (f'<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-180.png"><script src="{v("app/icon.js")}"></script>'
            '<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-title" content="Week by Week"><meta name="apple-mobile-web-app-status-bar-style" content="default">'
            f'<link rel="stylesheet" href="{v("app/app.css")}">')
APP_SCRIPTS = f'<script src="{v("app/config.js")}"></script><script src="{v("app/vendor/supabase.js")}"></script><script src="{v("app/bridge.js")}"></script>'

def once(s, a, label):
    n = s.count(a)
    if n != 1: sys.exit(f'build: expected one {label} in the page, found {n}')

once(page, '</head>', '</head>'); once(page, '<body>', '<body>')
index = page.replace('</head>', APP_HEAD + '</head>', 1).replace('<body>', '<body>' + APP_SCRIPTS, 1)
open(os.path.join(ROOT, 'index.html'), 'w', encoding='utf-8').write(index)

style = re.search(r'<style>.*?</style>', page, flags=re.S).group(0)   # the page's stylesheet
tpl = open(os.path.join(ROOT, 'app/import.tpl.html'), encoding='utf-8').read()
imp = tpl.replace('{{APP_HEAD}}', APP_HEAD).replace('{{PAGE_STYLE}}', style).replace('{{APP_SCRIPTS}}', APP_SCRIPTS + f'<script src="{v("app/import.js")}"></script>')
open(os.path.join(ROOT, 'import.html'), 'w', encoding='utf-8').write(imp)
print(f'index.html {len(index):,} bytes, import.html {len(imp):,} bytes')
