// Week by Week app test kit: a stand-in for the Supabase servers, inside the browser tab.
// The REAL supabase-js client and the app's bridge run unchanged; only fetch() is answered here, by a small
// imitation of Supabase Auth and PostgREST holding a COPY of the data (window.__SEED__). It applies the same
// locks as supabase/001_base.sql (editor writes, viewer reads, strangers nothing). Nothing can reach a real server.
// window.__ROLE__: 'editor' (default) or 'viewer' is signed in at the start; 'none' starts signed out.
(() => {
  const USERS = [
    {id: '00000000-0000-4000-8000-0000000000a1', email: 'thiago@example.test', password: 'test-password-1', role: 'editor', name: 'Thiago'},
    {id: '00000000-0000-4000-8000-0000000000b2', email: 'rory@example.test', password: 'test-password-2', role: 'viewer', name: 'Rory'},
    {id: '00000000-0000-4000-8000-0000000000c3', email: 'stranger@example.test', password: 'test-password-3', role: null, name: 'Stranger'}
  ];
  const URL0 = 'https://test.supabase.co', KEY = 'sb_publishable_test', SKEY = 'sb-test-auth-token';
  const store = {};
  for (const [c, docs] of Object.entries(window.__SEED__ || {})) { store[c] = {}; for (const [id, d] of Object.entries(docs)) store[c][id] = {data: JSON.parse(JSON.stringify(d)), at: new Date(0).toISOString()}; }
  window.__store = new Proxy({}, {get: (_, c) => Object.fromEntries(Object.entries(store[c] || {}).map(([k, v]) => [k, v.data])), ownKeys: () => Object.keys(store), getOwnPropertyDescriptor: () => ({enumerable: true, configurable: true})});
  window.__writes = []; window.__saved = []; window.__calls = [];
  window.__pushDevices = {}; window.__pushPrefs = {}; window.__pushTests = [];
  const PUSH_DEFAULTS = {buys: 'now', shop: 'evening', moves: 'now', pots: 'now', asks: 'now', decided: 'now', edits: 'now', report: 'now', answers: 'now', digestAt: '21:00', quiet: {from: '23:00', to: '08:00'}};   // as private.push_prefs_of

  const b64 = o => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
  const unb64 = s => JSON.parse(atob(s.replace(/-/g, '+').replace(/_/g, '/')));
  const session = u => {
    const exp = Math.floor(Date.now() / 1000) + 3e8;
    const user = {id: u.id, aud: 'authenticated', role: 'authenticated', email: u.email, app_metadata: {}, user_metadata: {}, created_at: new Date(0).toISOString()};
    return {access_token: `${b64({alg: 'HS256', typ: 'JWT'})}.${b64({sub: u.id, email: u.email, role: 'authenticated', aud: 'authenticated', exp})}.sig`,
      token_type: 'bearer', expires_in: 3e8, expires_at: exp, refresh_token: 'refresh-' + u.id, user};
  };
  const start = USERS.find(u => u.role === (window.__ROLE__ || 'editor'));
  try { if (start) localStorage.setItem(SKEY, JSON.stringify(session(start))); else localStorage.removeItem(SKEY); } catch (e) {}

  const res = (status, body) => new Response(status === 204 ? null : JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});
  const denied = () => res(403, {code: '42501', message: 'new row violates row-level security policy for table "docs"', details: null, hint: null});
  window.__as = null;   // the kit can act as Rory ('viewer') to answer from his account
  const who = h => { if (window.__as) return USERS.find(u => u.role === window.__as) || null; const a = h.get('authorization') || ''; const t = a.replace(/^Bearer /, ''); if (t === KEY || !t.includes('.')) return null; try { return USERS.find(u => u.id === unb64(t.split('.')[1]).sub) || null; } catch (e) { return null; } };
  const eqs = q => Object.fromEntries([...q.entries()].filter(([, v]) => v.startsWith('eq.')).map(([k, v]) => [k, decodeURIComponent(v.slice(3))]));
  const pick = (row, sel) => sel && sel !== '*' ? Object.fromEntries(sel.split(',').map(k => [k, row[k]])) : row;
  const row = (c, id) => ({coll: c, id, data: store[c][id].data, updated_at: store[c][id].at});
  // the server's clock: it only moves forward, whatever the kit does to the page's clock (it jumps days ahead and back)
  let last = 0;
  const now = () => { last = Math.max(last + 1, Date.now()); return new Date(last).toISOString(); };

  async function fakeFetch(input, init = {}){
    const u = new URL(typeof input === 'string' ? input : input.url), q = u.searchParams, m = (init.method || 'GET').toUpperCase();
    const h = new Headers(init.headers || {}), body = init.body ? JSON.parse(init.body) : null, me = who(h), role = me && me.role;
    window.__calls.push(m + ' ' + u.pathname);
    // ---- Auth ----
    if (u.pathname === '/auth/v1/token' && q.get('grant_type') === 'password'){
      const x = USERS.find(z => z.email === body.email && z.password === body.password);
      return x ? res(200, session(x)) : res(400, {code: 400, error_code: 'invalid_credentials', msg: 'Invalid login credentials'});
    }
    if (u.pathname === '/auth/v1/user') return me ? res(200, session(me).user) : res(401, {code: 401, msg: 'Invalid JWT'});
    if (u.pathname === '/auth/v1/logout') return res(204);
    if (u.pathname === '/auth/v1/recover') return res(200, {});
    // ---- PostgREST ----
    if (u.pathname === '/rest/v1/members' && m === 'GET'){
      if (!role) return res(200, []);
      const f = eqs(q);
      return res(200, USERS.filter(x => x.role && (!f.user_id || x.id === f.user_id)).map(x => pick({user_id: x.id, role: x.role, name: x.name}, q.get('select'))));
    }
    if (u.pathname === '/rest/v1/docs'){
      if (!me) return denied();
      if (m === 'GET'){
        if (!role) return res(200, []);
        const f = eqs(q);
        const all = Object.keys(store).filter(c => c !== 'answers' && (!f.coll || c === f.coll)).sort().flatMap(c => Object.keys(store[c]).filter(id => !f.id || id === f.id).sort().map(id => row(c, id)));
        const off = +q.get('offset') || 0, lim = q.has('limit') ? +q.get('limit') : 1000;
        return res(200, all.slice(off, off + lim).map(r => pick(r, q.get('select'))));
      }
      if (m === 'POST'){
        if (role !== 'editor') return denied();
        const list = Array.isArray(body) ? body : [body], up = /merge-duplicates/.test(h.get('prefer') || ''), out = [];
        for (const d of list){
          if (!/^[a-z][a-z0-9_]{0,39}$/.test(d.coll) || !d.id || d.id.includes('/')) return res(400, {code: '23514', message: 'check constraint'});
          if (!up && store[d.coll] && store[d.coll][d.id]) return res(409, {code: '23505', message: 'duplicate key'});
          (store[d.coll] ||= {})[d.id] = {data: JSON.parse(JSON.stringify(d.data)), at: now()};
          window.__writes.push(up ? ['set', d.coll + '/' + d.id] : ['add', d.coll, d.id]);
          out.push(pick(row(d.coll, d.id), q.get('select')));
        }
        return res(201, out);
      }
      if (m === 'DELETE'){
        const f = eqs(q);
        if (role !== 'editor' || !store[f.coll] || !store[f.coll][f.id]) return res(200, []);
        delete store[f.coll][f.id]; window.__writes.push(['delete', f.coll + '/' + f.id]);
        return res(200, [{id: f.id}]);
      }
    }
    if (u.pathname === '/rest/v1/answers'){   // Rory's answers: the same rules as supabase/002_rory_answers.sql
      const A = store.answers ||= {};
      if (m === 'GET'){
        if (!role) return res(200, []);
        const all = Object.keys(A).sort().map(id => ({id, data: A[id].data, at: A[id].at}));
        const off = +q.get('offset') || 0, lim = q.has('limit') ? +q.get('limit') : 1000;
        return res(200, all.slice(off, off + lim).map(r => pick(r, q.get('select'))));
      }
      if (m !== 'POST') return res(405, {message: 'answers are never changed or deleted'});
      if (role !== 'viewer') return denied();
      const d = body.data || {}, said = String(d.said || '').trim(), ts = now();
      if (!['compare', 'wish'].includes(d.kind) || !['yes', 'no'].includes(d.answer) || !d.ref || said.length < 2) return res(400, {code: '23514', message: 'check constraint'});
      const c = (store[d.kind === 'compare' ? 'compare' : 'wishlist'] || {})[d.ref], qd = c && c.data;
      const open = d.kind === 'compare' ? qd && qd.rory && qd.status !== 'applied' && qd.rory.asked === d.asked && qd.rory.plan === d.plan
        : qd && !['bought', 'dropped'].includes(qd.status || 'waiting') && (qd.asked || qd.addedAt) === d.asked;
      if (!open) return res(400, {code: '22023', message: 'That question isn\'t open'});
      if (Object.values(A).some(a => a.data.kind === d.kind && a.data.ref === d.ref && a.data.asked === d.asked)) return res(409, {code: '23505', message: 'Already answered'});
      const data = {...d, at: ts, said};
      A[body.id] = {data, at: ts}; window.__writes.push(['answer', body.id]);
      const eur = n => '€' + Number(n || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
      const title = d.kind === 'compare' ? `Compare, ${qd.name || ''} · ${qd.rory.planName || ''}` : `wishlist, ${qd.what || ''} ${eur(qd.price)}`;
      const short = d.kind === 'compare' ? `Rory said ${d.answer} to ${qd.name || ''} · ${qd.rory.planName || ''}: “${said}”` : `Rory said ${d.answer} to ${qd.what || ''}: “${said}”`;
      const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Dublin'}).format(new Date(ts));
      (store.changelog ||= {})['ans' + body.id] = {data: {at: ts, date: day, kind: 'decision', text: `Rory’s answer, from his own account (${title}): ${d.answer}, “${said}”.`, [d.kind === 'compare' ? 'cmp' : 'wish']: d.ref, step: 'answer', rory: d.answer, short, tell: 'answers'}, at: ts};
      return res(201, [pick({id: body.id, data, at: ts}, q.get('select'))]);
    }
    if (u.pathname === '/rest/v1/rpc/doc_merge'){
      if (role !== 'editor') return res(403, {code: '42501', message: 'read only'});
      const d = (store[body.p_coll] || {})[body.p_id];
      if (!d) return res(400, {code: 'P0002', message: `no doc ${body.p_coll}/${body.p_id}`});
      Object.assign(d.data, body.p_patch); d.at = now(); window.__writes.push(['update', body.p_coll + '/' + body.p_id]);
      return res(200, {data: d.data, at: d.at});
    }
    if (u.pathname === '/rest/v1/rpc/doc_import'){
      if (role !== 'editor') return res(403, {code: '42501', message: 'read only'});
      const list = body.p_docs;
      if (!Array.isArray(list) || !list.length) return res(400, {code: '22023', message: 'empty import'});
      if (list.some(d => !/^[a-z][a-z0-9_]{0,39}$/.test(d.coll) || !d.id || String(d.id).includes('/'))) return res(400, {code: '23514', message: 'check constraint'});
      for (const k of Object.keys(store)) delete store[k];
      for (const d of list) (store[d.coll] ||= {})[d.id] = {data: d.data, at: d.coll === 'answers' && d.data.at ? d.data.at : now()};
      window.__writes.push(['import', list.length]);
      return res(200, list.length);
    }
    // ---- notifications: the same rules as supabase/003_notifications.sql (each of us, our own phones and choices only) ----
    if (u.pathname === '/rest/v1/push_devices'){
      const D = window.__pushDevices, f = eqs(q), one = Array.isArray(body) ? body[0] : body;
      if (!role) return m === 'GET' ? res(200, []) : denied();
      if (m === 'GET') return res(200, Object.values(D).filter(d => d.user_id === me.id && (!f.endpoint || d.endpoint === f.endpoint)).map(d => pick(d, q.get('select'))));
      if (m === 'POST'){
        if (!/^https:\/\//.test(one.endpoint || '')) return res(400, {code: '23514', message: 'check constraint'});
        if ((one.user_id && one.user_id !== me.id) || (D[one.endpoint] && D[one.endpoint].user_id !== me.id)) return denied();
        D[one.endpoint] = {...one, user_id: me.id}; window.__writes.push(['device', role]); return res(201, []);
      }
      if (m === 'DELETE'){ if (D[f.endpoint] && D[f.endpoint].user_id === me.id) delete D[f.endpoint]; return res(200, []); }
    }
    if (u.pathname === '/rest/v1/push_prefs'){
      const one = Array.isArray(body) ? body[0] : body;
      if (!role || (m === 'POST' && one.user_id && one.user_id !== me.id)) return denied();
      if (m === 'GET') return res(200, window.__pushPrefs[me.id] ? [{user_id: me.id, data: window.__pushPrefs[me.id]}] : []);
      if (m === 'POST'){ window.__pushPrefs[me.id] = one.data; window.__writes.push(['prefs', role]); return res(201, []); }
    }
    if (u.pathname === '/rest/v1/rpc/push_my_prefs') return res(200, role ? {...PUSH_DEFAULTS, ...(window.__pushPrefs[me.id] || {})} : null);
    if (u.pathname === '/rest/v1/rpc/push_public_key') return res(200, role ? 'B' + 'A'.repeat(86) : null);
    if (u.pathname === '/rest/v1/rpc/push_test'){
      if (!role) return res(403, {code: '42501', message: 'not one of us'});
      const n = Object.values(window.__pushDevices).filter(d => d.user_id === me.id).length; window.__pushTests.push({role, n}); return res(200, n);
    }
    return res(404, {message: 'not in the fake: ' + m + ' ' + u.pathname});
  }

  window.__USERS = USERS;
  window.WBW_CONFIG = {url: URL0, key: KEY, live: false, client: {global: {fetch: fakeFetch}}};
})();
