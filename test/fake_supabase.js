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
  const who = h => { const a = h.get('authorization') || ''; const t = a.replace(/^Bearer /, ''); if (t === KEY || !t.includes('.')) return null; try { return USERS.find(u => u.id === unb64(t.split('.')[1]).sub) || null; } catch (e) { return null; } };
  const eqs = q => Object.fromEntries([...q.entries()].filter(([, v]) => v.startsWith('eq.')).map(([k, v]) => [k, decodeURIComponent(v.slice(3))]));
  const pick = (row, sel) => sel && sel !== '*' ? Object.fromEntries(sel.split(',').map(k => [k, row[k]])) : row;
  const row = (c, id) => ({coll: c, id, data: store[c][id].data, updated_at: store[c][id].at});
  const now = () => new Date().toISOString();

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
        const all = Object.keys(store).sort().flatMap(c => Object.keys(store[c]).sort().map(id => row(c, id)));
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
      for (const d of list) (store[d.coll] ||= {})[d.id] = {data: d.data, at: now()};
      window.__writes.push(['import', list.length]);
      return res(200, list.length);
    }
    return res(404, {message: 'not in the fake: ' + m + ' ' + u.pathname});
  }

  window.__USERS = USERS;
  window.WBW_CONFIG = {url: URL0, key: KEY, live: false, client: {global: {fetch: fakeFetch}}};
})();
