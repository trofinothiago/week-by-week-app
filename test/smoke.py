#!/usr/bin/env python3
"""Week by Week app: checks the app's own parts on the built files (index.html, import.html), with the fake Supabase.
Sign-in, roles (Thiago writes, Rory reads only, a stranger is turned away), an invite link, the account page and
the backup import, and the phone fit of the new screens (375 and 430 px, light and dark).

usage: python3 test/smoke.py [--backup FILE.json] [--shots DIR]
"""
import argparse, json, os, sys, threading, http.server, functools
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument('--backup', default=''); ap.add_argument('--shots', default=''); A = ap.parse_args()
FAKE = open(os.path.join(ROOT, 'test/fake_supabase.js'), encoding='utf-8').read()

# a small made-up household (or the real backup, when given), in the page's own shapes
if A.backup:
    B = json.load(open(A.backup, encoding='utf-8'))
else:
    B = {'app': 'Week by Week', 'kind': 'backup', 'format': 1, 'savedAt': '2026-11-08T18:00:00.000Z',
         'config': {'settings': {'incomeThiago': 300, 'incomeRory': 500, 'transferBills': 390, 'cardWeekly': 100}, 'plan': {'efWeekly': 25}, 'facts': {}, 'advice': {}, 'prep': {}, 'energy': {}, 'health': {}},
         'weeks': {}, 'bills': [{'id': 'rent1', 'name': 'Mortgage', 'amount': 900, 'frequency': 'monthly', 'dueDay': 1, 'account': 'bills', 'active': True, 'category': 'Housing'}],
         'spending': [{'id': 's1', 'date': '2026-11-07', 'amount': 12.5, 'category': 'Groceries', 'who': 'both', 'from': 'joint', 'kind': 'need'}],
         'cardlog': [], 'wishlist': [], 'changelog': [], 'wise': [], 'checks': [], 'klarna': [], 'loans': [], 'assets': [], 'moves': [], 'compare': [], 'prep': []}
seed = {'config': {k: v for k, v in B['config'].items() if v}, 'weeks': {k: {x: y for x, y in v.items() if x != 'id'} for k, v in B.get('weeks', {}).items()}}
for k, v in B.items():
    if isinstance(v, list): seed[k] = {d['id']: {x: y for x, y in d.items() if x != 'id'} for d in v}

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Q, directory=ROOT)); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{srv.server_port}/'
res = []
def check(name, ok, info=''):
    res.append(ok); print(('PASS ' if ok else 'FAIL ') + name + (f'  [{str(info)[:240]}]' if info != '' and not ok else ''), flush=True)

with sync_playwright() as p:
    br = p.chromium.launch()
    def open_as(role, path='index.html', width=390, dark=False, hash=''):
        ctx = br.new_context(viewport={'width': width, 'height': 860}, color_scheme='dark' if dark else 'light')
        ctx.add_init_script('window.__SEED__ = ' + json.dumps(seed) + '; window.__ROLE__ = ' + json.dumps(role) + ';')
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(BASE) else r.abort())     # nothing leaves this machine
        ctx.route('**/app/config.js', lambda r: r.fulfill(body=FAKE, content_type='text/javascript'))   # the fake Supabase instead of the real one (the later route wins)
        pg = ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(BASE + path + hash); pg.wait_for_timeout(1200)
        return ctx, pg, errs
    ev = lambda pg, js: pg.evaluate(js)
    gate = lambda pg: ev(pg, "() => { const g = document.getElementById('gate'); return g ? g.innerText : ''; }")
    sideways = lambda pg: ev(pg, "() => document.documentElement.scrollWidth > window.innerWidth + 1")
    shot = lambda pg, n: A.shots and pg.screenshot(path=os.path.join(A.shots, n + '.png'), full_page=False)
    if A.shots: os.makedirs(A.shots, exist_ok=True)

    # 1. signed out: the sign-in screen, a wrong password, then Thiago signs in
    ctx, pg, errs = open_as('none')
    check('signed out: the sign-in screen shows', 'Sign in' in gate(pg) and 'Password' in gate(pg), gate(pg))
    check('signed out: nothing of ours is loaded', ev(pg, "() => (S.bills || []).length === 0 && !S.db"))
    shot(pg, 'signin-light')
    pg.fill('#gEmail', 'thiago@example.test'); pg.fill('#gPass', 'wrong-password'); pg.click('.gform button[type=submit]'); pg.wait_for_timeout(500)
    check('a wrong password is refused with a clear line', 'don’t match' in gate(pg), gate(pg))
    pg.fill('#gPass', 'test-password-1'); pg.click('.gform button[type=submit]'); pg.wait_for_timeout(1200)
    check('Thiago signs in: the sign-in screen goes', gate(pg) == '', gate(pg))
    check('Thiago sees his iPhone-look page with our data', ev(pg, "() => S.canWrite && document.documentElement.dataset.look === 'ios' && S.bills.length === %d" % len(seed.get('bills', {}))))
    check('Today draws clean', not any(s in ev(pg, "() => document.getElementById('view').innerText") for s in ['Something went wrong', 'NaN', 'Invalid Date', 'store isn’t available']))
    check('no errors on the page', not errs, errs)
    ctx.close()

    # 2. Thiago writes: set, update, add, delete reach the database and come back to the screen
    ctx, pg, errs = open_as('editor')
    r = ev(pg, """async () => {
      const out = {};
      await S.db.doc('config/settings').update({smokeA: 1}); await new Promise(r => setTimeout(r, 50)); out.update = S.settings.smokeA === 1;
      await S.db.doc('bills/smoke1').set({name: 'Smoke', amount: 1, frequency: 'monthly', dueDay: 2, account: 'bills', active: false}); await new Promise(r => setTimeout(r, 50));
      out.set = S.bills.some(b => b.id === 'smoke1');
      const a = await S.db.collection('wishlist').add({what: 'Smoke', price: 1}); await new Promise(r => setTimeout(r, 50));
      out.add = S.wishlist.some(w => w.id === a.id) && /^[A-Za-z0-9]{20}$/.test(a.id);
      await S.db.doc('bills/smoke1').delete(); await new Promise(r => setTimeout(r, 50)); out.del = !S.bills.some(b => b.id === 'smoke1');
      try { await S.db.doc('bills/nothere').update({a: 1}); out.missing = false; } catch (e) { out.missing = true; }
      out.writes = window.__writes.map(w => w[0]).join(',');
      return out; }""")
    check('Thiago: a change (update) is saved and shows', r['update'], r)
    check('Thiago: a new bill (set) is saved and shows', r['set'], r)
    check('Thiago: a new item (add) gets an id and shows', r['add'], r)
    check('Thiago: a delete is saved and shows', r['del'], r)
    check('Thiago: changing something that isn’t there is refused', r['missing'], r)
    check('the writes went to the database in order', r['writes'] == 'update,set,add,delete', r['writes'])
    check('Thiago: Settings → Setup draws (backup panel)', 'Backup' in ev(pg, "() => { S.tab = 'settings'; S.sub.settings = 'setup'; render(); return document.getElementById('view').innerText; }"))
    ctx.close()

    # 3. Rory: his report only, and the database refuses every write
    ctx, pg, errs = open_as('viewer')
    check('Rory: he lands on his report (his own look)', ev(pg, "() => !S.canWrite && document.body.classList.contains('rorymode') && document.documentElement.dataset.look === 'classic'"))
    r = ev(pg, """async () => {
      const out = {}, t = async f => { try { await f(); return 'saved'; } catch (e) { return e.code; } };
      out.update = await t(() => S.db.doc('config/settings').update({hack: 1}));
      out.set = await t(() => S.db.doc('config/settings').set({hack: 1}));
      out.add = await t(() => S.db.collection('spending').add({hack: 1}));
      out.del = await t(() => S.db.doc('bills/' + S.bills[0].id).delete());
      out.still = S.bills.length; out.writes = window.__writes.length; return out; }""")
    check('Rory: a change is refused by the database', r['update'] == 'invalid_argument', r)
    check('Rory: a new document is refused', r['set'] == 'invalid_argument' and r['add'] == 'invalid_argument', r)
    check('Rory: a delete is refused and nothing disappears', r['del'] == 'invalid_argument' and r['still'] == len(seed.get('bills', {})), r)
    check('Rory: nothing reached the data', r['writes'] == 0, r)
    check('no errors on Rory’s page', not errs, errs)
    ctx.close()

    # 4. a stranger who somehow has an account is turned away
    ctx, pg, errs = open_as('none')
    pg.fill('#gEmail', 'stranger@example.test'); pg.fill('#gPass', 'test-password-3'); pg.click('.gform button[type=submit]'); pg.wait_for_timeout(1000)
    check('a stranger is turned away and sees nothing', 'isn’t one of the two' in gate(pg) and ev(pg, "() => !S.db"), gate(pg))
    ctx.close()

    # 5. Rory's invite link: choose a password, then in
    import base64, time
    b64 = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
    ac = b64({'alg': 'HS256', 'typ': 'JWT'}) + '.' + b64({'sub': '00000000-0000-4000-8000-0000000000b2', 'email': 'rory@example.test', 'role': 'authenticated', 'aud': 'authenticated', 'exp': int(time.time()) + 3600}) + '.sig'
    ctx, pg, errs = open_as('none', hash=f'#access_token={ac}&expires_in=3600&refresh_token=r&token_type=bearer&type=invite')
    check('invite link: “choose your password” shows', 'Choose your password' in gate(pg), gate(pg))
    shot(pg, 'invite-light')
    pg.fill('#gNew', 'short'); pg.fill('#gNew2', 'short'); pg.click('.gform button[type=submit]'); pg.wait_for_timeout(300)
    check('invite link: a short password is refused', '10 characters' in gate(pg), gate(pg))
    pg.fill('#gNew', 'a-good-long-password'); pg.fill('#gNew2', 'a-good-long-password'); pg.click('.gform button[type=submit]'); pg.wait_for_timeout(1200)
    check('invite link: after the password Rory is in, on his report', gate(pg) == '' and ev(pg, "() => !S.canWrite && document.body.classList.contains('rorymode')"), gate(pg))
    check('invite link: the address is cleaned (no token left in it)', 'access_token' not in pg.url, pg.url)
    ctx.close()

    # 6. the account page: Thiago brings in a backup (two taps); Rory can't
    bk = os.path.join('/tmp', 'wbw_smoke_backup.json'); json.dump(B, open(bk, 'w'))
    ctx, pg, errs = open_as('editor', 'import.html')
    txt = lambda: ev(pg, "() => document.getElementById('acct').innerText")
    check('account page: who is signed in', 'Thiago' in txt() and 'Can change everything' in txt(), txt())
    pg.set_input_files('input[type=file]', bk); pg.wait_for_timeout(400)
    check('account page: the file is read and counted', 'in the file' in txt() and 'Replace everything' in txt(), txt())
    shot(pg, 'import-light')
    pg.click('[data-a=go]'); pg.wait_for_timeout(200)
    check('account page: the first tap only asks again', 'Tap again' in txt() and not ev(pg, "() => window.__writes.some(w => w[0] === 'import')"))
    pg.click('[data-a=go]'); pg.wait_for_timeout(800)
    n = sum(1 for v in B['config'].values() if v) + len(B.get('weeks', {})) + sum(len(v) for v in B.values() if isinstance(v, list))
    check('account page: the second tap brings it all in', f'Done: {n} items' in txt(), txt())
    bad = os.path.join('/tmp', 'wbw_smoke_bad.json'); json.dump({'hello': 1}, open(bad, 'w'))
    pg.set_input_files('input[type=file]', bad); pg.wait_for_timeout(300)
    check('account page: a file that isn’t a backup is refused', 'isn’t a Week by Week backup' in txt() and 'Replace everything' not in txt(), txt())
    check('no errors on the account page', not errs, errs)
    ctx.close()
    ctx, pg, errs = open_as('viewer', 'import.html')
    check('account page for Rory: no import, a clear line', 'Only Thiago' in txt() and not ev(pg, "() => !!document.querySelector('input[type=file]')"), txt())
    ctx.close()

    # 7. the new screens fit the phone (small iPhone and Pro Max, light and dark)
    bad = []
    for w in (375, 430):
        for dark in (False, True):
            for path, role in (('index.html', 'none'), ('import.html', 'editor')):
                ctx, pg, errs = open_as(role, path, w, dark)
                if path == 'import.html': pg.set_input_files('input[type=file]', bk); pg.wait_for_timeout(300)
                if sideways(pg): bad.append(f'{path} {w}px {"dark" if dark else "light"}: scrolls sideways')
                if errs: bad.append(f'{path}: {errs[0]}')
                if dark and w == 375: shot(pg, path.split('.')[0] + '-dark')
                ctx.close()
    check('the sign-in and account screens fit the phone (375 and 430 px, light and dark)', not bad, bad)

    br.close()
srv.shutdown()
print(f'\n{sum(res)} of {len(res)} passed'); sys.exit(0 if all(res) else 1)
