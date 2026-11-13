// Tests step 5's SQL (a closed year report can never be changed) on a local Postgres (PGlite), on top of steps 1–3.
// usage: node test/years_test.mjs supabase/001_base.sql supabase/002_rory_answers.sql supabase/003_notifications.sql supabase/005_closed_years.sql
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';

const db = new PGlite();
const T = '11111111-1111-1111-1111-111111111111', R = '22222222-2222-2222-2222-222222222222';
await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin;
  create schema auth; grant usage on schema auth to anon, authenticated;
  create table auth.users (id uuid primary key, email text);
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant execute on function auth.uid() to anon, authenticated;
  grant usage on schema public to anon, authenticated;
  create publication supabase_realtime;
`);
for (const f of process.argv.slice(2)) await db.exec(fs.readFileSync(f, 'utf8'));
await db.exec(`insert into auth.users values ('${T}', 't@x'), ('${R}', 'r@x');
  insert into public.members values ('${T}', 'editor', 'Thiago'), ('${R}', 'viewer', 'Rory');`);

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra && !cond ? '  ' + extra : '')); };
const as = async (role, uid, q, params) => {
  await db.exec(`reset role; select set_config('request.jwt.claim.sub', '${uid || ''}', false); ${role ? `set role ${role};` : ''}`);
  try { const r = await db.query(q, params); return {rows: r.rows, n: r.affectedRows}; }
  catch (e) { return {err: e.code || 'ERR', msg: e.message}; }
  finally { await db.exec('reset role'); }
};
const cur = (await db.query(`select extract(year from now() at time zone 'Europe/Dublin')::int y`)).rows[0].y, last = cur - 1;
const yr = (y, net) => JSON.stringify({y, data: {y, net}, closedOn: `${y + 1}-01-15`});
const ins = (id, d) => [`insert into docs (coll, id, data) values ('years', $1, $2::jsonb)`, [id, d]];
const read = async id => (await db.query(`select data from docs where coll = 'years' and id = $1`, [id])).rows[0]?.data;

let r = await as('authenticated', R, ...ins(String(last), yr(last, 10)));
ok('Rory cannot close a year', r.err === '42501', r.err);
r = await as('authenticated', T, ...ins(String(cur), yr(cur, 10)));
ok('a year that isn’t over can’t be closed', r.err === '23514', r.err);
r = await as('authenticated', T, ...ins(String(last), yr(last - 1, 10)));
ok('a report whose year doesn’t match its id is refused', r.err === '23514', r.err);
r = await as('authenticated', T, ...ins('y' + last, yr(last, 10)));
ok('an id that isn’t a year is refused', r.err === '23514', r.err);
r = await as('authenticated', T, ...ins(String(last), yr(last, 10)));
ok('Thiago closes last year (written once)', !r.err, r.msg);
r = await as('authenticated', T, ...ins(String(last), yr(last, 99)));
ok('closing the same year again is refused', !!r.err && (await read(String(last))).data.net === 10, r.err);
r = await as('authenticated', T, `insert into docs (coll, id, data) values ('years', $1, $2::jsonb) on conflict (coll, id) do update set data = excluded.data`, [String(last), yr(last, 99)]);
ok('writing over it (upsert) is refused', r.err === '42501', r.err);
r = await as('authenticated', T, `update docs set data = jsonb_set(data, '{data,net}', '99') where coll = 'years'`);
ok('Thiago cannot change it', r.err === '42501', r.err);
r = await as('authenticated', T, `select doc_merge('years', $1, '{"closedOn":"x"}')`, [String(last)]);
ok('Thiago cannot merge into it', r.err === '42501', r.err);
r = await as('authenticated', T, `delete from docs where coll = 'years'`);
ok('Thiago cannot delete it', r.err === '42501', r.err);
r = await as(null, '', `update docs set data = '{}' where coll = 'years'`);
ok('not even the database owner (outside the app) can change it', r.err === '42501', r.err);
r = await as(null, '', `delete from docs where coll = 'years'`);
ok('not even the database owner can delete it', r.err === '42501', r.err);
await as('authenticated', T, `insert into docs (coll, id, data) values ('bills', 'b1', '{"name":"Rent"}')`);
r = await as('authenticated', T, `update docs set coll = 'years', id = $1 where coll = 'bills'`, [String(last - 3)]);
ok('another document can’t be turned into a year report', r.err === '42501', r.err);
// a backup import keeps every closed year as it is, and only adds the ones missing
r = await as('authenticated', T, `select doc_import($1::jsonb) n`, [JSON.stringify([{coll: 'bills', id: 'b2', data: {name: 'Gas'}}])]);
ok('an import without the year keeps it', !r.err && (await read(String(last)))?.data.net === 10, r.msg);
r = await as('authenticated', T, `select doc_import($1::jsonb) n`, [JSON.stringify([{coll: 'bills', id: 'b3', data: {}}, {coll: 'years', id: String(last), data: JSON.parse(yr(last, 55))}, {coll: 'years', id: String(last - 1), data: JSON.parse(yr(last - 1, 7))}])]);
ok('an import with another copy of the year keeps the closed one, and adds a year that was missing', !r.err && (await read(String(last))).data.net === 10 && (await read(String(last - 1)))?.data.net === 7, r.msg);
r = await as('authenticated', T, `select coll, id from docs where coll = 'bills'`);
ok('the rest of the import still replaces everything', r.rows.length === 1 && r.rows[0].id === 'b3', JSON.stringify(r.rows));
r = await as('authenticated', R, `select count(*)::int c from docs where coll = 'years'`);
ok('Rory reads the closed years', r.rows[0].c === 2);
console.log(`\n${pass} of ${pass + fail} passed`); process.exit(fail ? 1 : 0);
