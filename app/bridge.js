// Week by Week app: the page's connection to its data, on Supabase.
// The page asks for window.claude.use('db' | 'user' | 'downloads'), exactly as it does inside Claude
// (and as the test kit's mock.js does). Here they come from Supabase: sign-in, the docs table, live updates.
// The page itself doesn't change. The locks live in the database (supabase/001_base.sql).
(() => {
  const CFG = window.WBW_CONFIG || {};
  const hash = new URLSearchParams(location.hash.slice(1));
  const LINK = hash.get('type');                       // 'invite' or 'recovery': choose a password first
  const LINK_ERR = hash.get('error_description');      // an expired or used link
  const store = {};                                    // coll -> {id: {data, at}}
  const subs = [];                                     // {coll, id (null: the whole collection), cb}
  let sb = null, me = null, ready = null, hiddenAt = 0;

  const copy = x => JSON.parse(JSON.stringify(x));     // what the page sends is stored as JSON, like the mock
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const client = () => sb ||= window.supabase.createClient(CFG.url, CFG.key, {
    auth: {persistSession: true, autoRefreshToken: true, detectSessionInUrl: true}, ...(CFG.client || {})});
  const fail = e => {                                  // errors in the shape the page knows (writeErr)
    const x = new Error((e && e.message) || 'Couldn’t reach the data');
    x.code = e && e.code === '42501' ? 'invalid_argument' : e && e.code === 'P0002' ? 'not_found' : 'unavailable';
    return x;
  };
  const newId = () => { const a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', r = crypto.getRandomValues(new Uint8Array(20)); return Array.from(r, n => a[n % 62]).join(''); };

  /* ---------- the local copy and who is watching it ---------- */
  const stamp = at => at ? Date.parse(at) || 0 : 0;
  const put = (c, id, data, at) => {
    const s = store[c] ||= {}, old = s[id];
    if (old && stamp(at) && stamp(at) < old.at) return false;   // an older echo never wins over a newer write
    s[id] = {data, at: stamp(at) || (old ? old.at : 0)};
    return true;
  };
  const drop = (c, id) => { if (store[c]) delete store[c][id]; };
  const snap = (c, id) => {
    if (id == null) return {docs: Object.entries(store[c] || {}).map(([k, v]) => ({id: k, data: () => copy(v.data)}))};
    const v = (store[c] || {})[id];
    return {exists: !!v, data: () => copy(v ? v.data : {})};
  };
  const fire = (c, id) => setTimeout(() => {
    for (const s of subs) if (c == null || (s.coll === c && (s.id == null || s.id === id))) s.cb(snap(s.coll, s.id));
  }, 0);
  const watch = (coll, id, cb) => { const s = {coll, id, cb}; subs.push(s); setTimeout(() => cb(snap(coll, id)), 0); return () => { const i = subs.indexOf(s); if (i >= 0) subs.splice(i, 1); }; };

  async function loadAll(){
    const all = async (table, cols, order) => {
      const rows = [];
      for (let a = 0; ; a += 1000){
        let q = client().from(table).select(cols);
        for (const o of order) q = q.order(o);
        const {data, error} = await q.range(a, a + 999);
        if (error) throw fail(error);
        rows.push(...data);
        if (data.length < 1000) break;
      }
      return rows;
    };
    const docs = await all('docs', 'coll,id,data,updated_at', ['coll', 'id']), answers = await all('answers', 'id,data,at', ['id']);
    for (const k of Object.keys(store)) delete store[k];
    for (const r of docs) put(r.coll, r.id, r.data, r.updated_at);
    store.answers = {};
    for (const r of answers) put('answers', r.id, r.data, r.at);
  }

  /* ---------- the database, as the page knows it ---------- */
  const readOnly = async () => { throw fail({code: '42501', message: 'read only'}); };
  const db = {
    collection: coll => ({
      onSnapshot: cb => watch(coll, null, cb),
      add: async doc => {
        const id = newId(), data = copy(doc);
        if (coll === 'answers'){   // Rory's answers: their own table, which only his account can add to (the server stamps the time)
          const {data: r, error} = await client().from('answers').insert({id, data}).select('data,at');
          if (error) throw fail(error);
          put(coll, id, r[0].data, r[0].at); fire(coll, id);
          const {data: h} = await client().from('docs').select('coll,id,data,updated_at').eq('coll', 'changelog').eq('id', 'ans' + id);   // the History line the database wrote for it
          if (h && h[0]){ put('changelog', h[0].id, h[0].data, h[0].updated_at); fire('changelog', h[0].id); }
          return {id};
        }
        const {data: r, error} = await client().from('docs').insert({coll, id, data}).select('updated_at');
        if (error) throw fail(error);
        put(coll, id, data, r && r[0] && r[0].updated_at); fire(coll, id);
        return {id};
      }
    }),
    doc: path => {
      const [coll, id] = path.split('/');
      if (coll === 'answers') return {onSnapshot: cb => watch(coll, id, cb), set: readOnly, update: readOnly, delete: readOnly};   // an answer is never changed or deleted
      return {
        onSnapshot: cb => watch(coll, id, cb),
        set: async d => {
          const data = copy(d);
          const {data: r, error} = await client().from('docs').upsert({coll, id, data}).select('updated_at');
          if (error) throw fail(error);
          put(coll, id, data, r && r[0] && r[0].updated_at); fire(coll, id);
        },
        update: async d => {
          const {data: r, error} = await client().rpc('doc_merge', {p_coll: coll, p_id: id, p_patch: copy(d)});
          if (error) throw fail(error);
          put(coll, id, r.data, r.at); fire(coll, id);
        },
        delete: async () => {
          const {data: r, error} = await client().from('docs').delete().eq('coll', coll).eq('id', id).select('id');
          if (error) throw fail(error);
          if (!(r && r.length) && (store[coll] || {})[id]) throw fail({code: '42501', message: 'read only'});
          drop(coll, id); fire(coll, id);
        }
      };
    }
  };

  /* ---------- live: the other phone's changes appear on their own ---------- */
  function live(){
    if (CFG.live === false) return;
    client().channel('docs').on('postgres_changes', {event: '*', schema: 'public', table: 'docs'}, p => {
      if (p.eventType === 'DELETE'){ const o = p.old || {}; if (o.coll && o.id){ drop(o.coll, o.id); fire(o.coll, o.id); } return; }
      const n = p.new || {};
      if (n.coll && n.id && put(n.coll, n.id, n.data, n.updated_at)) fire(n.coll, n.id);
    }).on('postgres_changes', {event: 'INSERT', schema: 'public', table: 'answers'}, p => {
      const n = p.new || {};
      if (n.id && put('answers', n.id, n.data, n.at)) fire('answers', n.id);
    }).subscribe();
    const refresh = async () => { try { await loadAll(); fire(null); } catch (e) {} };   // after the phone slept, read everything again
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) hiddenAt = Date.now();
      else if (hiddenAt && Date.now() - hiddenAt > 30000) refresh();
    });
    window.addEventListener('online', refresh);
  }

  /* ---------- signing in (the page's own iPhone look) ---------- */
  const gate = (sub, body) => {
    let g = document.getElementById('app-gate');
    if (!g){ g = document.createElement('div'); g.id = 'app-gate'; g.className = 'app-gate'; document.body.appendChild(g); }
    g.innerHTML = `<div class="wrap"><div class="ios-title"><div class="app-brand">${MARK}<div><h1>Week by Week</h1><p>${esc(sub)}</p></div></div></div><div class="stack">${body}</div></div>`;
    return g;
  };
  const MARK = '<picture class="app-mark"><source srcset="icon-dark-180.png" media="(prefers-color-scheme: dark)"><img src="icon-180.png" alt="" width="56" height="56"></picture>';
  const ungate = () => { const g = document.getElementById('app-gate'); if (g) g.remove(); };
  const say = (g, t, bad) => { const m = g.querySelector('.app-msg'); m.textContent = t; m.classList.toggle('bad', !!bad); };
  const field = (id, label, type, ac) => `<div class="fld"><label for="${id}">${label}</label><input id="${id}" type="${type}" autocomplete="${ac}" required></div>`;

  const askSignIn = note => new Promise(done => {
    const g = gate('Sign in', `<section class="panel"><form class="app-form" novalidate>
      ${note ? `<p class="app-note">${esc(note)}</p>` : ''}
      ${field('gEmail', 'Email', 'email', 'username')}${field('gPass', 'Password', 'password', 'current-password')}
      <p class="app-msg" role="status"></p>
      <button class="btn strong" type="submit">Sign in</button>
      <button class="btn" type="button" data-g="forgot">Forgot the password?</button></form></section>`);
    const em = g.querySelector('#gEmail'), pw = g.querySelector('#gPass');
    g.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      if (!em.value || !pw.value){ say(g, 'Type the email and the password.', true); return; }
      say(g, 'Signing in…');
      const {data, error} = await client().auth.signInWithPassword({email: em.value.trim(), password: pw.value});
      if (error){ say(g, error.status === 400 ? 'That email and password don’t match.' : 'Couldn’t sign in. Check the connection and try again.', true); return; }
      done(data.session);
    });
    g.querySelector('[data-g=forgot]').addEventListener('click', async () => {
      if (!em.value){ say(g, 'Type your email first, then tap “Forgot the password?” again.', true); return; }
      const {error} = await client().auth.resetPasswordForEmail(em.value.trim(), {redirectTo: location.origin + location.pathname});
      say(g, error ? 'Couldn’t send the email. Try again in a few minutes.' : 'If that email is one of ours, a link to choose a new password is on its way.', !!error);
    });
  });

  const choosePassword = () => new Promise(done => {
    const g = gate(LINK === 'invite' ? 'Welcome' : 'New password', `<section class="panel"><form class="app-form" novalidate>
      <p class="app-note">Choose your password. On the iPhone, let it save to the Keychain: next time Face ID fills it in.</p>
      ${field('gNew', 'New password (10 characters or more)', 'password', 'new-password')}${field('gNew2', 'Type it again', 'password', 'new-password')}
      <p class="app-msg" role="status"></p>
      <button class="btn strong" type="submit">Save the password</button></form></section>`);
    g.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const a = g.querySelector('#gNew').value, b = g.querySelector('#gNew2').value;
      if (a.length < 10){ say(g, 'Use 10 characters or more.', true); return; }
      if (a !== b){ say(g, 'The two don’t match.', true); return; }
      say(g, 'Saving…');
      const {error} = await client().auth.updateUser({password: a});
      if (error){ say(g, 'Couldn’t save it: ' + error.message, true); return; }
      done();
    });
  });

  async function member(user){
    const {data, error} = await client().from('members').select('role,name').eq('user_id', user.id);
    if (error) throw fail(error);
    return data && data[0] ? {id: user.id, email: user.email, role: data[0].role, name: data[0].name} : null;
  }

  async function signOut(){ await client().auth.signOut(); location.replace(location.pathname); }

  async function start(){
    const c = client();
    let {data: {session}} = await c.auth.getSession();
    if (session && (LINK === 'invite' || LINK === 'recovery')) await choosePassword();
    if (LINK || LINK_ERR) history.replaceState(null, '', location.pathname + location.search);
    let note = LINK_ERR ? 'That link has expired or was already used. Sign in, or tap “Forgot the password?” for a new one.' : '';
    for (;;){
      if (!session){ session = await askSignIn(note); note = ''; }
      try {
        me = await member(session.user);
        if (!me){
          await c.auth.signOut(); session = null;
          note = 'This account isn’t one of the two in Week by Week.';
          continue;
        }
        gate('Opening', '<section class="panel"><p class="app-note">Getting our numbers…</p></section>');
        await loadAll();
        break;
      } catch (e) {
        await new Promise(r => {
          const g = gate('Can’t reach the data', `<section class="panel"><p class="app-note">Check the connection and try again.</p><button class="btn strong" type="button">Try again</button></section>`);
          g.querySelector('button').addEventListener('click', r);
        });
      }
    }
    ungate();
    live();
    return me;
  }

  /* ---------- files (backup, Rory's PDF) ---------- */
  const downloads = {save: async ({filename, data}) => {
    const file = new File([data], filename, {type: data.type || 'application/octet-stream'});
    if (/iPhone|iPad|Android/.test(navigator.userAgent) && navigator.canShare && navigator.canShare({files: [file]})){
      try { await navigator.share({files: [file], title: filename}); return; }
      catch (e) { if (e.name === 'AbortError'){ const x = new Error('declined'); x.code = 'declined'; throw x; } }   // else: fall back to a plain download
    }
    const a = document.createElement('a'); a.href = URL.createObjectURL(file); a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
  }};

  /* ---------- the account page (import.html) ---------- */
  const account = {
    me: () => me, signOut,
    counts: () => Object.fromEntries(Object.entries(store).map(([c, s]) => [c, Object.keys(s).length])),
    replaceAll: async docs => {
      const {data, error} = await client().rpc('doc_import', {p_docs: docs});
      if (error) throw fail(error);
      await loadAll(); fire(null);
      return data;
    }
  };

  window.claude = {use: async name => {
    if (name === 'downloads') return downloads;
    if (name !== 'db' && name !== 'user' && name !== 'account') return null;
    await (ready ||= start());
    return name === 'db' ? db : name === 'account' ? account : {can: async cap => cap === 'data.write' ? me.role === 'editor' : cap === 'answer.own' ? me.role === 'viewer' : false};
  }};
})();
