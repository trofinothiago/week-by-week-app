#!/usr/bin/env python3
"""Build the app from the page.

src/week-by-week.html is the page exactly as it is inside Claude (copied from the live artifact, tested with the kit).
This writes:
  index.html   the page + the app's head (icon, manifest, app.css) + its data connection (config, Supabase, bridge),
               placed right after <body>, where the kit puts its mock.
  import.html  the account page (sign out, bring in a backup), with the page's own stylesheet so it looks the same.
Nothing in the page's code changes.

usage: python3 tools/build.py
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
page = open(os.path.join(ROOT, 'src/week-by-week.html'), encoding='utf-8').read()

APP_HEAD = ('<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-180.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-title" content="Week by Week"><meta name="apple-mobile-web-app-status-bar-style" content="default">'
            '<link rel="stylesheet" href="app/app.css">')
APP_SCRIPTS = '<script src="app/config.js"></script><script src="app/vendor/supabase.js"></script><script src="app/bridge.js"></script>'

def once(s, a, label):
    n = s.count(a)
    if n != 1: sys.exit(f'build: expected one {label} in the page, found {n}')

once(page, '</head>', '</head>'); once(page, '<body>', '<body>')
index = page.replace('</head>', APP_HEAD + '</head>', 1).replace('<body>', '<body>' + APP_SCRIPTS, 1)
open(os.path.join(ROOT, 'index.html'), 'w', encoding='utf-8').write(index)

styles = re.findall(r'<style>.*?</style>', page, flags=re.S)
style = max(styles, key=len)   # the page's stylesheet (the small one in <head> is Claude's frame)
tpl = open(os.path.join(ROOT, 'app/import.tpl.html'), encoding='utf-8').read()
imp = tpl.replace('{{APP_HEAD}}', APP_HEAD).replace('{{PAGE_STYLE}}', style)
open(os.path.join(ROOT, 'import.html'), 'w', encoding='utf-8').write(imp)
print(f'index.html {len(index):,} bytes, import.html {len(imp):,} bytes')
