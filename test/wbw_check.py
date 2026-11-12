#!/usr/bin/env python3
"""Week by Week weekly system check (the app's copy: the page plays through the app's own data connection and the fake Supabase in test/fake_supabase.js; test/make_kit.py builds its mock.js).
Plays the page on a COPY of the live data (in-memory mock database: nothing reaches the real one) and checks that
every screen draws, every connection works and Rory's report and PDF are made.

usage: python3 wbw_check.py --page week-by-week.html --data DATA_DIR --kit KIT_DIR [--lib NODE_MODULES] [--now 2026-11-02T07:45:00] [--out result.json]
DATA_DIR holds one folder per collection (config, bills, cardlog, spending, weeks, checks, moves, wise, loans, klarna, wishlist, assets, changelog)
with one <id>.json per document, exactly as ArtifactData list ... out_dir writes them.
NODE_MODULES must contain jspdf@2.5.1 and html2canvas@1.4.1 (npm install) for the PDF check; without it the PDF check is skipped.
"""
import argparse, glob, json, os, sys, time, datetime, traceback
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument('--page', required=True); ap.add_argument('--data', required=True); ap.add_argument('--kit', default=os.path.dirname(os.path.abspath(__file__)))
ap.add_argument('--lib', default=''); ap.add_argument('--now', default=''); ap.add_argument('--out', default='result.json'); ap.add_argument('--shots', default='')
A = ap.parse_args()

# ---- build the test page: the live page with the mock database and a copy of the data ----
seed = {}
for d in glob.glob(os.path.join(A.data, '*')):
    if os.path.isdir(d): seed[os.path.basename(d)] = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(d + '/*.json')}
for k in ['klarna', 'assets', 'wishlist', 'moves', 'loans', 'wise', 'checks', 'weeks', 'cardlog', 'spending', 'changelog', 'bills']: seed.setdefault(k, {})
html = open(A.page, encoding='utf-8').read()
mock = open(os.path.join(A.kit, 'mock.js'), encoding='utf-8').read()
assert '<body>' in html, 'page has no <body>'
TEST = os.path.join(os.path.dirname(os.path.abspath(A.out)), '_wbw_test.html')
open(TEST, 'w', encoding='utf-8').write(html.replace('<body>', '<body><script>window.__SEED__ = ' + json.dumps(seed) + ';\n' + mock + '</script>', 1))

NOW = datetime.datetime.fromisoformat(A.now) if A.now else datetime.datetime.now()
iso = lambda d: d.strftime('%Y-%m-%dT%H:%M:%S')
results, notes = [], {}
def check(name, ok, info=''):
    results.append({'name': name, 'ok': bool(ok), 'info': str(info)[:400]}); print(('PASS ' if ok else 'FAIL ') + name + (f'  [{str(info)[:200]}]' if info != '' else ''), flush=True)

TABS = [('today', None), ('week', None), ('pay', None)] + [('money', x) for x in ['balance', 'bills', 'energy', 'debts', 'spending', 'transfers']] + \
       [('plan', x) for x in ['plan', 'advisor', 'budget', 'compare', 'ready', 'trends', 'million']] + [('settings', x) for x in ['setup', 'rules', 'health', 'history']]
# phone fit: nothing past the edge, squeezed into a narrow column, or drawn on top of other text
PROBE = r"""() => {
  const W = document.documentElement.clientWidth, out = [];
  if (document.documentElement.scrollWidth > W + 1) out.push('PAGE scrolls sideways: ' + document.documentElement.scrollWidth);
  const scrollerOf = el => { for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return p; } return null; };
  const desc = el => (el.className && typeof el.className === 'string' ? el.tagName.toLowerCase() + '.' + el.className.split(' ').join('.') : el.tagName.toLowerCase()) + ' "' + (el.innerText || '').replace(/\s+/g, ' ').slice(0, 60) + '"';
  const root = document.querySelector('.ios-sheet') || document.getElementById('view');
  const seen = new Set();
  for (const el of root.querySelectorAll('*')) {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const sc = scrollerOf(el);
    if (r.right > W + 1 && !sc) { const k = 'EDGE ' + desc(el); if (!seen.has(k)) { seen.add(k); out.push(k + ' right=' + Math.round(r.right)); } }
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 2 && !el.matches('.subnav,.iostabs,.seg,.chips')) out.push('SCROLLS ' + desc(el) + ' ' + el.scrollWidth + '>' + el.clientWidth);
    // squeezed text: a box with its own text, narrow, many lines
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 2);
    if (own && r.width < 150 && !el.matches('svg *,button,.iostabs *,.subnav *')) {
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3, lines = Math.round(r.height / lh);
      const words = (el.innerText || '').trim().split(/\s+/).length;
      if ((lines >= 3 && r.width < 120 && words >= 3) || (lines >= 4 && words / lines < 3)) out.push('SQUEEZED ' + desc(el) + ' w=' + Math.round(r.width) + ' lines=' + lines);
    }
  }
  // overlapping text: two text boxes drawn on top of each other
  const fixedAnc = el => { for (let p = el; p && p !== document.body; p = p.parentElement) { const ps = getComputedStyle(p).position; if (ps === 'fixed' || ps === 'sticky') return true; } return false; };
  const leaves = [];
  for (const el of root.querySelectorAll('*')) {
    if (el.closest('svg')) continue;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.fontSize) < 2) continue;
    if (fixedAnc(el) || !(el.innerText || '').trim()) continue;
    { let op = 1; for (let q = el; q && q !== document.body; q = q.parentElement) op *= parseFloat(getComputedStyle(q).opacity); if (op < .05) continue; }
    for (const n of el.childNodes) { if (n.nodeType !== 3 || !n.textContent.trim()) continue; const rg = document.createRange(); rg.selectNodeContents(n); for (const r of rg.getClientRects()) if (r.width > 1 && r.height > 1) leaves.push({el, r}); }
  }
  for (let i = 0; i < leaves.length; i++) for (let j = i + 1; j < leaves.length; j++) {
    const a = leaves[i].r, b = leaves[j].r; if (leaves[i].el === leaves[j].el) continue;
    const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (ox > 3 && oy > 4) { const k = 'OVERLAP ' + desc(leaves[i].el) + ' × ' + desc(leaves[j].el); if (!seen.has(k)) { seen.add(k); out.push(k); } }
  }
  return out;
}"""
BAD = ['Something went wrong', 'NaN', 'undefined', 'Invalid Date']

def lib_route(r):
    u = r.request.url
    if A.lib and 'jspdf' in u: return r.fulfill(path=os.path.join(A.lib, 'jspdf/dist/jspdf.umd.min.js'), content_type='text/javascript')
    if A.lib and 'html2canvas' in u: return r.fulfill(path=os.path.join(A.lib, 'html2canvas/dist/html2canvas.min.js'), content_type='text/javascript')
    return r.abort() if u.startswith('http') else r.continue_()

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_page(viewport={'width': 390, 'height': 900}); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.route('**/*', lib_route)
    ev = pg.evaluate; w = lambda ms=400: pg.wait_for_timeout(ms)
    view = lambda: ev("() => document.getElementById('view').innerText")
    def load(t):
        pg.clock.set_fixed_time(iso(t)); pg.goto('file://' + TEST); pg.wait_for_timeout(1000)
    def at(t): pg.clock.set_fixed_time(iso(t)); ev("() => render()"); w(150)
    def pick(a, v):   # choose from a list that acts on change (the country in Ready)
        ev(f"""() => {{ const x = document.querySelector('select[data-act={a}]'); x.value = {json.dumps(v)}; x.dispatchEvent(new Event('change', {{bubbles: true}})); }}"""); w(500)
    def act(a, **d):
        ev(f"""() => {{ const x = document.createElement('button'); x.dataset.act = {json.dumps(a)}; Object.assign(x.dataset, {json.dumps(d)}); document.getElementById('view').appendChild(x); x.click(); }}"""); w(500)
    def rory_answer(kind, ref, ans, words):   # act as Rory: only his own account can answer (the fake server lets the kit sign in as him)
        ev(f"() => {{ window.__as = 'viewer'; S.canWrite = false; S.canAnswer = true; S.f.ans = {{...(S.f.ans || {{}}), [{json.dumps(ref)}]: {json.dumps(words)}}}; render(); }}")
        act('roryAnswer', k=kind, id=ref, v=ans); w(500)
        out = ev("() => ({err: S.err, view: document.getElementById('view').innerText})")
        ev("() => { window.__as = null; S.canWrite = true; S.canAnswer = false; S.err = ''; render(); }")
        return out
    fit = []
    def sweep(label):
        bad = []
        for tab, sub in TABS:
            ev(f"() => {{ S.tab = '{tab}'; S.todayOpen = ''; {f'S.sub.{tab} = {json.dumps(sub)};' if sub else ''} render(); }}")
            v = view()
            for s in BAD:
                if s in v: bad.append(f'{tab}/{sub}: {s}')
            if ev("() => document.documentElement.scrollWidth > window.innerWidth + 1"): bad.append(f'{tab}/{sub}: scrolls sideways')
            if label == 'now': fit.extend(f'{tab}/{sub}: {x}' for x in ev(PROBE))
        check(f'{label}: all {len(TABS)} sections draw clean', not bad, bad)
        if label == 'now': check('now: every section fits the phone screen (nothing squeezed, overlapping or past the edge)', not fit, fit[:8])
    def step(name, fn):
        try: fn()
        except Exception as e: check(name + ' (ran without error)', False, ''.join(traceback.format_exception_only(type(e), e)).strip())

    # ---- 0. code hygiene: no dead code, no duplicates, no patches (runs on the page's source, no browser) ----
    def f_hygiene():
        import re as _re
        a = html.index('<style>\n') + 8; z = html.index('</style>', a); css = html[a:z]
        s0 = html.index('<script>', z) + 8; s1 = html.rindex('</script>'); js = html[s0:s1]; rest = html[:a] + html[z:]
        # top-level definitions: a line that starts with function/async function/const/let/var NAME
        defs = [(m.group(2), m.start()) for m in _re.finditer(r'(?m)^(?:async\s+)?(function\s*\*?\s*|const\s+|let\s+|var\s+)([A-Za-z_$][\w$]*)', js)]
        names = [n for n, _ in defs]
        dup = sorted({n for n in names if names.count(n) > 1})
        check('code: no function or constant is defined twice (a later copy would silently replace the first)', not dup, dup[:10])
        def end_of(p):   # a definition runs until the next line that starts a new statement at the left edge (closing brackets belong to it)
            for m in _re.finditer(r'\n(?=[^\s}\])])', js[p:]): return p + m.start()
            return len(js)
        starts = sorted(p for _, p in defs) + [len(js)]
        def refs(n, text):   # the name used as itself: not a property like x.name (a spread ...name counts)
            return sum(1 for m in _re.finditer(r'(?<![\w$])' + _re.escape(n) + r'(?![\w$])', text) if not (m.start() and text[m.start() - 1] == '.' and text[max(0, m.start() - 3):m.start()] != '...'))
        dead = []
        for i, (n, p) in enumerate(defs):
            nxt = min([q for q in starts if q > p] or [len(js)])
            body = js[p:min(end_of(p), nxt)]
            if refs(n, js) - refs(n, body) <= 0: dead.append(n)
        check('code: nothing is defined that nothing uses (no dead code left behind by a change)', not dead, dead[:12])
        # CSS: every class is used, no selector twice in the same place, no styles injected from JavaScript
        css2 = _re.sub(r'/\*.*?\*/', '', css, flags=_re.S); rules = []
        def parse(block, ctx=''):
            i = 0
            while i < len(block):
                j = block.find('{', i)
                if j < 0: break
                sel = block[i:j].strip()
                if sel.startswith('@'):
                    d, k = 1, j + 1
                    while d: d += {'{': 1, '}': -1}.get(block[k], 0); k += 1
                    parse(block[j + 1:k - 1], ctx + ' ' + sel); i = k
                else: k = block.find('}', j); rules.append((ctx.strip(), sel)); i = k + 1
        parse(css2)
        twice = sorted({f'{c} {x}'.strip() for c, x in rules if rules.count((c, x)) > 1})
        check('styles: no selector is written twice in the same place (one rule each)', not twice, twice[:8])
        prefixes = set(_re.findall(r'([A-Za-z][\w-]*-)\$\{', rest))   # classes built in code, like c-${...}
        classes = sorted({m for _, x in rules for m in _re.findall(r'\.([A-Za-z_][\w-]*)', x)})
        unused = [c for c in classes if not _re.search(r'(?<![\w.-])' + _re.escape(c) + r'(?![\w-])', rest) and not any(c.startswith(p) for p in prefixes)]
        check('styles: every class in the stylesheet is used by the page', not unused, unused[:12])
        patches = [t for t, pat in [('a <style> written from JavaScript', r'<style>\$\{|<style>[^<]*\{[^<]*</style>'), ('console.log', r'console\.log\('), ('debugger', r'\bdebugger\b'),
                   ('the retired Classic look (S.look)', r'S\.look\b'), ('the retired weekly budgets (kind budget)', r"kind\s*[!=]==\s*'budget'"), ('a patch marker', r'(?i)\b(patch_v?\d|monkey.?patch|_orig[A-Z(])')] if _re.search(pat, js)]
        check('code: no patch leftovers (styles from JavaScript, console.log, retired features, patch markers)', not patches, patches)
        acts = set(_re.findall(r'data-act="([A-Za-z]\w*)"', js)); missing = sorted(x for x in acts if f"case '{x}'" not in js and not _re.search(r"\b(a|act)\s*===\s*'" + x + "'", js))
        check('code: every button the page draws has an action that handles it', not missing, missing[:10])
        handled = set(_re.findall(r"case '([A-Za-z]\w*)':", js))   # an action no screen can trigger: its name appears nowhere but its own case
        orphan = sorted(x for x in handled if len(_re.findall(r"['\"]" + x + r"['\"]", js)) + len(_re.findall(r'data-act="' + x + '"', js)) < 2)
        check('code: every action the page handles can be reached from a screen (no dead handlers)', not orphan, orphan[:10])
        seenL = {}   # the same long piece of code written twice: it belongs in one shared helper
        for ln in js.split('\n'):
            t = ln.strip()
            if len(t) >= 160 and not t.startswith('//'): seenL[t] = seenL.get(t, 0) + 1
        twiceL = [t[:90] for t, c in seenL.items() if c > 1]
        rep = [x for x in _re.findall(r'=> `(<[^`$]{0,40}(?:\$\{[^{}]*\}[^`$]{0,60}){4,}?)`', js)]
        repT = sorted({x[:90] for x in rep if len(x) >= 140 and rep.count(x) > 1})
        check('code: no long piece of code is written out twice (shared helpers instead)', not twiceL and not repT, (twiceL + repT)[:6])
        SH = {'font': ['font-size', 'font-weight', 'font-family', 'line-height', 'font-style'], 'margin': ['margin-top', 'margin-bottom', 'margin-left', 'margin-right'], 'padding': ['padding-top', 'padding-bottom', 'padding-left', 'padding-right'], 'background': ['background-color'], 'border': ['border-color', 'border-width', 'border-style']}
        over = []
        for m in _re.finditer(r'([^{}]+)\{([^{}]*)\}', css2):
            props = [q.split(':', 1)[0].strip() for q in m.group(2).split(';') if ':' in q]
            over += [f"{m.group(1).strip()[-50:]}: {q}" for q in {q for q in props if props.count(q) > 1}]
            over += [f"{m.group(1).strip()[-50:]}: {sh} then {l}" for sh, ls in SH.items() if sh in props for l in ls if l in props[props.index(sh) + 1:]]
        check('styles: no property is set twice in one rule (no overrides stacked on top)', not over, over[:6])
        notes['codeSize'] = {'bytes': len(html.encode('utf-8')), 'definitions': len(defs), 'cssRules': len(rules)}
    step('hygiene', f_hygiene)

    # ---- 1. the page as it is now ----
    load(NOW)
    notes['version'] = ev("() => typeof APP_VERSION !== 'undefined' ? APP_VERSION : '?'")
    check('page loads and draws', 'Something went wrong' not in view() and ev("() => !!document.getElementById('view')"))
    sc = ev("() => typeof selfCheck === 'function' ? selfCheck() : null"); notes['selfCheck'] = sc
    check('in-page self-check: nothing that needs fixing', sc is not None and sc['st'] != 'bad', [x for x in (sc or {}).get('items', []) if x['st'] == 'bad'])
    scr = ev("() => typeof screenCheck === 'function' ? screenCheck() : null"); notes['screenCheck'] = scr
    check('in-page screen check: every section and Rory\'s report', scr is not None and not scr['bad'], (scr or {}).get('bad'))
    sweep('now')
    ev("() => { S.tab = 'today'; S.todayOpen = ''; render(); }")
    if A.shots: pg.screenshot(path=os.path.join(A.shots, 'today.png'), full_page=True)
    for sheet in ['check', 'log', 'add']:
        ev(f"() => {{ S.tab = 'today'; S.todayOpen = '{sheet}'; render(); }}")
        check(f'Today sheet "{sheet}" opens', ev("() => !!document.querySelector('.ios-sheet')") and not any(s in view() for s in BAD))
    ev("() => { S.todayOpen = ''; S.tab = 'week'; render(); }")
    check('Week: report for Rory on the page', 'Download PDF' in view() or 'PDF' in view())
    ev("() => { S.canWrite = false; render(); }"); rv = view()
    rfit = ev(PROBE); check("Rory's view fits the phone screen", not rfit, rfit[:8])
    check("Rory's view: the report only, no forms (but the box for his own answers and his notification choices)", not ev("() => [...document.querySelectorAll('#view input, #view select')].some(x => !x.closest('.cmpans, .ntf'))") and not any(s in rv for s in BAD))
    if A.shots: pg.screenshot(path=os.path.join(A.shots, 'rory.png'), full_page=True)
    ev("() => { S.canWrite = true; S.tab = 'week'; render(); }")
    if A.lib:
        try:
            pg.click('button[data-act="pdf"]', timeout=5000)
            for _ in range(40):
                if ev("() => window.__saved.length"): break
                w(500)
            check('PDF for Rory is made', ev("() => window.__saved.some(x => /\\.pdf$/.test(x.name))"), ev("() => window.__saved"))
        except Exception as e: check('PDF for Rory is made', False, e)
    else: notes['pdf'] = 'skipped: no PDF libraries given'
    num = lambda js: ev(f"() => {{ const v = {js}; return typeof v === 'number' ? Math.round(v * 100) / 100 : v; }}")
    step('core numbers', lambda: check('core numbers are numbers (Joint, Bills Pocket, card, forecast, review, advisor)', all(isinstance(x, (int, float)) for x in ev("""() => { const ws = weekStartOf(today()), A = dueAdvice(), R = pocketReview(), F = enForecast();
      return [jointStart().v, jointShow(ws).v, pocketStart().v, cardState() ? cardState().bal : 0, A ? A.base.min.v : 0, R && R.safe != null ? R.safe : 0, F ? F.cost : 0, flow().free]; }""")) and bool(ev("() => advisor() && advisor().head"))))

    # ---- 2. a purchase from the Joint account, and undo ----
    def f_purchase():
        load(NOW); j0 = num('jointStart().v')
        ev(f"() => {{ S.f.spend = {{date: '{NOW.date()}', what: 'Kit test shop', amount: '12.34', cat: 'Groceries', paidFrom: 'joint', who: 'both', kind: 'need', told: 'before', note: ''}}; }}"); ev("async () => { await spendSave(); }"); w()
        j1 = num('jointStart().v'); check('purchase from Joint: Joint −€12.34', abs(j0 - 12.34 - j1) < .01, f'{j0} -> {j1}')
        check('a purchase logged after a money check on the same day counts in the next money check', ev("() => { const c = sortedChecks().filter(chkComplete).pop(); if (!c || !c.at) return true; return flowRows(addDays(pd(c.date), -1), today(), 0, {sA: c.at, sZ: new Date(Date.now() + 6e4).toISOString()}).some(x => x.name === 'Kit test shop'); }"))
        check('purchase shows in the week and the report', ev("() => weekSpending(weekStartOf(today())).some(x => x.what === 'Kit test shop')"))
        sid = ev("() => S.spending.find(x => x.what === 'Kit test shop').id"); act('spendDel', id=sid); act('spendDel', id=sid)
        check('deleting it puts Joint back', abs(num('jointStart().v') - j0) < .01)
    step('purchase', f_purchase)

    # ---- 3. Add money, and undo ----
    def f_add():
        load(NOW); j0 = num('jointStart().v'); ws = "weekStartOf(today())"
        ev(f"() => {{ S.f.add = {{date: '{NOW.date()}', amount: '25', to: 'joint', who: 'thiago', how: 'cash', note: 'kit'}}; }}"); act('addSave')
        check('Add money: saved with who and where from', ev("() => S.moves.some(m => m.added && m.note === 'kit')"), ev("() => S.err"))
        check('Add money: Joint +€25', abs(num('jointStart().v') - j0 - 25) < .01)
        check('Add money: in the report heads-up', ev(f"() => headsUp({ws}, reportData({ws}), true).some(x => x.t.startsWith('Money added'))"))
        mid = ev("() => S.moves.find(m => m.note === 'kit').id"); act('mvDel', id=mid); act('mvDel', id=mid)
        check('Add money: Undo takes it back', abs(num('jointStart().v') - j0) < .01 and not ev("() => S.moves.some(m => m.note === 'kit')"))
    step('add money', f_add)

    # ---- 4. Pay: confirm a bill on its day, and undo ----
    def f_pay():
        load(NOW)
        for k in range(0, 21):
            d = NOW + datetime.timedelta(days=k); at(d.replace(hour=12, minute=0))
            it = ev("() => { const x = payToDo().find(y => y.kind === 'bill' && y.b && y.key); return x ? {key: x.key, id: x.b.id, name: x.b.name} : null; }")
            if it: break
        if not it: notes['pay'] = 'no bill due in the next 3 weeks'; return
        h0 = ev(f"() => (S.bills.find(b => b.id === '{it['id']}').history || []).length")
        ev(f"async () => {{ await ppSave({json.dumps(it['key'])}, true); }}"); w(600)
        h = ev(f"() => S.bills.find(b => b.id === '{it['id']}').history || []")
        check(f"Pay: confirming {it['name']} writes its history", len(h) == h0 + 1)
        last = max(h, key=lambda x: x.get('at', ''))
        act('ppUndo', id=it['id'], at=last['at'])
        check(f"Pay: Undo puts {it['name']} back", len(ev(f"() => S.bills.find(b => b.id === '{it['id']}').history || []")) == h0 and any(x['key'] == it['key'] for x in ev("() => payToDo().map(x => ({key: x.key}))")))
    step('pay', f_pay)

    # ---- 5. a whole week: transfers on payday, card payment, the Sunday money check, delete it ----
    def f_week():
        load(NOW)
        info = ev("""() => { for (let i = 0; i < 4; i++){ const ws = addDays(weekStartOf(today()), 7 * i), tr = (S.weeks[iso(ws)] || {}).transfers || {};
            const steps = stepsFor(ws).filter(x => x.amount != null && x.id !== 'card'); if (steps.some(x => !tr[x.id])) return {ws: iso(ws), pay: iso(cardPayday(ws)), ids: steps.map(x => x.id)}; } return null; }""")
        if not info: notes['week'] = 'no open week in the next 4'; return
        pdy = datetime.datetime.fromisoformat(info['pay']).replace(hour=19); at(pdy)
        for sid in info['ids']:
            if sid == 'aib': continue
            if not ev(f"() => !!((S.weeks['{info['ws']}'] || {{}}).transfers || {{}})['{sid}']"): act('stepDone', w=info['ws'], id=sid)
        plan = ev("() => num(st().cardWeekly)") or 100
        act('cardWk', w=info['ws'], v=str(plan))
        tr = ev(f"() => (S.weeks['{info['ws']}'] || {{}}).transfers || {{}}")
        check(f"week of {info['ws']}: every transfer ticked on payday", all(tr.get(x) for x in info['ids']) and tr.get('card'), tr)
        check('card payment logged with the week', bool(ev(f"() => weekCardPay('{info['ws']}')")))
        check('Pay has no transfers left for the week', not ev(f"() => payToDo().some(x => x.kind === 'step' || x.kind === 'card')"))
        check('Joint tile: no "once the pays are in" after everything is done', not ev(f"() => jointShow(pd('{info['ws']}')).pending"))
        sun = datetime.datetime.fromisoformat(info['ws']) + datetime.timedelta(days=6, hours=20); at(sun)
        c = ev("""() => { const c0 = sortedChecks().filter(c => ['joint','bills','vaults','ef','aib','card'].every(k => has(c[k]))).pop(); if (!c0) return null;
            const rows = flowRows(pd(c0.date), today(), c0.card), sum = rows.reduce((t, r) => t + r.amt, 0), card = cardState() ? cardState().bal : num(c0.card);
            const old = num(c0.joint) + num(c0.bills) + num(c0.vaults) + num(c0.ef) + num(c0.aib) - num(c0.card);
            const joint = Math.round((old + sum - (num(c0.bills) + num(c0.vaults) + num(c0.ef) + num(c0.aib)) + card) * 100) / 100;
            return {joint, bills: num(c0.bills), vaults: num(c0.vaults), ef: num(c0.ef), aib: num(c0.aib), card: Math.round(card * 100) / 100, cardBefore: card}; }""")
        if not c: notes['check'] = 'no complete money check to start from'; return
        ev(f"() => {{ S.f.chk = {{date: iso(today()), joint: '{c['joint']}', bills: '{c['bills']}', vaults: '{c['vaults']}', ef: '{c['ef']}', aib: '{c['aib']}', card: '{c['card']}', kwh: '', note: ''}}; S.tab = 'week'; render(); }}"); act('chkSave'); w(600)
        r = ev("() => { const r = latestRec(); return r && {ok: r.ok, diff: Math.round((r.diff ?? r.gap ?? 0) * 100) / 100}; }")
        check('Sunday money check: adds up with everything logged', r and r['ok'] and abs(r['diff']) < .02, r)
        check('the check sets the card balance', abs(num('cardState().bal') - c['card']) < .01)
        cid = ev("() => S.checks.slice().sort((a, b) => (a.at || '').localeCompare(b.at || '')).pop().id"); act('chkDel', id=cid); act('chkDel', id=cid)
        check('deleting the check undoes it', not ev(f"() => S.checks.some(x => x.id === '{cid}')") and abs(num('cardState().bal') - c['cardBefore']) < .01)
        ev("() => { S.tab = 'week'; render(); }")
        check("the week's report draws after the whole week", not any(s in view() for s in BAD))
    step('week', f_week)

    # ---- 5b. two money checks on the same day: the later one is the one that counts ----
    def f_sameday():
        load(NOW)
        c = ev("() => { const c0 = sortedChecks().filter(c => ['joint','bills','vaults','ef','aib','card'].every(k => has(c[k]))).pop(); return c0 ? {joint: num(c0.joint), bills: num(c0.bills), vaults: num(c0.vaults), ef: num(c0.ef), aib: num(c0.aib), card: num(c0.card)} : null; }")
        if not c: return
        for k in range(2):
            ev(f"() => {{ S.f.chk = {{date: iso(today()), joint: '{c['joint'] + k}', bills: '{c['bills']}', vaults: '{c['vaults']}', ef: '{c['ef']}', aib: '{c['aib']}', card: '{c['card']}', kwh: '', note: ''}}; S.tab = 'week'; render(); }}"); act('chkSave'); w(400)
            pg.clock.set_fixed_time(iso(NOW + datetime.timedelta(minutes=5 * (k + 1)))); 
        last = ev("() => { const r = latestRec(); return r ? num(r.c1.joint) : null; }")
        check('two money checks on the same day: the later one counts', last is not None and abs(last - (c['joint'] + 1)) < .01, last)
    step('same-day checks', f_sameday)

    # ---- 6. Bills Pocket touched by hand, and put back ----
    def f_rule1():
        load(NOW); o0 = num("potOwed('bills').owe")
        ev(f"() => {{ S.f.mv = {{date: '{NOW.date()}', from: 'bills', to: 'joint', amount: '10', note: 'kit', kind: 'extra', bill: ''}}; }}"); act('mvSave')
        check('Bills Pocket by hand: €10 more to put back', abs(num("potOwed('bills').owe") - o0 - 10) < .01 and ev("() => todoList().some(x => x.txt.startsWith('Put '))"))
        ev(f"() => {{ S.f.mv = {{date: '{NOW.date()}', from: 'joint', to: 'bills', amount: '10', note: 'kit back', kind: 'extra', bill: ''}}; }}"); act('mvSave')
        check('put back: owed goes back to where it was', abs(num("potOwed('bills').owe") - o0) < .01, ev("() => S.err"))
    step('rule 1', f_rule1)

    # ---- 7. electricity: a lower month-to-date and a future day are refused ----
    def f_energy():
        load(NOW)
        check('electricity: a day that hasn\'t happened is refused', bool(ev(f"() => enReadCheck('{(NOW + datetime.timedelta(days=3)).date()}', 50)")))
        last = ev("() => { const r = (EN().readings || []).filter(x => x.upTo).sort((a, b) => a.upTo.localeCompare(b.upTo)).pop(); return r || null; }")
        if last and num(f"pd('{last['upTo']}') <= today() ? 1 : 0"):
            nxt = ev(f"() => {{ const d = addDays(pd('{last['upTo']}'), 1); return d <= today() && iso(d).slice(0, 7) === '{last['upTo'][:7]}' ? iso(d) : null; }}")
            if nxt and float(last.get('kwh') or 0) > 1: check('electricity: a lower month-to-date is refused', bool(ev(f"() => enReadCheck('{nxt}', {float(last['kwh']) - 1})")))
            if nxt and float(last.get('kwh') or 0) > 1: check('electricity: the same kWh for a later day is refused (the app hadn’t added that day yet)', 'same as' in (ev(f"() => enReadCheck('{nxt}', {float(last['kwh'])})") or ''))
    step('energy', f_energy)

    # ---- 7b. electricity month by month: the app shows one month at a time, counting from the 1st ----
    def f_energy2():
        load(NOW)
        if not ev("() => typeof enMonths === 'function'"): notes['energy2'] = 'no month-by-month view in this version'; return
        F0 = ev("() => { const F = enForecast(); return {used: F.used, kwh: F.kwh, cost: F.cost}; }")
        ms = ev("() => { const F = enForecast(); return enMonths(F).reduce((a, x) => a + x.inKwh, 0); }")
        check('electricity: the months add up to the whole bill period', abs(ms - F0['kwh']) < 1.5, f"{round(ms, 1)} vs {round(F0['kwh'], 1)}")
        usual = ev("() => enUsualRate('')")
        d1 = (NOW.replace(day=1) + datetime.timedelta(days=1)).date()
        if d1 < NOW.date():
            big = round(usual * 31, 1)
            msg = ev(f"() => enReadCheck('{d1}', {big})")
            check("electricity: last month's total saved as this month is refused, and the message says which month", bool(msg) and 'month' in msg, msg)
        lastday = ev("() => enUpTo('last', '')")
        check("electricity: choosing last month saves it as that month's final total", lastday == ev("() => iso(addDays(enMonthStart(today()), -1))"), lastday)
        # a new number for the same month replaces the old one: only the difference counts
        mk = ev("() => iso(today()).slice(0, 7)")
        cur = ev(f"() => {{ const r = EN().readings.filter(x => x.upTo && x.upTo.slice(0, 7) === '{mk}').sort((a, b) => a.upTo.localeCompare(b.upTo)).pop(); return r || null; }}")
        y = (NOW - datetime.timedelta(days=1)).date()
        if cur and cur['upTo'] < str(y):
            u0 = ev("() => enForecast().used")
            ok = ev(f"async () => !!(await enReadSave('{y}', {float(cur['kwh']) + 10}))"); w(500)
            u1 = ev("() => enForecast().used")
            check('electricity: a new reading adds only what changed (+10 kWh), never the whole number again', ok and abs(u1 - u0 - 10) < .6, f'{round(u0, 1)} -> {round(u1, 1)}')
        elif not cur and NOW.day >= 3:
            u0 = ev("() => enForecast().used")
            ok = ev(f"async () => !!(await enReadSave('{y}', {round(usual * (y.day), 1)}))"); w(500)
            ok2 = ev(f"async () => !!(await enReadSave('{y}', {round(usual * (y.day), 1) + 10}))"); w(500)
            u1 = ev("() => enForecast().used")
            check('electricity: saving the same day twice replaces it, never adds both', ok and ok2 and abs(u1 - u0 - round(usual * y.day, 1) - 10) < 1, f'{round(u0, 1)} -> {round(u1, 1)}')
        check('self-check: no reading looks like the wrong month', not ev("() => enSuspect().length"), ev("() => enSuspect().map(x => x.r.upTo + ' ' + x.r.kwh)"))
        ev("() => { S.tab = 'money'; S.sub.money = 'energy'; render(); }")
        v = view()
        check('Electricity tab: month by month and the reading form with the month choice', 'The bill, month by month' in v and 'Which month does the app show?' in v and not any(s in v for s in BAD))
    step('energy month by month', f_energy2)

    # ---- 8. change how a bill is paid, from a date ----
    def f_change():
        load(NOW)
        b = ev("() => { const x = S.bills.find(b => b.active !== false && (b.freq || 'monthly') === 'monthly' && num(b.dueDay) >= 1 && num(b.dueDay) <= 26 && b.id !== 'electricity' && !b.endsOn && !b.startsOn && !(b.was || []).some(w => w.until >= iso(today()))); return x ? {id: x.id, day: num(x.dueDay), was: (x.was || []).length, n: S.bills.length} : null; }")
        if not b: notes['change'] = 'no monthly bill to try'; return
        ev("() => { S.tab = 'money'; S.sub.money = 'bills'; render(); }"); act('billEdit', id=b['id'])
        nd = b['day'] + 2; pg.fill('#f_bill_dueDay', str(nd)); w()
        if ev("() => !!document.getElementById('f_bill_chFrom')"): pg.fill('#f_bill_chFrom', str(NOW.date())); w()
        pg.click('button[data-act="billSave"]'); w(700)
        x = ev(f"() => {{ const x = S.bills.find(b => b.id === '{b['id']}'); return {{day: num(x.dueDay), was: (x.was || []).length, n: S.bills.length, after: occurrences(x, addDays(today(), 1), addDays(today(), 40)).map(d => d.getDate())}}; }}")
        check('bill change from a date: same bill, old way kept, new day after', x['day'] == nd and x['was'] == b['was'] + 1 and x['n'] == b['n'] and all(d == nd or d >= 28 for d in x['after']), x)
    step('bill change', f_change)

    # ---- 9. backup ----
    def f_backup():
        load(NOW); n = ev("() => { const d = backupData(); return Object.keys(d).length; }")
        check('backup file has everything', n >= 10, n)
        miss = ev("() => typeof DATA_COLLS === 'undefined' ? [] : DATA_COLLS.filter(k => !(k in backupData()))")
        check('backup holds every collection the page loads (new ones included)', not miss, miss)
    step('backup', f_backup)

    # ---- 9b. Compare: which plan to take (verdict colours, must-haves, apply with Undo, a free trial, yearly on the card, electricity, phone fit, not in Rory's report) ----
    def f_compare():
        load(NOW)
        if not ev("() => typeof vCompare === 'function'"): notes['compare'] = 'no Compare in this version'; return
        K = "S.compare.find(c => c.name === 'Kit Plus')"
        ev("() => { S.tab = 'today'; S.todayOpen = 'check'; render(); }")
        check('Check a purchase has a "Compare plans" button', ev("() => !!document.querySelector('.ios-sheet [data-act=cmpFromCheck]')"))
        rp = ev("""() => { const xs = activeBills().filter(b => b.account === 'bills' && !b.vault && (b.freq || 'monthly') === 'monthly' && b.id !== 'electricity' && num(b.amount) >= 5 && num(b.amount) < 60).slice(0, 2); return {ids: xs.map(b => b.id), m: xs.reduce((a, b) => a + monthlyEq(b), 0)}; }""")
        if not rp['ids']: notes['compare'] = 'no monthly Bills Pocket bills to replace'; return
        today_m = rp['m']; fam = round(today_m - 2, 2); ind = round(max(1, today_m - 10), 2); nom = round(max(1, today_m - 5), 2)
        D = str(NOW.date())
        SD = [D]   # the start date the test comparisons use (moved with the free-trial moment)
        def setup(trial='', rate=True, name='Kit Plus'):
            ev(f"""() => {{ cmpNewForm({{name: '{name}'}}); const f = S.f.cmp; f.users = '2'; f.account = 'bills'; f.start = '{SD[0]}'; f.use = {json.dumps({'music': 'need', 'tv': 'never', 'storage': 'some'} if rate else {})};
                f.rm = Object.fromEntries({json.dumps(rp['ids'])}.map(id => [id, true]));
                const k0 = f.plans[0]; S.f['cp_' + k0] = {{name: 'Individual', price: '{ind}', per: 'month', covers: '1', feats: 'Music, 50GB'}};
                const k1 = cmpKey(), k2 = cmpKey(); S.f['cp_' + k1] = {{name: 'Family', price: '{fam}', per: 'month', covers: '5', feats: 'Music, TV, 200GB', trial: '{trial}'}};
                S.f['cp_' + k2] = {{name: 'No music', price: '{nom}', per: 'month', covers: '5', feats: 'TV, 200GB'}}; f.plans.push(k1, k2);
                S.tab = 'plan'; S.sub.plan = 'compare'; S.todayOpen = ''; render(); }}""")
        def agree(pid, words='OK, go ahead'):   # ask Rory, then Rory says yes from his own account, in his words
            act('cmpAsk', k=pid); w(300)
            rory_answer('compare', ev(f"() => (S.compare.filter(c => c.rory && c.rory.plan === {json.dumps(pid)} && !c.applied).sort((x, y) => y.rory.asked.localeCompare(x.rory.asked))[0] || {{}}).id"), 'yes', words)   # the open question about this plan
        # how much we use each service comes first: no answer, no question to Rory, until every one is rated
        setup(rate=False)
        u0 = ev("() => { const E = cmpEval(cmpFromForm()); return {h: E.rec.h, n: E.unrated.length}; }"); ev("() => render()")
        check('Compare: until every service is rated (we need it, sometimes, never), there is no verdict and Rory can’t be asked', u0['n'] == 3 and u0['h'].startswith('First: how much') and not ev("() => !!document.querySelector('[data-act=cmpAsk]')"), u0)
        setup()
        E = ev("() => { const E = cmpEval(cmpFromForm()); return E && {rows: E.rows.map(r => ({n: r.p.name, st: r.st, why: r.why.map(w => w.t), m: r.k.monthly, d: r.diff})), rec: E.rec.h, now: E.now.monthly}; }")
        V = {r['n']: r for r in (E or {}).get('rows', [])}
        check('Compare: a plan for 1 when 2 of us use it is red', V.get('Individual', {}).get('st') == 'bad' and any('covers' in w for w in V['Individual']['why']), V.get('Individual'))
        check('Compare: a plan without something we need is red', V.get('No music', {}).get('st') == 'bad' and any('need' in w for w in V['No music']['why']), V.get('No music'))
        check('Compare: cheaper than what it replaces, with every must-have: not red, and recommended', V.get('Family', {}).get('st') in ('ok', 'warn') and 'Family' in E['rec'], {'fam': V.get('Family'), 'rec': E and E['rec']})
        check('Compare: today\'s cost is the bills it replaces', abs(E['now'] - today_m) < .01 and abs(V['Family']['d'] - (fam - today_m)) < .01, E['now'])
        ok = ev("async () => !!(await cmpSave())"); w(400)
        check('Compare: the comparison is saved', ok and ev("() => S.compare.filter(c => c.name === 'Kit Plus').length === 1 && S.compare.find(c => c.name === 'Kit Plus').plans.length === 3"))
        ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }"); v = view()
        cf = ev(PROBE)
        check('Compare: the page draws with the answer on top, and fits the phone screen', 'Which one?' in v and 'Take Family' in v and not any(s in v for s in BAD) and not cf, cf[:8])
        if A.shots: pg.screenshot(path=os.path.join(A.shots, 'compare.png'), full_page=True)
        n0 = num('flow().needBills'); nb0 = ev("() => S.bills.length")
        fid = ev("() => S.compare.find(c => c.name === 'Kit Plus').plans.find(p => p.name === 'Family').id")
        act('cmpApply', k=fid); act('cmpApply', k=fid); w(500)
        _dbg = ev("() => ({st: " + K + ".status, btn: [...document.querySelectorAll('.cmpcard [data-act=cmpApply]')].map(b => b.outerHTML.slice(0, 160))})"); check('Compare: nothing is applied before Rory is asked', _dbg['st'] == 'open' and not _dbg['btn'], _dbg)
        act('cmpAsk', k=fid); w(400)
        q = ev("() => { const c = " + K + "; return {asked: !!(c.rory && c.rory.asked), plan: c.rory && c.rory.planName, log: S.changelog.some(x => x.step === 'ask' && x.cmp === c.id)}; }")
        ws_ = "weekStartOf(today())"
        hu = ev(f"() => headsUp({ws_}, reportData({ws_}), true).map(x => x.t)"); td = ev("() => todoList().map(x => x.txt)")
        ev("() => { S.canWrite = false; render(); }"); rv = view(); rf = ev(PROBE); ev("() => { S.canWrite = true; S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        check('Compare: "Ask Rory" puts the question at the top of his report, in the heads-up and in History, and the To do list waits for his answer', q['asked'] and q['plan'] == 'Family' and q['log'] and 'Thiago is asking you' in rv and 'Kit Plus · Family' in rv and any(t.startswith('Thiago asks') for t in hu) and any('Waiting for Rory' in t for t in td) and not rf, {'q': q, 'hu': hu[:3], 'fit': rf[:4]})
        cid0 = ev("() => " + K + ".id")
        r0 = rory_answer('compare', cid0, 'yes', '')
        check('Compare: Rory’s answer needs his words', not ev("() => (cmpRory(" + K + ") || {}).answer") and 'a few words' in (r0['err'] or ''), r0['err'])
        ra = ev("async () => { const c = " + K + "; try { await S.db.collection('answers').add({kind: 'compare', ref: c.id, asked: c.rory.asked, plan: c.rory.plan, answer: 'yes', said: 'Thiago typing'}); return 'saved'; } catch (e) { return e.code; } }")
        check('Compare: Thiago can’t answer for Rory: the database refuses it', ra == 'invalid_argument' and not ev("() => (cmpRory(" + K + ") || {}).answer"), ra)
        ev("() => { S.canWrite = false; S.canAnswer = true; render(); }"); rv = view(); rf = ev(PROBE); ev("() => { S.canWrite = true; S.canAnswer = false; S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        check('Compare: Rory sees Yes / No and a box for his own words, fitting the phone', 'Your answer, in your words' in rv and 'Only your account can answer' in rv and not rf, rf[:4])
        rory_answer('compare', cid0, 'yes', 'Fine, Family only')
        check('Compare: Rory’s yes comes from his own account, in his words, and the database writes it in History', ev("() => cmpRory(" + K + ").answer") == 'yes' and ev("() => S.changelog.some(x => x.step === 'answer' && /from his own account/.test(x.text) && /Family only/.test(x.text))"))
        r1 = rory_answer('compare', cid0, 'no', 'Changed my mind')
        check('Compare: one answer per question: no quiet second answer', ev("() => cmpRory(" + K + ").answer") == 'yes' and ev("() => S.answers.filter(a => a.ref === " + K + ".id).length") == 1, r1['err'])
        act('cmpApply', k=fid); act('cmpApply', k=fid); w(500)
        a = ev("() => { const c = S.compare.find(c => c.name === 'Kit Plus'), b = c.applied && S.bills.find(x => x.id === c.applied.billId); return {st: c.status, b: b && {name: b.name, startsOn: b.startsOn, amount: b.amount}, ends: " + json.dumps(rp['ids']) + ".map(id => S.bills.find(x => x.id === id).endsOn), log: S.changelog.some(x => /Compare, Kit Plus/.test(x.text || ''))}; }")
        check('Compare: "We both agree" (two clicks) adds the plan as a bill from its first charge and ends the bills it replaces from the start date', a['st'] == 'applied' and a['b'] and a['b']['startsOn'] == D and all(e == D for e in a['ends']) and a['log'], a)
        n1 = num('flow().needBills')
        rd = ev(f"() => reportDetails({ws_}, false, reportData({ws_})).replace(/<[^>]+>/g, ' ')")
        check('Rory’s report: the Decisions card shows the question, his answer as written, and the choice', 'Decisions' in rd and 'Thiago asks: Kit Plus' in rd and 'Fine, Family only' in rd and 'Applied: Kit Plus' in rd, rd[rd.find('Decisions'):][:300] if 'Decisions' in rd else '')
        check('Compare: the weekly bills follow the choice', abs((n1 - n0) - (fam - today_m) * 12 / 52) < .05, f'{n0} -> {n1}')
        ev("() => { S.tab = 'money'; S.sub.money = 'bills'; render(); }"); vb = view()
        check('Bills: the replaced bills show as ended', 'Ended' in vb and not any(s in vb for s in BAD))
        ev("() => { S.canWrite = false; render(); }"); rv = view()
        check("Compare stays out of Rory's report; the plan applied shows there like any bill", 'Compare plans' not in rv and 'Which one?' not in rv and 'We both agree' not in rv and 'Kit Plus · Family' in rv)
        ev("() => { S.canWrite = true; S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        cid = ev("() => S.compare.find(c => c.name === 'Kit Plus').id"); act('cmpUndo', id=cid); act('cmpUndo', id=cid); w(500)
        u = ev("() => ({st: S.compare.find(c => c.name === 'Kit Plus').status, n: S.bills.length, ends: " + json.dumps(rp['ids']) + ".map(id => S.bills.find(x => x.id === id).endsOn || null)})")
        check('Compare: Undo takes it all back', u['st'] == 'open' and u['n'] == nb0 and all(e is None for e in u['ends']) and abs(num('flow().needBills') - n0) < .01, u)
        # deleting comparisons we don't need any more: from the list, with the bin (two taps)
        ev("() => { S.f.cmp = null; S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        cid = ev("() => " + K + ".id")
        check('Compare: every saved comparison has a delete button in the list', ev(f"() => !!document.querySelector('[data-act=cmpDel][data-id=\"{cid}\"]')") and ev("() => document.querySelectorAll('.cmpdel').length === S.compare.length"))
        act('cmpDel', id=cid); cf = ev(PROBE)
        check('Compare: the first tap asks, and the list still fits the phone screen', ev(f"() => S.compare.some(c => c.id === '{cid}')") and 'Tap Delete again' in view() and not cf, cf[:6])
        act('cmpDel', id=cid); w(400)
        check('Compare: the second tap deletes it and History says so', not ev(f"() => S.compare.some(c => c.id === '{cid}')") and ev("() => S.changelog.some(x => /Comparison deleted: Kit Plus/.test(x.text || ''))"))
        at(NOW + datetime.timedelta(minutes=1))   # a minute on: a new comparison and a new question, as in real life (the page clock is fixed)
        setup(); ev("async () => { await cmpSave(); }"); w(300)
        fid = ev("() => " + K + ".plans.find(p => p.name === 'Family').id"); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        agree(fid); act('cmpApply', k=fid); act('cmpApply', k=fid); w(500)
        ap = ev("() => { const c = " + K + "; return {id: c.id, bill: c.applied.billId, n: flow().needBills}; }")
        act('cmpDel', id=ap['id']); act('cmpDel', id=ap['id']); w(500)
        dl = ev(f"() => ({{gone: !S.compare.some(c => c.id === '{ap['id']}'), bill: S.bills.some(b => b.id === '{ap['bill']}' && b.active !== false), ends: " + json.dumps(rp['ids']) + f".map(id => S.bills.find(x => x.id === id).endsOn), n: flow().needBills, open: !!S.f.cmp}})")
        check('Compare: deleting an applied comparison keeps the plan as a bill and the replaced bills ended', dl['gone'] and dl['bill'] and all(e == D for e in dl['ends']) and abs(dl['n'] - ap['n']) < .01 and not dl['open'], dl)
        # the real data: an applied comparison whose bill was removed by hand is flagged, and can be deleted
        stale = ev("() => S.compare.filter(c => c.applied && c.applied.billId && !S.bills.some(b => b.id === c.applied.billId)).map(c => ({id: c.id, name: c.name}))")
        if stale:
            sc2 = ev("() => { S._hc = null; return selfCheck().items.filter(x => x.area === 'Compare').map(x => x.t); }")
            check('self-check: an applied comparison whose bill is gone is flagged', all(any(x['name'] in t for t in sc2) for x in stale), sc2)
            nb = ev("() => S.bills.length")
            for x in stale: act('cmpDel', id=x['id']); act('cmpDel', id=x['id']); w(400)
            check('Compare: it deletes cleanly, and no bill changes', not ev("() => S.compare.some(c => " + json.dumps([x['id'] for x in stale]) + ".includes(c.id))") and ev("() => S.bills.length") == nb and not ev("() => { S._hc = null; return selfCheck().items.some(x => x.area === 'Compare' && x.st !== 'idle'); }"))
        load(NOW)
        # a free trial: the To do list reminds us before it turns into a bill; "We cancelled it" takes it back.
        # It runs at the first moment (now, or up to 3 mornings later) when the test plan isn't red on this data: on a Sunday with the week's transfers not ticked in the copy, the Bills Pocket can look short.
        TT = NOW
        for k in range(4):
            TT = NOW if k == 0 else (NOW + datetime.timedelta(days=k)).replace(hour=9, minute=0, second=0); SD[0] = str(TT.date()); load(TT); setup(trial='10')
            if ev("() => { const E = cmpEval(cmpFromForm()); const r = E && E.rows.find(x => x.p.name === 'Family'); return !!r && r.st !== 'bad'; }"): break
        notes['trialMoment'] = iso(TT)
        load(TT); setup(trial='10'); ev("async () => { await cmpSave(); }"); w(300)
        fid = ev("() => S.compare.find(c => c.name === 'Kit Plus').plans.find(p => p.name === 'Family').id"); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        agree(fid); act('cmpApply', k=fid); act('cmpApply', k=fid); w(500)
        tr = ev("() => { const c = S.compare.find(c => c.name === 'Kit Plus'), b = c.applied && S.bills.find(x => x.id === c.applied.billId); return {ends: c.applied && c.applied.trialEnds, start: b && b.startsOn}; }")
        at(TT + datetime.timedelta(days=7))
        td = ev("() => todoList().filter(x => x.act === 'cmpTrialCancel').map(x => x.txt)")
        check('Compare: a free trial is in the To do list days before it ends, and the bill starts after it', bool(td) and tr['start'] == tr['ends'] and (tr['ends'] or '') > SD[0], {'todo': td, **tr, 'at': iso(TT)})
        act('cmpTrialCancel', id=ev("() => S.compare.find(c => c.name === 'Kit Plus').id")); w(500)
        check('Compare: "We cancelled it" removes the bill and brings back what it replaced', not ev("() => S.bills.some(b => /^Kit Plus/.test(b.name))") and all(e is None for e in ev("() => " + json.dumps(rp['ids']) + ".map(id => S.bills.find(x => x.id === id).endsOn || null)")))
        at(TT + datetime.timedelta(minutes=1)); setup(trial='10'); ev("async () => { await cmpSave(); }"); w(300)   # a minute on: a new comparison and a new question, as in real life (the page clock is fixed)
        KF = "S.compare.find(c => c.id === S.f.cmp._id)"   # the comparison on the form (the cancelled one is still in the list)
        fid = ev("() => " + KF + ".plans.find(p => p.name === 'Family').id"); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        agree(fid); act('cmpApply', k=fid); act('cmpApply', k=fid); w(500)
        tb = ev("() => { const c = " + KF + "; return c && c.applied ? c.applied.billId : null; }"); cid = ev("() => " + KF + ".id"); act('cmpDel', id=cid); act('cmpDel', id=cid); w(500)
        at(TT + datetime.timedelta(days=7))
        td = ev("() => todoList().filter(x => x.act === 'cmpTrialBill').map(x => x.id)")
        if tb: act('cmpTrialBill', id=tb); w(500)
        check('Compare: a free-trial reminder stays after its comparison is deleted, and "We cancelled it" pauses the bill and brings back what it replaced', td == [tb] and bool(tb) and ev(f"() => (S.bills.find(b => b.id === '{tb}') || {{}}).active === false") and all(e is None for e in ev("() => " + json.dumps(rp['ids']) + ".map(id => S.bills.find(x => x.id === id).endsOn || null)")), td)
        at(NOW); SD[0] = D
        # yearly: never on the card while it owes; the Vault needs time
        y = ev(f"""() => {{ const base = {{name: 'Kit yearly', kind: 'sub', users: 1, account: 'card', day: null, start: '{D}', must: [], leaveFee: 0, replaces: [], plans: [{{id: 'y1', name: 'Yearly', price: 99, per: 'year', covers: 1, feats: []}}]}};
            const c1 = cmpEval(base), c2 = cmpEval({{...base, account: 'bills', start: iso(addDays(today(), 10))}}); return {{card: c1.rows[0], bal: cardState() ? cardState().bal : 0, soon: c2.rows[0]}}; }}""")
        check('Compare: a yearly plan on the AIB card while it owes is red', y['bal'] <= .005 or (y['card']['st'] == 'bad' and any('AIB card' in w['t'] for w in y['card']['why'])), y['card']['why'] if y.get('card') else y)
        check('Compare: a yearly plan the Vault can’t save in time is red', y['soon']['st'] == 'bad' and any('Vault' in w['t'] for w in y['soon']['why']))
        # electricity: our real kWh with each offer's rates
        en = ev(f"""() => {{ const T = EN().tariff, base = {{name: 'Kit power', kind: 'energy', users: 2, account: 'bills', day: null, start: '{D}', must: [], leaveFee: 0, replaces: [],
            plans: [{{id: 'e1', name: 'Same rates', standing: T.standing, day: T.day, night: T.night, peak: T.peak, disc: T.discount, feats: []}}, {{id: 'e2', name: 'Dearer', standing: T.standing * 1.2, day: T.day * 1.2, night: T.night * 1.2, peak: T.peak * 1.2, disc: T.discount, feats: []}}]}};
            const E = cmpEval(base); return {{now: E.now.monthly, a: E.rows[0].k.monthly, b: E.rows[1].k.monthly, sa: E.rows[0].st, sb: E.rows[1].st, rec: E.rec.h}}; }}""")
        check('Compare: electricity offers are priced with our real use (same rates = same cost; dearer rates cost more)', en['now'] > 20 and abs(en['a'] - en['now']) < .02 and en['b'] > en['now'] + 5 and en['sa'] == 'ok', en)
        at(NOW + datetime.timedelta(minutes=2))   # a new comparison a little later: its own id and its own question (the page clock is fixed)
        ev("() => { const T = EN().tariff; cmpNewForm({name: 'Kit power', kind: 'energy'}); const k = S.f.cmp.plans[0]; S.f['cp_' + k] = {name: 'Same rates', standing: String(T.standing), day: String(T.day), night: String(T.night), peak: String(T.peak), disc: String(T.discount), promoMonths: '12', lock: '12', feats: 'Smart tariff'}; S.f.cmp.use = {'smart tariff': 'need'}; S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        v = view(); ef = ev(PROBE)
        check('Compare: the electricity form and its answer fit the phone screen', 'kWh a day' in v and 'Which one?' in v and not any(s in v for s in BAD) and not ef, ef[:8])
        if A.shots: pg.screenshot(path=os.path.join(A.shots, 'compare_energy.png'), full_page=True)
        # applying a switch on a later date: the new rates take over on that day; Undo takes it back
        sw = (NOW + datetime.timedelta(days=20)).date()
        ev(f"() => {{ S.f.cmp.start = '{sw}'; render(); }}"); ok = ev("async () => !!(await cmpSave())"); w(300)
        k0 = ev("() => S.f.cmp.plans[0]"); agree(k0); act('cmpApply', k=k0); act('cmpApply', k=k0); w(500)
        sup0 = ev("() => EN().tariff.supplier"); at(NOW + datetime.timedelta(days=21)); sup1 = ev("() => EN().tariff.supplier")
        at(NOW); cid = ev("() => S.compare.find(c => c.kind === 'energy').id"); act('cmpUndo', id=cid); act('cmpUndo', id=cid); w(500)
        check('Compare: an electricity switch on a later date takes over on that day, and Undo takes it back', ok and sup0 != 'Same rates' and sup1 == 'Same rates' and not ev("() => !!(S.energy || {}).tariffNext") and ev("() => S.compare.find(c => c.kind === 'energy').status") == 'open', [sup0, sup1])
        at(NOW + datetime.timedelta(minutes=3)); ev("() => { const c = S.compare.find(c => c.kind === 'energy'); cmpFormFrom(c); }"); k0 = ev("() => S.f.cmp.plans[0]")   # asked again a minute later
        agree(k0); act('cmpApply', k=k0); act('cmpApply', k=k0); w(500)
        ev("() => { S.tab = 'money'; S.sub.money = 'energy'; render(); }"); ve = view(); ef = ev(PROBE)
        act('enSwitchCancel'); act('enSwitchCancel'); w(500)
        check('Electricity: a switch agreed in Compare shows with its date, fits the phone, and "Cancel the switch" takes it back', 'Switching to Same rates' in ve and not ef and not ev("() => !!(S.energy || {}).tariffNext") and ev("() => S.compare.find(c => c.kind === 'energy').status") == 'open', ef[:6])
        # a bigger bundle only for things we don't use; a bigger storage size covers a smaller one
        ub = ev(f"""() => {{ const base = {{name: 'Kit bundle', kind: 'sub', users: 2, account: 'bills', day: null, start: '{D}', must: [], leaveFee: 0, replaces: {json.dumps(rp['ids'])},
            use: {{music: {{lvl: 'need'}}, games: {{lvl: 'never'}}, icloud: {{lvl: 'need', min: 200}}}},
            plans: [{{id: 'a', name: 'Basic', price: {round(today_m - 8, 2)}, per: 'month', covers: 5, feats: ['Music', 'iCloud 200GB']}}, {{id: 'b', name: 'Big', price: {round(today_m - 3, 2)}, per: 'month', covers: 5, feats: ['Music', 'iCloud 2TB', 'Games']}}, {{id: 'c', name: 'Small', price: {round(today_m - 12, 2)}, per: 'month', covers: 5, feats: ['Music', 'iCloud 50GB']}}]}};
            const E = cmpEval(base), E2 = cmpEval({{...base, use: {{...base.use, games: {{lvl: 'some'}}}}}}), f = (E, n) => {{ const r = E.rows.find(x => x.p.name === n); return {{st: r.st, why: r.why.map(w => w.t)}}; }};
            return {{basic: f(E, 'Basic'), big: f(E, 'Big'), small: f(E, 'Small'), big2: f(E2, 'Big'), rec: E.rec.h}}; }}""")
        check('Compare: a bigger plan only for things we never use is red, and says how much a year it would cost', ub['big']['st'] == 'bad' and any('never use' in t and 'a year' in t for t in ub['big']['why']) and ub['rec'] == 'Take Basic', ub)
        check('Compare: if the extra is something we use sometimes, it is amber (worth it only if we really use it)', ub['big2']['st'] == 'warn' and any('sometimes' in t for t in ub['big2']['why']), ub['big2'])
        check('Compare: storage sizes: 2TB covers a 200GB need, 50GB doesn’t', ub['small']['st'] == 'bad' and any('Missing something we need' in t for t in ub['small']['why']) and not any('Missing' in t for t in ub['big']['why']), ub['small'])
        # a plan that costs more waits 48 hours after Rory is asked, even with his yes
        load(NOW); setup(name='Kit Dearer'); ev(f"() => {{ const k = S.f.cmp.plans[1]; S.f['cp_' + k].price = '{round(today_m + 3, 2)}'; render(); }}")
        dr = ev("() => { const c = cmpFromForm(), r = cmpEval(c).rows[1]; return {st: r.st, pid: r.p.id, d: r.diff}; }")
        if dr['st'] != 'bad':
            ev("async () => { await cmpSave(); }"); w(300); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
            agree(dr['pid']); act('cmpApply', k=dr['pid']); act('cmpApply', k=dr['pid']); w(400)
            early = ev("() => S.compare.find(c => c.name === 'Kit Dearer').status")
            at(NOW + datetime.timedelta(hours=49)); ev("() => { const c = S.compare.find(c => c.name === 'Kit Dearer'); cmpFormFrom(c); S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
            act('cmpApply', k=dr['pid']); act('cmpApply', k=dr['pid']); w(500)
            late = ev("() => S.compare.find(c => c.name === 'Kit Dearer').status")
            st49 = ev(f"() => {{ const c = S.compare.find(c => c.name === 'Kit Dearer'), r = cmpEval(c).rows.find(x => x.p.id === '{dr['pid']}'); return r ? r.st : '?'; }}")
            if late != 'applied' and st49 == 'bad': notes['48h'] = 'the dearer test plan turned red by +49h (the money changed): only the wait was checked'
            check('Compare: a plan that costs more waits 48 hours after Rory is asked, even with his yes', early == 'open' and (late == 'applied' or st49 == 'bad'), [early, late, st49])
            cid = ev("() => S.compare.find(c => c.name === 'Kit Dearer').id"); act('cmpUndo', id=cid); act('cmpUndo', id=cid); w(400); at(NOW)
        else: notes['wait48'] = 'the dearer plan is red with this data (no new bills): the 48-hour rule is not reached'
        # Rory says no: the plan is red, it can't be applied, and it can't be asked again for a week
        load(NOW); setup(name='Kit No'); ev("async () => { await cmpSave(); }"); w(300); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        nid = ev("() => S.compare.find(c => c.name === 'Kit No').plans.find(p => p.name === 'Family').id")
        act('cmpAsk', k=nid); w(300); rory_answer('compare', ev("() => S.compare.find(c => c.name === 'Kit No').id"), 'no', 'No, not now')
        act('cmpApply', k=nid); act('cmpApply', k=nid); act('cmpAsk', k=nid); w(400)
        no = ev("() => { const c = S.compare.find(c => c.name === 'Kit No'), r = cmpEval(cmpFromForm()).rows.find(x => x.p.id === c.rory.plan); return {st: r.st, why: r.why.map(w => w.t), status: c.status, ans: cmpRory(c).answer}; }")
        check('Compare: Rory’s no makes the plan red, stops it being applied, and it can’t be asked again for a week', no['st'] == 'bad' and any('Rory said no' in t for t in no['why']) and no['status'] == 'open' and no['ans'] == 'no', no)
        # the plan changes after Rory was asked: he has to be asked again
        load(NOW); setup(name='Kit Stale'); ev("async () => { await cmpSave(); }"); w(300); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }")
        sid = ev("() => S.compare.find(c => c.name === 'Kit Stale').plans.find(p => p.name === 'Family').id")
        act('cmpAsk', k=sid); w(300); ev(f"() => {{ S.f['cp_{sid}'].price = '{round(fam - 1, 2)}'; }}")
        st_ = ev("() => { const c = cmpFromForm(), D = cmpDecision(c, cmpEval(c)); return {stale: D.stale, waiting: D.waiting}; }")
        check('Compare: if the plan or its price changes after Rory was asked, he has to be asked again', st_['stale'] and not st_['waiting'], st_)
        # a bill added by hand: "Did you decide this with Rory?" is asked, and "Not yet" shows in his report
        load(NOW); n0b = ev("() => S.bills.length")
        ev("() => { S.tab = 'money'; S.sub.money = 'bills'; S.billOpen = true; S.f.bill = {freq: 'monthly', account: 'bills', kind: 'debit', active: true, cat: 'TV & streaming', name: 'Kit stream', amount: '9.99', dueDay: '12'}; render(); }")
        box = 'Did you decide this with Rory?' in view(); act('billSave'); w(500)
        e1 = ev("() => S.err") or ''; n1b = ev("() => S.bills.length")
        ev("() => { S.f.bill.agree = 'no'; }"); act('billSave'); w(700)
        hu2 = ev(f"() => headsUp({ws_}, reportData({ws_}), true).map(x => x.t)"); td2 = ev("() => todoList().map(x => x.txt)")
        check('Bills: a new bill asks "Did you decide this with Rory?"; without an answer it isn’t saved; "Not yet" shows in Rory’s report and the To do list', box and 'Rory' in e1 and n1b == n0b and ev("() => S.bills.length") == n0b + 1 and ev("() => S.changelog.some(x => x.kind === 'bill' && x.rory === 'no' && /Kit stream/.test(x.text))") and any(t.startswith('Decided without Rory') for t in hu2) and any('without Rory' in t for t in td2), {'err': e1, 'hu': hu2[:3]})
        # a comparison saved: every screen still draws a month ahead
        at(NOW + datetime.timedelta(days=35)); ev("() => { S.tab = 'plan'; S.sub.plan = 'compare'; render(); }"); v = view()
        check('Compare: draws clean 5 weeks ahead', not any(s in v for s in BAD))
    step('compare', f_compare)

    # ---- 9c. Ready: our emergency kit for 2, cash at home, official updates (Plan → Ready) ----
    def f_ready():
        load(NOW)
        if not ev("() => typeof vReady === 'function'"): notes['ready'] = 'no Ready in this version'; return
        if not ev("() => S.prep.length"): notes['ready'] = 'no kit items in the data'; return
        T = lambda: ev("() => todoList().map(x => x.txt)")
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); rf = ev(PROBE)
        check('Ready: Plan → Ready draws the kit for 2, cash at home, Starlink and power, and fits the phone', all(x in v for x in ['Ready for emergencies', '72 hours for 2', 'Cash at home', 'Starlink and power', 'Why the warnings']) and not rf and not any(s in v for s in BAD), rf[:6])
        # tick an item, undo it
        act('prepHave', id='p2radio'); h1 = num("S.prep.find(y => y.id === 'p2radio').have")
        act('prepUndo', id='p2radio'); h1b = num("S.prep.find(y => y.id === 'p2radio').have"); act('prepUndo', id='p2radio'); h2 = num("S.prep.find(y => y.id === 'p2radio').have")
        check('Ready: "Already have it" ticks an item; Undo needs two taps and takes it back; History says so', h1 == 1 and h1b == 1 and h2 == 0 and ev("() => S.changelog.some(c => c.kind === 'ready' && /undone/.test(c.text))"), [h1, h1b, h2])
        # bought it: a need under Home (not the shop), with its use-by date; undo removes both
        n0 = num("S.spending.length"); sh0 = num("essentialsLearned().amount || 0")
        act('prepBuy', id='p2water'); ev("() => { S.f.ppb_p2water.amount = '5.40'; S.f.ppb_p2water.exp = '2027-10-01'; }"); act('prepBuySave', id='p2water')
        sp = ev("() => { const x = S.prep.find(y => y.id === 'p2water'), s = S.spending.find(y => y.id === x.spendId); return s ? {cat: s.cat, kind: s.kind, amt: s.amount, have: x.have, exp: x.exp} : null; }")
        check('Ready: "Bought it" logs the purchase as a need under Home (not the shop) with its use-by date', bool(sp) and sp['cat'] == 'Home' and sp['kind'] == 'need' and abs(sp['amt'] - 5.4) < .01 and sp['have'] == 4 and sp['exp'] == '2027-10-01' and abs(num("essentialsLearned().amount || 0") - sh0) < .01, sp)
        act('prepUndo', id='p2water'); act('prepUndo', id='p2water')
        check('Ready: Undo on a bought item removes its purchase too', num("S.spending.length") == n0 and num("S.prep.find(y => y.id === 'p2water').have") == 0)
        # something about to expire: To do and Rory's report
        soon = (NOW + datetime.timedelta(days=10)).date().isoformat()
        ev(f"async () => {{ await S.db.doc('prep/p2milk').update({{have: 3, exp: '{soon}'}}); }}"); w()
        ev("() => { S.canWrite = false; S.tab = 'week'; render(); }"); rv = view(); rfit = ev(PROBE); ev("() => { S.canWrite = true; render(); }")
        check("Ready: food about to expire goes on the To do list and in Rory's report (his Ready card fits the phone)", any('UHT milk' in t and 'expires' in t for t in T()) and 'Ready for emergencies' in rv and 'UHT milk' in rv and not rfit, rfit[:4])
        # cash at home: waits for Rory; once agreed, a step moves emergency-fund money to cash at home without changing the month or the Joint
        if ev("() => prepAgreed()"): ev("async () => { await S.db.doc('config/prep').update({agreed: null}); }"); w()
        check("Ready: the cash steps wait for Rory's agreement", not any('Cash at home: take out' in t for t in T()) and any('show Rory the emergency plan' in t for t in T()))
        ev("() => { S.f.ppag = {ag: 'yes', said: 'Grand, small steps'}; }"); act('prepAgree')
        dec = ev("() => weekDecisions(weekStartOf(today())).some(x => x.kind === 'ready' && x.rory === 'yes')")
        check("Ready: Rory's agreement is recorded in his words and shows in his Decisions card", ev("() => PC().agreed && PC().agreed.rory === 'yes' && PC().agreed.said === 'Grand, small steps'") and dec)
        if num("efSeries().amount") < 60:
            ev("() => { S.f.add = {date: iso(today()), amount: '100', to: 'ef', who: 'both', how: 'gift', note: 'kit'}; }"); ev("async () => { await addSave(); }"); w()
        first = datetime.datetime.fromisoformat(ev("() => PC().cash.first") + 'T10:00:00'); at(max(NOW, first))
        e0, j0, m0 = num("efEstimate().amount"), num("jointStart().v"), num("(monthResult(today()) || {}).net || 0")
        due = any('Cash at home: take out' in t for t in T())
        act('prepCash')
        e1, j1, m1, c1 = num("efEstimate().amount"), num("jointStart().v"), num("(monthResult(today()) || {}).net || 0"), num("cashHomeAt()")
        check('Ready: on its day, a cash step puts €50 at home from the emergency fund; the fund still counts it (rule 8); the Joint and the month result don’t change', due and c1 == 50 and abs(e1 - e0) < .01 and abs(j1 - j0) < .01 and abs(m1 - m0) < .01, [due, c1, e0, e1, j0, j1, m0, m1])
        rows = ev("() => flowRows(addDays(today(), -1), today(), 0).filter(r => r.kind === 'cash').map(r => r.amt)")
        check('Ready: the money check counts the cash taken out (so it still adds up), and it isn’t called “emergency fund used” or “moved to a personal account”', rows == [-50] and not any('Refill the emergency fund' in t for t in T()) and not ev("() => S.moves.filter(mvOut).some(m => m.to === 'cash')"), rows)
        nxt = ev("() => cashPlan().next ? iso(cashPlan().next) : null")
        check('Ready: the next cash step comes 4 weeks later, and nothing is due before then', nxt == (max(NOW, first) + datetime.timedelta(days=28)).date().isoformat() and not any('Cash at home: take out' in t for t in T()), nxt)
        mid = ev("() => S.moves.find(m => m.to === 'cash').id"); act('mvDel', id=mid); act('mvDel', id=mid)
        check('Ready: undoing the cash step takes it back everywhere', num("cashHomeAt()") == 0 and abs(num("efEstimate().amount") - e0) < .01)
        load(NOW)
        # official updates: a source not on the list is hidden and flagged
        ev("async () => { const a = (S.prepCfg.alerts || []).concat([{id: 'kitwiki', date: iso(today()), level: 'act', t: 'Kit test from a wiki', url: 'https://en.wikipedia.org/wiki/Test'}]); await S.db.doc('config/prep').update({alerts: a}); }"); w()
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); sc = ev("() => selfCheck().items.filter(x => x.area === 'Ready' && x.st === 'bad').map(x => x.t)")
        check('Ready: an update from a source not on the list (Wikipedia) is hidden and the system check flags it', 'Kit test from a wiki' not in v and not any('Kit test from a wiki' in t for t in T()) and any('wikipedia' in t for t in sc), sc)
        ev("async () => { const a = (S.prepCfg.alerts || []).filter(x => x.id !== 'kitwiki').concat([{id: 'kitmet', date: iso(today()), level: 'act', t: 'Kit test: Status Red wind warning for Wexford', url: 'https://www.met.ie/warnings'}]); await S.db.doc('config/prep').update({alerts: a}); }"); w()
        t0 = ev("() => todoList()[0].txt")
        ev("() => { S.tab = 'today'; render(); }"); vt = view(); tf = ev(PROBE)
        ev("() => { S.canWrite = false; S.tab = 'week'; render(); }"); rv = view(); rfit = ev(PROBE); ev("() => { S.canWrite = true; render(); }")
        check("Ready: an official warning to act on goes first on the To do list, shows on Today and in Rory's report, all fitting the phone", t0.startswith('Official warning: Kit test') and 'Kit test: Status Red' in vt and 'Kit test: Status Red' in rv and not tf and not rfit, [t0[:60], tf[:3], rfit[:3]])
        ev("async () => { await S.db.doc('config/prep').update({alerts: (S.prepCfg.alerts || []).filter(x => x.id !== 'kitmet')}); }"); w()
        # sources: only official ones can raise a warning; news from outside the list is hidden; a warning goes at its end time; old dates show the year
        if ev("() => typeof prepOfficial === 'function'"):
            past = (NOW - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
            ev(f"""async () => {{ const a = (S.prepCfg.alerts || []).concat([{{id: 'kitmedia', date: iso(today()), level: 'act', t: 'Kit test media act', url: 'https://www.gbnews.com/news/test'}}, {{id: 'kitmediainfo', date: iso(today()), level: 'info', t: 'Kit test media background', url: 'https://www.gbnews.com/news/test2'}}, {{id: 'kitleft', date: iso(today()), level: 'info', t: 'Kit test off-list outlet', url: 'https://www.irishtimes.com/x'}}, {{id: 'kitover', date: iso(today()), level: 'watch', t: 'Kit test warning already over', url: 'https://www.met.ie/warnings', until: '{past}'}}]); const w = (S.prepCfg.why || []).concat([{{date: '2025-03-26', t: 'Kit test old reason', url: 'https://ec.europa.eu/x'}}]); await S.db.doc('config/prep').update({{alerts: a, why: w}}); }}"""); w()
            ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); T0 = ev("() => todoList().map(x => x.txt)")
            sc = ev("() => selfCheck().items.filter(x => x.area === 'Ready').map(x => x.st + ' ' + x.t)")
            check('Ready: only an official source can raise a warning (a news “act” is hidden and flagged); news shows only as background, with the outlet named', 'Kit test media act' not in v and not any('Kit test media act' in t for t in T0) and any(t.startswith('warn') and 'GB News' in t for t in sc) and 'Kit test media background' in v and 'GB News' in v, sc[:4])
            check('Ready: an outlet that isn’t on the list is hidden and flagged', 'Kit test off-list outlet' not in v and any('irishtimes.com' in t for t in sc))
            check('Ready: a warning with an end time disappears when it ends; a date from another year shows the year', 'Kit test warning already over' not in v and 'Kit test old reason' in v and '2025' in v)
            ev("async () => { await S.db.doc('config/prep').update({alerts: (S.prepCfg.alerts || []).filter(x => !String(x.id).startsWith('kit')), why: (S.prepCfg.why || []).filter(x => !String(x.t).startsWith('Kit test'))}); }"); w()
        # medicines: kept to 7 days spare
        ev("() => { S.f.ppmed = {name: 'Kit test tablets', who: 'thiago', days: '3'}; }"); act('prepMedAdd')
        low = any('Kit test tablets' in t and '3 days spare' in t for t in T())
        mid2 = ev("() => (S.prep.find(x => x.name === 'Kit test tablets') || {}).id"); act('prepMedDays', id=mid2); ev("() => { S.f.ppmd = {days: '10'}; }"); act('prepMedDaysSave', id=mid2)
        check('Ready: a regular medicine under 7 days spare goes on the To do list, and updating it clears it', low and not any('Kit test tablets' in t for t in T()))
        act('prepDrop', id=mid2); act('prepDrop', id=mid2)
        # big items go on the wishlist; the Starlink plan goes through Compare
        act('prepWish', id='p4station'); wl = ev("() => { const x = S.prep.find(y => y.id === 'p4station'), w = S.wishlist.find(y => y.id === x.wishId); return w ? {k: w.kind, p: w.price, pid: w.prepId} : null; }")
        check('Ready: a big item (power station) goes on the wishlist as a need, linked to the kit', bool(wl) and wl['k'] == 'need' and wl['p'] == 699 and wl['pid'] == 'p4station', wl)
        act('prepCompare'); cp = ev("() => ({n: S.f.cmp && S.f.cmp.plans.length, sub: S.sub.plan, ask: !!document.querySelector('[data-act=cmpAsk]')})")
        check('Ready: "Compare the Starlink plans" opens Compare with the plans, no verdict until every service is rated', cp['n'] == 3 and cp['sub'] == 'compare' and not cp['ask'], cp)
        # the backup holds the kit and the Ready settings
        check('Ready: the backup holds the kit and config/prep', ev("() => { const d = backupData(); return (d.prep || []).length > 0 && !!(d.config.prep || {}).cash; }"))
    step('ready', f_ready)

    # ---- 9d. a bill paid early by hand: it leaves on the day it was paid, once, and Undo takes it back ----
    def f_early():
        load(NOW)
        if not ev("() => typeof payEarly === 'function'"): notes['early'] = 'no paid-early in this version'; return
        at(NOW + datetime.timedelta(days=1))
        it = ev("() => { const x = payEarlyList().find(y => y.b.account === 'bills' && !y.b.variable); return x ? {key: x.key, id: x.b.id, due: iso(x.d), amt: Math.round(x.amount * 100) / 100} : null; }")
        if not it: notes['early'] = 'no Bills Pocket bill due in the next 31 days'; return
        p0 = num("pocketStart().v")
        ev("() => { S.tab = 'pay'; S.payOpen = 'early'; render(); }"); v = view(); pf = ev(PROBE)
        check('Paid early: Pay has “A bill, paid early” with the bills due in the next 31 days, and the form fits the phone', 'A bill, paid early' in v and 'Which bill' in v and not pf, pf[:4])
        ev(f"() => {{ S.f.pe = {{key: '{it['key']}', date: iso(today()), amount: ''}}; }}"); act('payEarly'); w(600)
        p1 = num("pocketStart().v")
        outs = ev(f"() => pocketOut(today(), addDays(pd('{it['due']}'), 2)).filter(o => o.id === '{it['id']}').map(o => iso(o.d))")
        gone = ev(f"() => !payEarlyList().some(x => x.key === '{it['key']}')")
        check('Paid early: the Bills Pocket goes down on the day it was paid, the bill is counted once (not again on its due day), and Pay no longer waits for it', abs(p0 - it['amt'] - p1) < .01 and gone and outs.count(ev("() => iso(today())")) == 1 and it['due'] not in outs, [p0, p1, it, outs])
        hat = ev(f"() => {{ const b = S.bills.find(x => x.id === '{it['id']}'); const h = (b.history || []).find(x => x.due === '{it['due']}'); return h ? h.at : null; }}")
        if hat: act('ppUndo', id=it['id'], at=hat)
        check('Paid early: Undo takes it back (the Bills Pocket and the due day as before)', abs(num("pocketStart().v") - p0) < .01 and ev(f"() => payEarlyList().some(x => x.key === '{it['key']}')"))
    step('paid early', f_early)

    # ---- 9c. the AIB card as the bank has it: real interest from the statement, and what's still pending ----
    def f_card():
        load(NOW)
        if not ev("() => typeof cardIntSave === 'function'"): notes['card'] = 'no real card interest in this version'; return
        if not ev("() => !!cardState() && cardStmtsPast().length > 0"): notes['card'] = 'no card balance or statement out yet'; return
        T = lambda: ev("() => todoList().map(x => x.txt)")
        ev("() => { S.tab = 'money'; S.sub.money = 'debts'; render(); }"); v = view(); pf = ev(PROBE)
        check('Card: Money → Debts has “Interest from the statement” and the balance with what’s still pending, and fits the phone', 'Interest from the statement' in v and 'Balance in the app' in v and not pf, pf[:4])
        stI = ev("() => iso(cardStmtsPast()[0].S)")
        for e in ev(f"() => S.cardlog.filter(e => e.type === 'interest' && e.stmt === '{stI}').map(e => e.id)"): ev(f"async () => {{ await S.db.doc('cardlog/{e}').delete(); }}"); w(200)
        rows = lambda: ev(f"() => {{ const r = flowRows(addDays(pd('{stI}'), -1), addDays(pd('{stI}'), 3), cardState().bal); return r.filter(x => /Card interest/.test(x.name)).map(x => [x.name, Math.round(x.amt * 100) / 100]); }}")
        r0 = rows(); bal0 = num("cardState().bal")
        todo0 = any('type the interest it charged' in t for t in T()) if ev(f"() => dayDiff(pd('{stI}'), today()) <= 20") else True
        check('Card interest: until it’s typed, the To do list asks for it and the money uses an estimate', todo0 and len(r0) == 1 and 'estimate' in r0[0][0], [r0, T()[:6]])
        ev(f"() => {{ S.f.ci = {{stmt: '{stI}', amount: '19.52'}}; }}"); act('cardInt'); w(500)
        r1 = rows(); e1 = ev(f"() => cardIntFor('{stI}')")
        ok_bal = abs(num("cardState().bal") - bal0) < .01 if ev(f"() => cardState().last.date > iso(addDays(pd('{stI}'), 1)) || (cardState().last.date === iso(addDays(pd('{stI}'), 1)))") else abs(num("cardState().bal") - bal0 - 19.52) < .01
        check('Card interest: the real amount replaces the estimate (once, the day after the statement), the To do goes, History says so', bool(e1) and r1 == [[f"Card interest on the {ev(f'() => dshort(pd(\'{stI}\'))')} statement", -19.52]] and not any('type the interest it charged' in t for t in T()) and ev("() => S.changelog.some(c => c.kind === 'card' && /interest on the/.test(c.text))") and ok_bal, [r1, e1])
        rate = num("cardRateY()"); apr = num("num(st().cardApr) / 100")
        check('Card interest: the next estimates use the rate the statement really charged (never above 1.5 × the APR)', rate > 0 and rate <= apr * 1.5 + 1e-9 and ev("() => cardRateFromStmt()"), [rate, apr])
        if ev("() => typeof cardIntPanel === 'function'"):
            ev("() => { S.tab = 'money'; S.sub.money = 'debts'; render(); }"); v = view(); pf = ev(PROBE)
            L = ev("() => cardIntMonths().map(x => ({v: x.v == null ? null : Math.round(x.v * 100) / 100, real: !!x.real, est: !!x.est}))")
            check('Card interest chart: Money → Debts shows the interest month by month (the real one from the statement, the next one estimated), and fits the phone', 'Card interest, month by month' in v and any(x['real'] and x['v'] == 19.52 for x in L) and (sum(1 for x in L if x['est']) <= 1) and 'Average a month' in v and not pf, [L, pf[:3]])
        # typed again for the same statement: replaced, not doubled
        ev(f"() => {{ S.f.ci = {{stmt: '{stI}', amount: '19.50'}}; }}"); act('cardInt'); w(400)
        check('Card interest: typed again for the same statement, it replaces the first (never counted twice)', ev(f"() => S.cardlog.filter(e => e.type === 'interest' && e.stmt === '{stI}').length") == 1 and num(f"cardIntFor('{stI}').amount") == 19.5)
        # self-check: two for the same statement
        ev(f"async () => {{ await S.db.collection('cardlog').add({{type: 'interest', stmt: '{stI}', date: iso(addDays(pd('{stI}'), 1)), amount: 1, at: '{stI}T00:00:00.000Z'}}); }}"); w(300)
        check('Card interest: the self-check flags interest logged twice for one statement', ev("() => { S._hc = null; return selfCheck().items.some(x => /logged twice/.test(x.t)); }"))
        for e in ev(f"() => S.cardlog.filter(e => e.type === 'interest' && e.stmt === '{stI}' && num(e.amount) === 1).map(e => e.id)"): ev(f"async () => {{ await S.db.doc('cardlog/{e}').delete(); }}"); w(200)
        # a later statement, after the last balance: the interest goes onto the card
        nx = ev("() => { const cc = cardCycles(); const c = cc.list.find(x => x.S > today()); return c ? iso(c.S) : null; }")
        if nx:
            at(datetime.datetime.fromisoformat(nx) + datetime.timedelta(days=2, hours=10))
            b0 = num("cardState().bal")
            ev(f"() => {{ S.f.ci = {{stmt: '{nx}', amount: '20.00'}}; }}"); act('cardInt'); w(400)
            check('Card interest: a statement after the last card balance adds its interest to what the card owes', abs(num("cardState().bal") - b0 - 20) < .01, [b0, num("cardState().bal")])
            idn = ev(f"() => cardIntFor('{nx}').id"); act('cardDel', id=idn); w(400)
            check('Card interest: deleting it takes it back (the balance and the estimate as before)', abs(num("cardState().bal") - b0) < .01 and not ev(f"() => !!cardIntFor('{nx}')"))
            at(NOW)
        # the money check: the app's number plus what's still pending = what we really owe
        load(NOW)
        it = ev("() => { S.f.chk = {date: iso(today()), joint: '', bills: '', vaults: '', ef: '', aib: '', card: '', note: '', kwh: ''}; const I = cardPendItems('chk'); return I.buys.slice(0, 2).map(x => ({id: x.id, a: x.a})); }")
        if not it: notes['cardPend'] = 'no card purchases in the last 7 days'; return
        owe = num("cardState().bal"); pend = round(sum(x['a'] for x in it), 2); app = round(owe - pend, 2)
        ev(f"() => {{ S.f.chk.card = '{app}'; S.tab = 'week'; render(); }}"); v0 = view()
        ev("() => { " + ''.join(f"S.f.chk['p_{x['id']}'] = true; " for x in it) + "render(); }"); v1 = view(); pf = ev(PROBE)
        check('Card check: the money check takes the app’s number, lists the card purchases to tick as Pending, says when it’s the same as the system, and fits the phone', 'Still pending in the AIB app?' in v1 and 'same as the system' in v1.lower() and 'less than the system expects' in v0 and not pf, pf[:4])
        c = ev("() => { const c0 = sortedChecks().filter(c => ['joint','bills','vaults','ef','aib'].every(k => has(c[k]))).pop(); return c0 ? {joint: num(c0.joint), bills: num(c0.bills), vaults: num(c0.vaults), ef: num(c0.ef), aib: num(c0.aib)} : null; }")
        if c: ev("() => { " + ''.join(f"S.f.chk.{k} = '{c[k]}'; " for k in c) + "}")
        act('chkSave'); w(500)
        last = ev("() => { const x = sortedChecks().pop(); return {card: num(x.card), app: num(x.cardApp), pend: num(x.cardPend)}; }")
        check('Card check: the check saves what we really owe (app + pending), keeps the app’s number, and the card balance follows', abs(last['card'] - owe) < .01 and abs(last['app'] - app) < .01 and abs(last['pend'] - pend) < .01 and abs(num("cardState().bal") - owe) < .01, [last, owe, app, pend])
        # Debts → Log the balance works the same way
        ev(f"() => {{ S.f.bal = {{date: iso(today()), amount: '{app}', p_{it[0]['id']}: true}}; S.tab = 'money'; S.sub.money = 'debts'; render(); }}"); pf = ev(PROBE)
        act('cardBal'); w(400)
        lb = num("sortedCardlog().filter(e => e.type === 'balance').pop().amount")
        check('Card check: Debts → Log the balance adds the ticked pending purchases too, and fits the phone', abs(lb - round(app + it[0]['a'], 2)) < .01 and not pf, [lb, pf[:3]])
    step('card interest and pending', f_card)

    # ---- 10. the week ahead and a month ahead ----
    # ---- 9d. the clean-up of 8 Nov 2026: one check for each fix, so none comes back ----
    def f_cleanup():
        load(NOW)
        if not ev("() => typeof cmpSaved === 'function' && typeof sinceCheck === 'function'"): notes['cleanup'] = 'before the clean-up'; return
        y = ev("""() => { const c = cmpSaved({name: 'Kit Yard', kind: 'sub', users: 2, account: 'bills', start: iso(addDays(today(), 10)), replaces: [], leaveFee: 0, use: {music: {lvl: 'need', min: null}}, plans: [
            {id: 'm', name: 'Monthly', price: 5, per: 'month', covers: 5, feats: ['Music']}, {id: 'y', name: 'Yearly', price: 48, per: 'year', covers: 5, feats: ['Music']}]});
          const E = cmpEval(c), g = id => E.rows.find(r => r.p.id === id); return {y: g('y').st, m: g('m').why.map(w => w.t)}; }""")
        check('Compare: a yearly plan that is red on its own (the Vault can’t save it in time) isn’t the yardstick for the others', y['y'] == 'bad' and not any('more than Yearly' in t for t in y['m']), y)
        g = ev("""() => { const c = cmpSaved({name: 'Kit Store', kind: 'sub', users: 2, account: 'bills', start: iso(addDays(today(), 10)), replaces: [], leaveFee: 0, use: {music: {lvl: 'need', min: null}, storage: {lvl: 'need', min: 200}}, plans: [
            {id: 's', name: 'Small', price: 5, per: 'month', covers: 5, feats: ['Music', '50GB']}, {id: 'b', name: 'Big', price: 6, per: 'month', covers: 5, feats: ['Music', '2TB']}]});
          const E = cmpEval(c), g = id => E.rows.find(r => r.p.id === id); return {svc: cmpServices(c).map(x => x.key), small: g('s').missNeed, big: g('b').missNeed}; }""")
        check('Compare: a storage size with no name ("2TB") is one Storage service, and a bigger size covers a smaller need', g['svc'] == ['music', 'storage'] and g['small'] and not g['big'], g)
        j = ev("""() => { const out = []; for (const b of activeBills().filter(x => x.account === 'joint' && x.vault)){ const d = occurrences(b, today(), addDays(today(), 400))[0]; if (!d) continue; const ws = weekStartOf(d), we = addDays(ws, 6);
            out.push({b: b.name, inOut: jointOut(ws, we).some(x => x.name === b.name), week: Math.abs(jointWeek(ws).bills - jointOut(ws, we).reduce((t, x) => t + x.amt, 0)) < .005}); } return out; }""")
        if j: check('Joint account: a Joint bill kept in the Vault is paid by the Vault, not taken from the Joint’s week', all(not x['inOut'] and x['week'] for x in j), j)
        else: notes['cleanupJointVault'] = 'no Joint bill kept in the Vault'
        e = ev("""async () => { const t = today(); let d = null; for (let k = 1; k <= 31 && !d; k++){ const x = addDays(t, k); if (pocketOut(x, x).length) d = x; } if (!d) return null;
            const c = sortedChecks().filter(x => has(x.bills)).pop();
            await S.db.collection('checks').add({...c, id: undefined, vaultPrev: undefined, date: iso(d), at: new Date(d.getFullYear(), d.getMonth(), d.getDate(), 8).toISOString(), bills: 500});
            return {d: iso(d), due: pocketOut(d, addDays(d, 1)).reduce((s2, x) => s2 + x.amt, 0)}; }""")
        if e:
            w(300); at(datetime.datetime.fromisoformat(e['d']) + datetime.timedelta(days=1, hours=12))
            v = num('pocketStart().v')
            check('Bills Pocket: a money check before noon on a bill day comes before that day’s bills (they leave once, the day after too)', abs(v - round(500 - e['due'], 2)) < .01, {'v': v, 'expected': round(500 - e['due'], 2), 'day': e['d']})
        load(NOW)
        v0 = num('pocketStart().v')
        ev("""async () => { const y = iso(addDays(today(), -1)); await S.db.collection('spending').add({what: 'Kit late Bills Pocket buy', amount: 9.99, date: y, at: new Date().toISOString(), paidFrom: 'bills', cat: 'Other', kind: 'need', who: 'both', told: 'before'}); }"""); w(300)
        c5 = ev("() => { const c = sortedChecks().filter(x => has(x.bills)).pop(); return {check: c.date, after: c.date >= iso(addDays(today(), -1))}; }")
        v1 = num('pocketStart().v')
        if c5['after']: check('Bills Pocket: a purchase from before the last money check, logged later, isn’t counted again', abs(v1 - v0) < .01, {'before': v0, 'after': v1, **c5})
        else: check('Bills Pocket: a purchase after the last money check, logged later, comes off once', abs((v0 - v1) - 9.99) < .01, {'before': v0, 'after': v1, **c5})
        load(NOW)
        sc = ev("() => screenCheck()")
        check('"Check every screen now" draws the iPhone Today, the three Today sheets and both pages of Rory’s report', ev("() => VIEWS.today === vTodayIOS") and sc['n'] == len(TABS) - 1 + 3 + 2 and not sc['bad'], sc)
        vs = ev("""() => Object.entries(S.weeks).filter(([k, w]) => (w.transfers || {}).vaults && w.vaultSplit && !((w.amounts || {}).vaults || {}).a).map(([k, w]) => ({k, split: Object.values(w.vaultSplit).reduce((t, y) => t + num(y), 0), row: (weekMoves(pd(k)).find(x => /Vault/.test(x.n) && !x.extra) || {}).real}))""")
        if vs: check('Rory’s report: a ticked Vault transfer shows what was really sent that week (its Vault split), not today’s plan', all(x['row'] is not None and abs(x['row'] - x['split']) < .01 for x in vs), vs[:4])
        ows = ev("""() => { const ws = weekStartOf(today()), D = reportData(ws), o = potOwed('bills').owe, used = pocketBuys().some(x => inWeek(x.date, ws)) || movesIn(ws, addDays(ws, 6)).some(m => mvBreak(m) === 1); return {o, used, hu: headsUp(ws, D, true).map(x => x.t).filter(t => /Bills Pocket used/.test(t))}; }""")
        if ows['used'] and ows['o'] > .005: check('Rory’s report: when the Bills Pocket was used and money is still owed, the heads-up says how much is still to put back', any('still to put back' in t for t in ows['hu']), ows)
        else: notes['cleanupOwed'] = 'nothing owed to the Bills Pocket this week'
    step('cleanup', f_cleanup)

    # ---- 9e. where we are: Ready follows the country; the money and Rory's report stay home ----
    def f_where():
        load(NOW)
        if not ev("() => typeof placeNow === 'function'"): notes['where'] = 'no "where we are" in this version'; return
        ev("""async () => { const c = S.prepCfg || {}; await S.db.doc('config/prep').update({where: {country: 'IE', place: 'Wexford', since: iso(today()), by: 'chat'}, alerts: (c.alerts || []).concat([
            {id: 'kw1', date: iso(today()), level: 'act', t: 'Kit home warning', url: 'https://www.met.ie/warnings', what: 'test'},
            {id: 'kw2', date: iso(today()), level: 'act', t: 'Kit UK warning', url: 'https://www.gov.uk/guidance/kit', what: 'test', country: 'GB'},
            {id: 'kw3', date: iso(today()), level: 'act', t: 'Kit UK news act', url: 'https://www.bbc.co.uk/news/kit', what: 'test', country: 'GB'},
            {id: 'kw4', date: iso(today()), level: 'info', t: 'Kit unknown country', url: 'https://www.gov.ie/kit', what: 'test', country: 'XX'}])}); }"""); w(400)
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); fit = ev(PROBE)
        check('Ready: "Where we are" shows the country, its emergency numbers and the choice of country, and fits the phone screen', 'Where we are' in v and 'Ireland, Wexford' in v and '112 or 999' in v and ev("() => document.querySelectorAll('select[data-act=prepWhere] option').length") == ev("() => Object.keys(PLACES).length") and not fit, fit[:6])
        pl = ev("""() => { const doms = {}, bad = []; for (const [k, p] of Object.entries(PLACES)){ if (!/^[A-Z]{2}$/.test(k) || !REGIONS.includes(p.r) || !p.name || !p.emergency || !p.sources || !(p.official || []).length) bad.push(k); for (const d of p.official || []){ if (doms[d] && doms[d] !== k) bad.push(`${k}: ${d} also ${doms[d]}`); doms[d] = k; } }
            return {n: Object.keys(PLACES).length, regions: REGIONS.filter(r => Object.values(PLACES).some(p => p.r === r)).length, groups: document.querySelectorAll('select[data-act=prepWhere] optgroup').length, bad}; }""")
        check('Where we are: every country on the list has its region, emergency numbers and its own official sources, grouped by region in one list', pl['n'] >= 50 and pl['regions'] == 7 and pl['groups'] == 7 and not pl['bad'], pl)
        home = ev("() => ({mine: prepAlerts().map(a => a.t), todo: todoList().filter(x => /Official warning/.test(x.txt)).map(x => x.txt)})")
        check('Ready at home: the warnings for another country stay hidden', 'Kit home warning' in home['mine'] and not any('Kit UK' in t for t in home['mine']) and not any('UK' in t for t in home['todo']), home)
        m0 = ev("() => [flow().free, pocketStart().v, jointShow(weekStartOf(today())).v]")
        pick('prepWhere', 'GB'); w(400)
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); fit = ev(PROBE)
        away = ev("""() => ({w: (S.prepCfg || {}).where, log: S.changelog.some(x => x.kind === 'ready' && /Where we are: the UK \(set by hand/.test(x.text || '')), mine: prepAlerts().map(a => a.t), todo: todoList().filter(x => /Official warning/.test(x.txt)).map(x => x.txt),
            rory: prepAlerts('home').map(a => a.t), heads: headsUp(weekStartOf(today()), reportData(weekStartOf(today())), true).map(x => x.t), m: [flow().free, pocketStart().v, jointShow(weekStartOf(today())).v]})""")
        check('Ready away (the UK, set by hand): its official warning shows and goes on the To do list, a news "act" stays hidden, home warnings stay, and History says so', away['w'] and away['w']['country'] == 'GB' and away['w']['by'] == 'hand' and away['log'] and 'Kit UK warning' in away['mine'] and 'Kit home warning' in away['mine'] and 'Kit UK news act' not in away['mine'] and any('in the UK' in t for t in away['todo']) and 'The UK' in v and '999 or 112' in v and not fit, {k: away[k] for k in ['w', 'mine', 'todo']})
        check('Away from home: Rory’s report keeps the home warnings only, and no money number changes', 'Kit UK warning' not in away['rory'] and 'Kit home warning' in away['rory'] and not any('Kit UK' in t for t in away['heads']) and all(abs(a - b) < .005 for a, b in zip(m0, away['m'])), {'rory': away['rory'], 'm0': m0, 'm': away['m']})
        ev("() => { S.canWrite = false; render(); }"); rv = view(); ev("() => { S.canWrite = true; render(); }")
        check('Away from home: Rory’s view has no country switch and no warning from the other country', 'Kit UK' not in rv and 'Where we are' not in rv)
        ev("""async () => { const c = S.prepCfg || {}; await S.db.doc('config/prep').update({alerts: (c.alerts || []).concat([{id: 'kw5', date: iso(today()), level: 'act', t: 'Kit Japan warning', url: 'https://www.jma.go.jp/kit', what: 'test', country: 'JP'}])}); }"""); w(300)
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); pick('prepWhere', 'JP'); w(400)
        ev("() => { S.tab = 'plan'; S.sub.plan = 'ready'; render(); }"); v = view(); fit = ev(PROBE)
        jp = ev("() => ({c: placeNow().code, mine: prepAlerts().map(a => a.t), sel: document.querySelector('select[data-act=prepWhere]').value})")
        check('Where we are: a country far away (Japan) picked from the list shows its emergency numbers and its own official warning, the UK one goes, and it fits the phone screen', jp['c'] == 'JP' and jp['sel'] == 'JP' and 'Kit Japan warning' in jp['mine'] and not any('Kit UK' in t for t in jp['mine']) and '110 police, 119 fire and ambulance' in v and not fit, {'jp': jp, 'fit': fit[:4]})
        pick('prepWhere', 'IE'); w(400)
        back = ev("() => ({c: placeNow().code, mine: prepAlerts().map(a => a.t)})")
        check('Back home: Ready shows Ireland again and the other countries’ warnings go', back['c'] == 'IE' and not any('Kit UK' in t or 'Kit Japan' in t for t in back['mine']), back)
        sc = ev("() => { S._hc = null; return selfCheck().items.filter(x => x.area === 'Ready').map(x => x.t); }")
        check('self-check: a warning for a country that isn’t on the list is flagged (and hidden)', any('isn’t on the list' in t and 'XX' in t for t in sc) and 'Kit unknown country' not in back['mine'], sc[:4])
    step('where', f_where)

    def f_ahead():
        load(NOW)
        for label, dt in [('next payday', None), ('next Sunday evening', NOW + datetime.timedelta(days=(6 - NOW.weekday()) % 7, hours=20 - NOW.hour)), ('in 5 weeks', NOW + datetime.timedelta(days=35))]:
            if dt is None:
                pdy = ev("() => iso(cardPayday(weekStartOf(today())))"); dt = datetime.datetime.fromisoformat(pdy).replace(hour=18)
                if dt < NOW: dt = datetime.datetime.fromisoformat(ev("() => iso(cardPayday(addDays(weekStartOf(today()), 7)))")).replace(hour=18)
            at(dt); sweep(label)
    # ---- 12. the wishlist: a want over the limit waits for Rory's yes, from his own account ----
    def f_answers():
        load(NOW)
        th = ev("() => num(st().ruleThreshold) || 20")
        def wish(what, price, kind='want'):
            ev(f"() => {{ S.f.wish = {{what: {json.dumps(what)}, price: '{price}', who: 'both', kind: '{kind}', prio: '2', told: 'yes'}}; }}"); act('wishSave'); w(400)
            return ev(f"() => (S.wishlist.find(x => x.what === {json.dumps(what)}) || {{}}).id")
        vd = lambda i: ev(f"() => wishVerdict(S.wishlist.find(x => x.id === '{i}'))")
        big = wish('Kit headphones', th + 30); v0 = vd(big)
        check('Wishlist: a want over the limit waits for Rory’s yes, and the question is in History', v0['v'] == 'Waiting for Rory' and ev(f"() => S.changelog.some(x => x.step === 'ask' && x.wish === '{big}')"), v0)
        hu = ev("() => headsUp(weekStartOf(today()), reportData(weekStartOf(today())), true).map(x => x.t)")
        ev("() => { S.canWrite = false; S.canAnswer = true; render(); }"); rv = view(); rf = ev(PROBE); ev("() => { S.canWrite = true; S.canAnswer = false; render(); }")
        check('Wishlist: Rory sees it at the top of his report, with Yes / No, in the heads-up, fitting the phone', 'Thiago is asking you' in rv and 'Kit headphones' in rv and 'Your answer, in your words' in rv and any('Kit headphones' in t for t in hu) and not rf, {'hu': hu[:3], 'fit': rf[:4]})
        small = wish('Kit socks', max(1, th - 5)); v1 = vd(small)
        check('Wishlist: a want under the limit works as before (Rory knows, no question)', v1['v'] != 'Waiting for Rory' and not ev(f"() => S.changelog.some(x => x.step === 'ask' && x.wish === '{small}')"), v1)
        ra = ev(f"async () => {{ const w = S.wishlist.find(x => x.id === '{big}'); try {{ await S.db.collection('answers').add({{kind: 'wish', ref: w.id, asked: w.asked, answer: 'yes', said: 'Thiago typing'}}); return 'saved'; }} catch (e) {{ return e.code; }} }}")
        check('Wishlist: Thiago can’t answer for Rory', ra == 'invalid_argument' and vd(big)['v'] == 'Waiting for Rory', ra)
        rory_answer('wish', big, 'yes', 'Go on, you deserve it'); v2 = vd(big)
        check('Wishlist: Rory’s yes, from his account, moves it on (the 48 hours and the money still decide), and History says so', v2['v'] not in ('Waiting for Rory', 'Rory said no') and ev(f"() => S.changelog.some(x => x.step === 'answer' && x.wish === '{big}' && /from his own account/.test(x.text) && /you deserve it/.test(x.text))"), v2)
        rd = ev("() => reportDetails(weekStartOf(today()), false, reportData(weekStartOf(today()))).replace(/<[^>]+>/g, ' ')")
        check('Wishlist: Rory’s Decisions card shows the question and his answer as he wrote it', 'Thiago asks: Kit headphones' in rd and 'you deserve it' in rd, rd[rd.find('Decisions'):][:300] if 'Decisions' in rd else '')
        no = wish('Kit speaker', th + 60); rory_answer('wish', no, 'no', 'Not this month'); v3 = vd(no)
        ev("() => { S.tab = 'plan'; S.sub.plan = 'advisor'; render(); }"); btn0 = ev(f"() => !!document.querySelector('[data-act=wishAskAgain][data-id=\"{no}\"]')")
        check('Wishlist: Rory’s no, in his words, stops it, and it can’t be asked again for a week', v3['v'] == 'Rory said no' and 'Not this month' in v3['why'] and not btn0, v3)
        at(NOW + datetime.timedelta(days=8)); ev("() => { S.tab = 'plan'; S.sub.plan = 'advisor'; render(); }")
        btn1 = ev(f"() => !!document.querySelector('[data-act=wishAskAgain][data-id=\"{no}\"]')"); act('wishAskAgain', id=no); w(400)
        check('Wishlist: a week later it can be asked again, and it waits for a new answer', btn1 and vd(no)['v'] == 'Waiting for Rory' and ev(f"() => S.changelog.filter(x => x.step === 'ask' && x.wish === '{no}').length") == 2)
        av = view(); af = ev(PROBE); at(NOW)
        check('Wishlist: the Advisor draws clean and fits the phone', not any(s in av for s in BAD) and not af, af[:4])
    step('answers', f_answers)
    # ---- 13. notifications (step 2b): every History line says who is told; each of us chooses on our own phone ----
    def f_notify():
        load(NOW)
        last = lambda: ev("() => S.changelog.slice().sort((a, b) => (a.at || '').localeCompare(b.at || '')).pop() || {}")
        def buy(what, cat, frm, amt='9.80'):
            ev(f"() => {{ S.f.spend = {{date: '{NOW.date()}', what: {json.dumps(what)}, amount: '{amt}', cat: '{cat}', paidFrom: '{frm}', who: 'both', kind: 'need', told: 'before', note: ''}}; }}"); ev("async () => { await spendSave(); }"); w(300)
            return last(), ev(f"() => (S.spending.find(x => x.what === {json.dumps(what)}) || {{}}).id")
        L, sid = buy('Kit ntf shop', 'Groceries', 'joint')
        check('Tell: the shop from the Joint account waits for Rory’s evening summary, with its total', L.get('tell') == 'shop' and (L.get('cats') or {}).get('Groceries') == 9.8, L)
        L2, sid2 = buy('Kit ntf card shop', 'Drinks', 'card')
        check('Tell: the shop on the card is told right away (a card purchase)', L2.get('tell') == 'buys' and 'cats' not in L2, L2)
        L3, sid3 = buy('Kit ntf pocket', 'Home', 'bills', '4.00')
        check('Tell: a purchase from the Bills Pocket card is told as a pot used', L3.get('tell') == 'pots', L3)
        for i in (sid, sid2, sid3): act('spendDel', id=i); act('spendDel', id=i)
        check('Tell: deleting a purchase is told (nothing disappears silently)', last().get('tell') == 'edits' and last().get('text', '').startswith('Deleted'), last())
        ev(f"() => {{ S.f.mv = {{date: '{NOW.date()}', from: 'joint', to: 'ef', amount: '3', note: 'kit ntf move', kind: 'extra'}}; }}"); ev("async () => { await moveSave(); }"); w(300)
        Lm = last(); mid = ev("() => (S.moves.find(m => m.note === 'kit ntf move') || {}).id")
        check('Tell: an extra move between our accounts is a money move', Lm.get('tell') == 'moves' and 'kit ntf move' in Lm.get('text', ''), {'last': Lm, 'err': ev("() => S.err")})
        ev(f"() => {{ S.f.mv = {{date: '{NOW.date()}', from: 'bills', to: 'joint', amount: '2', note: 'kit ntf pot', kind: 'extra'}}; }}"); ev("async () => { await moveSave(); }"); w(300)
        Lp = last(); pid = ev("() => (S.moves.find(m => m.note === 'kit ntf pot') || {}).id")
        check('Tell: money taken from the Bills Pocket by hand is told as a pot used (rule 1)', Lp.get('tell') == 'pots' and 'rule 1' in Lp.get('text', ''), {'last': Lp, 'err': ev("() => S.err")})
        if pid: act('mvDel', id=pid); act('mvDel', id=pid)
        if mid: act('mvDel', id=mid); act('mvDel', id=mid)
        check('Tell: undoing it is told as undone', last().get('tell') == 'edits', last())
        ev("async () => { await logChangeAg('no', 'bill', 'Added Kit ntf bill'); }"); Lb = last()
        check('Tell: a bill decided without Rory is a decision, with the short line he reads', Lb.get('tell') == 'decided' and Lb.get('rory') == 'no' and Lb.get('short') == 'Added Kit ntf bill', Lb)
        act('wkSent'); w(300)
        check('Tell: the weekly report marked as sent tells Rory it’s ready', last().get('tell') == 'report', last())
        TELLS = {'buys', 'shop', 'moves', 'pots', 'asks', 'decided', 'edits', 'report', 'answers'}
        bad = ev("() => S.changelog.filter(x => 'tell' in x && !['buys', 'shop', 'moves', 'pots', 'asks', 'decided', 'edits', 'report', 'answers'].includes(x.tell)).map(x => x.text.slice(0, 60))")
        quiet = ev("() => S.changelog.filter(x => x.tell && /^(Electricity reading|Money check|Backup downloaded|AIB card interest)/.test(x.text)).map(x => x.text.slice(0, 60))")
        check('Tell: every tell is one the database knows; readings, money checks, backups and statement interest tell nobody', not bad and not quiet, bad + quiet)
        # Thiago's phone, in Settings → Setup
        ev("() => { S.tab = 'settings'; S.sub.settings = 'setup'; render(); }"); v0 = view()
        check('Notifications: Thiago’s card in Settings → Setup, off on this phone, only Rory’s answers to choose', 'Notifications' in v0 and 'Off on this phone.' in v0 and 'Turn on for this phone' in v0 and 'Rory’s answers' in v0 and 'The shop, cigarettes' not in v0, v0[v0.find('Notifications'):][:300] if 'Notifications' in v0 else '')
        act('ntfOn'); w(600); v1 = view()
        dev = ev("() => Object.values(window.__pushDevices)")
        check('Notifications: “Turn on” asks the phone, subscribes and saves this phone as Thiago’s', ev("() => window.__push.asked") == 1 and 'On for this phone.' in v1 and len(dev) == 1 and dev[0]['label'] == 'Thiago’s phone', dev)
        act('ntfTest'); w(400)
        check('Notifications: “Send me a test” goes to his own phone', ev("() => window.__pushTests.slice(-1)[0]") == {'role': 'editor', 'n': 1}, ev("() => window.__pushTests"))
        act('seg', form='ntf', key='answers', val='evening'); act('seg', form='ntf', key='quiet', val='yes')
        ev("() => { S.f.ntf.qFrom = '22:00'; S.f.ntf.qTo = '22:00'; }"); act('ntfSave'); w(300)
        check('Notifications: quiet hours that start and end at the same time are refused, nothing saved', 'same time' in (ev("() => S.err") or '') and not ev("() => Object.keys(window.__pushPrefs).length"))
        ev("() => { S.f.ntf.qFrom = '22:30'; S.f.ntf.qTo = '07:30'; }"); act('ntfSave'); w(500)
        tp = ev("() => Object.values(window.__pushPrefs)[0] || {}")
        check('Notifications: Thiago’s choices are saved as his (Rory’s answers in the evening, quiet 22:30–07:30)', tp.get('answers') == 'evening' and tp.get('quiet') == {'from': '22:30', 'to': '07:30'} and 'Evening summary at' in view() and not ev("() => S.err"), tp)
        sf = ev(PROBE)
        check('Notifications: Thiago’s card fits the phone', not sf, sf[:6])
        act('ntfOff'); w(400)
        check('Notifications: “Turn off” removes this phone', not ev("() => Object.keys(window.__pushDevices).length") and 'Off on this phone.' in view())
        ev("() => { window.__push.permission = 'denied'; }"); ev("async () => { S.ntf.state = await S.ntf.api.state(); render(); }"); w(200)
        check('Notifications: blocked in the iPhone’s Settings, the card says where to turn them on', 'Settings → Notifications → Week by Week' in view() and 'Turn on for this phone' not in view())
        ev("() => { window.__push.permission = 'default'; window.__push.sub = null; }")
        # Rory's phone, at the bottom of his report
        ev("() => { window.__as = 'viewer'; S.canWrite = false; S.f.ntf = ntfForm(S.ntf.prefs); S.ntf.state = 'off'; render(); }"); rv = view()
        kinds = ['Thiago is asking you', 'Decisions, and anything decided without you', 'Purchases and card charges', 'The shop, cigarettes and drinks', 'Bills Pocket, Vault or emergency fund used', 'Bills paid, transfers and money added', 'Anything changed, undone or deleted', 'The weekly report']
        rl = rv.lower()   # his report's design shows the labels in capitals
        check('Notifications: Rory’s card at the bottom of his report, with his eight kinds', 'notifications' in rl and all(k.lower() in rl for k in kinds) and 'rory’s answers' not in rl, {'missing': [k for k in kinds if k.lower() not in rl], 'tail': rv[-500:]})
        act('ntfOn'); w(600)
        dev = ev("() => Object.values(window.__pushDevices)")
        act('seg', form='ntf', key='moves', val='evening'); act('seg', form='ntf', key='quiet', val='no'); act('ntfSave'); w(500)
        P = ev("() => window.__pushPrefs")
        rp = P.get('00000000-0000-4000-8000-0000000000b2') or {}; tp2 = P.get('00000000-0000-4000-8000-0000000000a1') or {}
        rf = ev(PROBE); ev("() => { window.__as = null; S.canWrite = true; render(); }")
        check('Notifications: Rory turns them on for his own phone and saves his own choices (Thiago’s stay as they were)', len(dev) == 1 and dev[0]['user_id'].endswith('b2') and rp.get('moves') == 'evening' and rp.get('shop') == 'evening' and rp.get('quiet') is None and tp2.get('answers') == 'evening', {'dev': dev, 'prefs': P})
        check('Notifications: Rory’s view with the card fits the phone', not rf, rf[:6])
        ev("() => { const keep = S.ntf; S.ntf = null; S.tab = 'settings'; S.sub.settings = 'setup'; render(); window.__k = keep; }"); vc = view(); ev("() => { S.ntf = window.__k; render(); }")
        check('Notifications: inside Claude (no notifications there) the card doesn’t show', 'On this phone' not in vc)
    step('notifications', f_notify)
    step('ahead', f_ahead)
    br.close()

notes['jsErrors'] = errs[:10]
check('no JavaScript errors anywhere', not errs, errs[:3])
out = {'at': datetime.datetime.now().isoformat(timespec='seconds'), 'now': iso(NOW), 'version': notes.get('version'), 'passed': sum(r['ok'] for r in results), 'failed': sum(not r['ok'] for r in results), 'results': results, 'notes': notes}
json.dump(out, open(A.out, 'w'), indent=1, default=str)
print(f"\nRESULT: {out['passed']} passed, {out['failed']} failed -> {A.out}")
sys.exit(1 if out['failed'] else 0)
