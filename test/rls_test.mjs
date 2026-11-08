// Tests the step-1 SQL on a local Postgres (PGlite) with a stand-in for Supabase's auth schema.
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';

const sql = fs.readFileSync(process.argv[2], 'utf8');
const db = new PGlite();
const T = '11111111-1111-1111-1111-111111111111', R = '22222222-2222-2222-2222-222222222222', X = '33333333-3333-3333-3333-333333333333';
await db.exec(`
  create role anon nologin; create role authenticated nologin;
  create schema auth; grant usage on schema auth to anon, authenticated;
  create table auth.users (id uuid primary key, email text);
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant execute on function auth.uid() to anon, authenticated;
  grant usage on schema public to anon, authenticated;
  create publication supabase_realtime;
`);
await db.exec(sql);
await db.exec(`insert into auth.users values ('${T}', 't@x'), ('${R}', 'r@x'), ('${X}', 'x@x');
  insert into public.members values ('${T}', 'editor', 'Thiago'), ('${R}', 'viewer', 'Rory');`);

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra ? '  ' + extra : '')); };
const as = async (role, uid, q, params) => {
  await db.exec(`reset role; select set_config('request.jwt.claim.sub', '${uid || ''}', false); set role ${role};`);
  try { const r = await db.query(q, params); return {rows: r.rows, n: r.affectedRows}; }
  catch (e) { return {err: e.code || 'ERR', msg: e.message}; }
  finally { await db.exec('reset role'); }
};

// Thiago writes
let r = await as('authenticated', T, `insert into docs (coll, id, data) values ('bills', 'b1', '{"name":"Rent","amount":10}')`);
ok('Thiago adds a bill', !r.err, r.msg);
r = await as('authenticated', T, `select updated_by from docs where coll='bills' and id='b1'`);
ok('the write is stamped with Thiago', r.rows && r.rows[0].updated_by === T);
r = await as('authenticated', T, `select doc_merge('bills', 'b1', '{"amount":12,"note":"x"}') r`);
ok('Thiago merges a change', !r.err && r.rows[0].r.data.amount === 12 && !!r.rows[0].r.at, r.msg);
r = await as('authenticated', T, `select data from docs where id='b1'`);
ok('merge is shallow like the page', r.rows[0].data.name === 'Rent' && r.rows[0].data.amount === 12 && r.rows[0].data.note === 'x');
r = await as('authenticated', T, `select doc_merge('bills', 'nope', '{"a":1}')`);
ok('merge on a missing doc is refused', r.err === 'P0002', r.err);
r = await as('authenticated', T, `insert into docs (coll, id, data) values ('config', 'settings', '{"a":1}') on conflict (coll, id) do update set data = excluded.data`);
ok('Thiago sets (upsert) a config doc', !r.err, r.msg);
r = await as('authenticated', T, `insert into docs (coll, id, data) values ('bills', 'a/b', '{}')`);
ok('an id with a slash is refused', !!r.err);

// Rory reads, never writes
r = await as('authenticated', R, `select count(*)::int c from docs`);
ok('Rory reads everything', r.rows && r.rows[0].c === 2);
r = await as('authenticated', R, `insert into docs (coll, id, data) values ('bills', 'b2', '{}')`);
ok('Rory cannot add', r.err === '42501', r.err);
r = await as('authenticated', R, `update docs set data='{}' where id='b1'`);
ok('Rory cannot change (0 rows)', !r.err && r.n === 0);
r = await as('authenticated', R, `select doc_merge('bills', 'b1', '{"amount":0}')`);
ok('Rory cannot merge', r.err === '42501', r.err);
r = await as('authenticated', R, `delete from docs where id='b1'`);
ok('Rory cannot delete (0 rows)', !r.err && r.n === 0);
r = await as('authenticated', R, `select doc_import('[{"coll":"bills","id":"z","data":{}}]')`);
ok('Rory cannot import', r.err === '42501', r.err);
r = await as('authenticated', R, `insert into members values ('${X}', 'editor', 'Rory2')`);
ok('Rory cannot add a member', !!r.err, r.err);
r = await as('authenticated', R, `update members set role='editor' where user_id='${R}'`);
ok('Rory cannot make himself editor', !!r.err, r.err);
r = await as('authenticated', T, `select data from docs where id='b1'`);
ok('the bill is unchanged after Rory tried', r.rows[0].data.amount === 12);
r = await as('authenticated', R, `select count(*)::int c from members`);
ok('Rory sees the two of us', r.rows && r.rows[0].c === 2);

// Strangers see nothing
r = await as('authenticated', X, `select count(*)::int c from docs`);
ok('a signed-in stranger sees nothing', r.rows && r.rows[0].c === 0);
r = await as('authenticated', X, `insert into docs (coll, id, data) values ('bills', 'b3', '{}')`);
ok('a signed-in stranger cannot write', r.err === '42501', r.err);
r = await as('anon', null, `select count(*)::int c from docs`);
ok('not signed in: no access at all', r.err === '42501', r.err);
r = await as('anon', null, `select doc_merge('bills', 'b1', '{}')`);
ok('not signed in: no merge', r.err === '42501', r.err);
r = await as('anon', null, `select * from members`);
ok('not signed in: no members', r.err === '42501', r.err);

// Import replaces everything, all or nothing
r = await as('authenticated', T, `select doc_import($1::jsonb) n`, [JSON.stringify([{coll: 'bills', id: 'n1', data: {a: 1}}, {coll: 'config', id: 'plan', data: {b: 2}}])]);
ok('Thiago imports', !r.err && r.rows[0].n === 2, r.msg);
r = await as('authenticated', T, `select count(*)::int c from docs`);
ok('import replaced everything', r.rows[0].c === 2);
r = await as('authenticated', T, `select doc_import($1::jsonb) n`, [JSON.stringify([{coll: 'bills', id: 'ok', data: {}}, {coll: 'bills', id: 'bad/id', data: {}}])]);
ok('a bad import is refused', !!r.err);
r = await as('authenticated', T, `select count(*)::int c from docs`);
ok('a refused import changes nothing', r.rows[0].c === 2);
r = await db.query(`select count(*)::int c from pg_publication_tables where pubname='supabase_realtime' and tablename='docs'`);
ok('live updates switched on for docs', r.rows[0].c === 1);

console.log(`\n${pass} of ${pass + fail} passed`);
process.exit(fail ? 1 : 0);
