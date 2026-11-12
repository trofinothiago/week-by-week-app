// Week by Week app: the account page. Who is signed in, sign out, and (Thiago only) bring in a backup.
// A backup is the .json from Settings → Setup → Download a backup. Bringing one in replaces everything
// in the app in one go (all or nothing, in the database: doc_import).
(async () => {
  const el = document.getElementById('app-acct');
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const A = await window.wbw.use('account'), me = A.me();
  let file = null, armed = false, busy = false, msg = '', bad = false;

  // backup → documents: config/<name>, weeks/<id>, <collection>/<id> (the id isn't kept inside the data)
  const toDocs = b => {
    if (!b || b.app !== 'Week by Week' || b.kind !== 'backup') throw new Error('This isn’t a Week by Week backup.');
    const out = [], noId = d => { const x = {...d}; delete x.id; return x; };
    const add = (coll, id, data) => {
      if (!id || /\//.test(String(id))) throw new Error(`An item in ${coll} has no usable id.`);
      out.push({coll, id: String(id), data});
    };
    for (const [id, d] of Object.entries(b.config || {})) if (d && Object.keys(d).length) add('config', id, d);
    for (const [id, d] of Object.entries(b.weeks || {})) add('weeks', id, noId(d));
    for (const [coll, list] of Object.entries(b)) if (Array.isArray(list)) for (const d of list) add(coll, d && d.id, noId(d || {}));
    if (!out.length) throw new Error('The backup is empty.');
    return out;
  };
  const byColl = docs => docs.reduce((o, d) => (o[d.coll] = (o[d.coll] || 0) + 1, o), {});
  const when = s => { const d = new Date(s); return isNaN(d) ? '' : new Intl.DateTimeFormat('en-IE', {day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(d); };

  const importPanel = () => {
    const now = A.counts();
    const rows = file ? Object.entries(byColl(file.docs)).sort().map(([c, n]) => `<div class="app-kv"><span>${esc(c)}</span><span class="num">${n} in the file · ${now[c] || 0} now</span></div>`).join('') : '';
    const btn = !file ? '' : busy ? `<button class="btn strong" disabled>Bringing it in…</button>`
      : `<button class="btn ${armed ? 'danger' : 'strong'}" data-a="go">${armed ? `Tap again: replace everything with these ${file.docs.length} items` : 'Replace everything with this backup'}</button>${armed ? '<button class="btn" data-a="cancel">Cancel</button>' : ''}`;
    return `<section class="panel app-acct"><header><h2>Bring in a backup</h2></header>
      <p class="app-note">The .json from Settings → Setup → Download a backup. It replaces everything in this app with the backup.</p>
      <input type="file" accept=".json,application/json" data-a="file" aria-label="Choose the backup file">
      ${file ? `<div class="app-kv"><span>Backup saved</span><b>${esc(when(file.savedAt))}</b></div>${rows}` : ''}
      ${msg ? `<p class="app-msg${bad ? ' bad' : ''}" role="status">${esc(msg)}</p>` : ''}
      ${btn}</section>`;
  };

  const draw = () => {
    el.innerHTML = `<section class="panel app-acct"><header><h2>Signed in</h2></header>
      <div class="app-kv"><span>Who</span><b>${esc(me.name)}</b></div>
      <div class="app-kv"><span>Email</span><span>${esc(me.email)}</span></div>
      <div class="app-kv"><span>In the app</span><span>${me.role === 'editor' ? 'Can change everything' : 'Can read, never change'}</span></div>
      <a class="btn strong" href="./">Open Week by Week</a>
      <button class="btn" data-a="out">Sign out</button></section>
      ${me.role === 'editor' ? importPanel() : '<section class="panel"><p class="app-note">Only Thiago can bring in a backup.</p></section>'}`;
  };

  el.addEventListener('change', async e => {
    if (e.target.dataset.a !== 'file' || !e.target.files[0]) return;
    armed = false; msg = ''; bad = false;
    try { const b = JSON.parse(await e.target.files[0].text()); file = {docs: toDocs(b), savedAt: b.savedAt}; }
    catch (err) { file = null; msg = err instanceof SyntaxError ? 'That file can’t be read as a backup.' : err.message; bad = true; }
    draw();
  });
  el.addEventListener('click', async e => {
    const a = e.target.closest('[data-a]'); if (!a) return;
    if (a.dataset.a === 'out') return A.signOut();
    if (a.dataset.a === 'cancel'){ armed = false; draw(); return; }
    if (a.dataset.a !== 'go' || !file || busy) return;
    if (!armed){ armed = true; draw(); return; }
    busy = true; msg = ''; draw();
    try { const n = await A.replaceAll(file.docs); msg = `Done: ${n} items brought in from the backup of ${when(file.savedAt)}.`; bad = false; file = null; }
    catch (err) { msg = err.code === 'invalid_argument' ? 'Only Thiago can bring in a backup.' : 'Couldn’t bring it in. Nothing was changed. Check the connection and try again.'; bad = true; }
    busy = false; armed = false; draw();
  });
  draw();
})();
