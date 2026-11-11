// Tests step 2a's SQL (Rory's own answers) on a local Postgres (PGlite), on top of step 1.
// usage: node test/answers_test.mjs supabase/001_base.sql supabase/002_rory_answers.sql
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';

const db = new PGlite();
const T = '11111111-1111-1111-1111-111111111111', R = '22222222-2222-2222-2222-222222222222', X = '33333333-3333-3333-3333-333333333333';
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
await db.exec(`insert into auth.users values ('${T}', 't@x'), ('${R}', 'r@x'), ('${X}', 'x@x');
  insert into public.members values ('${T}', 'editor', 'Thiago'), ('${R}', 'viewer', 'Rory');`);

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra && !cond ? '  ' + extra : '')); };
const as = async (role, uid, q, params) => {
  await db.exec(`reset role; select set_config('request.jwt.claim.sub', '${uid || ''}', false); set role ${role};`);
  try { const r = await db.query(q, params); return {rows: r.rows, n: r.affectedRows}; }
  catch (e) { return {err: e.code || 'ERR', msg: e.message}; }
  finally { await db.exec('reset role'); }
};
const ASK = '2026-11-09T10:00:00.000Z';
const ans = (id, d) => [`insert into answers (id, data) values ($1, $2::jsonb) returning data`, [id, JSON.stringify(d)]];

// Thiago asks: a comparison with a question, and a want over €20 on the wishlist
await as('authenticated', T, `insert into docs (coll, id, data) values ('compare', 'c1', $1::jsonb), ('wishlist', 'w1', $2::jsonb)`,
  [JSON.stringify({name: 'Apple One', status: 'open', rory: {plan: 'p2', planName: 'Family', asked: ASK}}), JSON.stringify({what: 'Headphones', price: 89.99, kind: 'want', addedAt: ASK, asked: ASK, status: 'waiting'})]);

let r = await as('authenticated', T, ...ans('a0', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: 'Sure'}));
ok('Thiago cannot answer for Rory', r.err === '42501', r.err);
r = await as('authenticated', X, ...ans('a0', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: 'Sure'}));
ok('a stranger cannot answer', r.err === '42501', r.err);
r = await as('anon', null, ...ans('a0', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: 'Sure'}));
ok('not signed in: cannot answer', r.err === '42501', r.err);
r = await as('authenticated', R, ...ans('a1', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: ' x '}));
ok('Rory needs a few words', !!r.err, r.err);
r = await as('authenticated', R, ...ans('a1', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p9', answer: 'yes', said: 'Fine by me'}));
ok('an answer to a plan that wasn’t asked is refused', r.err === '22023', r.err);
r = await as('authenticated', R, ...ans('a1', {kind: 'compare', ref: 'c1', asked: '2026-11-01T10:00:00.000Z', plan: 'p2', answer: 'yes', said: 'Fine by me'}));
ok('an answer to an old question is refused', r.err === '22023', r.err);
r = await as('authenticated', R, ...ans('a1', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: 'Fine, Family only', at: '1999-01-01T00:00:00.000Z'}));
ok('Rory answers from his own account', !r.err && r.rows[0].data.answer === 'yes', r.msg);
ok('the time is the server’s, never typed', !r.err && r.rows[0].data.at > '2026', !r.err && r.rows[0].data.at);
r = await as('authenticated', R, `select answered_by from answers where id = 'a1'`);
ok('it is stamped as Rory’s', r.rows && r.rows[0].answered_by === R);
r = await as('authenticated', T, `select data from docs where coll = 'changelog' and id = 'ansa1'`);
ok('the database wrote the History line', r.rows && r.rows.length === 1 && r.rows[0].data.kind === 'decision' && r.rows[0].data.cmp === 'c1' && r.rows[0].data.step === 'answer' && r.rows[0].data.rory === 'yes' && /from his own account \(Compare, Apple One · Family\): yes, “Fine, Family only”/.test(r.rows[0].data.text), r.rows && JSON.stringify(r.rows[0]));
r = await as('authenticated', R, ...ans('a2', {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'no', said: 'Changed my mind'}));
ok('one answer per question (no quiet second answer)', r.err === '23505', r.err);
r = await as('authenticated', R, `update answers set data = data || '{"answer":"no"}' where id = 'a1'`);
ok('nobody can change an answer', !!r.err, r.err);
r = await as('authenticated', T, `update answers set data = data || '{"answer":"no"}' where id = 'a1'`);
ok('not even Thiago', !!r.err, r.err);
r = await as('authenticated', T, `delete from answers where id = 'a1'`);
ok('nobody can delete an answer', !!r.err, r.err);
r = await as('authenticated', T, `select count(*)::int c from answers`);
ok('Thiago reads Rory’s answers', r.rows && r.rows[0].c === 1);
r = await as('authenticated', X, `select count(*)::int c from answers`);
ok('a stranger reads nothing', r.rows && r.rows[0].c === 0);
r = await as('authenticated', R, `insert into docs (coll, id, data) values ('changelog', 'fake', '{"text":"x"}')`);
ok('Rory still can’t write anything else (History included)', r.err === '42501', r.err);

// the wishlist
r = await as('authenticated', R, ...ans('w1a', {kind: 'wish', ref: 'w1', asked: ASK, answer: 'no', said: 'Not this month'}));
ok('Rory answers a want on the wishlist', !r.err, r.msg);
r = await as('authenticated', T, `select data from docs where coll = 'changelog' and id = 'answ1a'`);
ok('… and its History line names the want', r.rows && r.rows[0] && r.rows[0].data.wish === 'w1' && /wishlist, Headphones €89\.99\): no, “Not this month”/.test(r.rows[0].data.text), r.rows && JSON.stringify(r.rows[0]));
await as('authenticated', T, `select doc_merge('wishlist', 'w1', '{"status":"dropped"}')`);
r = await as('authenticated', R, ...ans('w1b', {kind: 'wish', ref: 'w1', asked: '2026-11-16T10:00:00.000Z', answer: 'yes', said: 'OK now'}));
ok('a dropped want can’t be answered', r.err === '22023', r.err);

// the import brings answers back into their own table, as they were, with no new History line
r = await as('authenticated', T, `select doc_import($1::jsonb) n`, [JSON.stringify([
  {coll: 'compare', id: 'c1', data: {name: 'Apple One', status: 'open', rory: {plan: 'p2', planName: 'Family', asked: ASK}}},
  {coll: 'answers', id: 'a1', data: {kind: 'compare', ref: 'c1', asked: ASK, plan: 'p2', answer: 'yes', said: 'Fine, Family only', at: '2026-11-09T11:00:00.000Z'}}])]);
ok('the import brings Rory’s answers back', !r.err && r.rows[0].n === 2, r.msg);
r = await as('authenticated', T, `select (select count(*)::int from docs) d, (select count(*)::int from answers) a, (select data->>'at' from answers where id = 'a1') at, (select answered_by from answers where id = 'a1') who`);
ok('… into their own table, as they were, as Rory’s, with no new History line', r.rows[0].d === 1 && r.rows[0].a === 1 && r.rows[0].at === '2026-11-09T11:00:00.000Z' && r.rows[0].who === R, JSON.stringify(r.rows[0]));
r = await as('authenticated', R, `select doc_import('[{"coll":"bills","id":"z","data":{}}]')`);
ok('Rory still cannot import', r.err === '42501', r.err);
r = await db.query(`select count(*)::int c from pg_publication_tables where pubname='supabase_realtime' and tablename='answers'`);
ok('live updates switched on for answers', r.rows[0].c === 1);

console.log(`\n${pass} of ${pass + fail} passed`);
process.exit(fail ? 1 : 0);
