// Tests step 2b's SQL (notifications, the database side) on a local Postgres (PGlite), on top of steps 1 and 2a.
// usage: node test/push_test.mjs supabase/001_base.sql supabase/002_rory_answers.sql supabase/003_notifications.sql
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';

const db = new PGlite();
const T = '11111111-1111-1111-1111-111111111111', R = '22222222-2222-2222-2222-222222222222', X = '33333333-3333-3333-3333-333333333333';
await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin;
  create schema auth; grant usage on schema auth to anon, authenticated, service_role;
  create table auth.users (id uuid primary key, email text);
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant execute on function auth.uid() to anon, authenticated, service_role;
  grant usage on schema public to anon, authenticated, service_role;
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
const sys = async (q, params) => { await db.exec(`reset role; select set_config('request.jwt.claim.sub', '', false);`); const r = await db.query(q, params); return r.rows; };
const box = (w = 'true') => sys(`select * from private.push_outbox where ${w} order by id`);
const line = (id, d) => as('authenticated', T, `insert into docs (coll, id, data) values ('changelog', $1, $2::jsonb)`, [id, JSON.stringify({at: '2026-11-12T10:00:00.000Z', date: '2026-11-12', ...d})]);
const take = at => as('service_role', null, `select push_take($1::timestamptz) as r`, [at]).then(r => r.err ? r : r.rows[0].r);
const at = (id, t) => sys(`update private.push_outbox set made_at = $2::timestamptz where ref = $1`, [id, t]);
const clear = () => sys(`update private.push_outbox set sent_at = now(), status = 'sent' where sent_at is null`);

// What gets queued, and for whom
await line('l1', {kind: 'spending', text: 'Purchase: Headphones €89.99 · Thiago · want · from Joint account', tell: 'buys'});
let q = await box();
ok('a History line with a tell is queued for Rory', q.length === 1 && q[0].user_id === R && q[0].tell === 'buys' && q[0].title === 'Purchase' && /Headphones/.test(q[0].body), JSON.stringify(q));
await line('l2', {kind: 'settings', text: 'Backup downloaded'});
ok('a line without a tell tells nobody', (await box()).length === 1);
await line('l3', {kind: 'bill', text: 'Added Netflix €12.99 · Rory not asked yet', short: 'Added Netflix €12.99', rory: 'no', tell: 'decided'});
q = await box(`ref = 'l3'`);
ok('decided without Rory: its own title, and the short line he reads', q.length === 1 && q[0].title === 'Decided without you' && q[0].body === 'Added Netflix €12.99', JSON.stringify(q));
await line('l4', {kind: 'spending', text: 'Purchase (one receipt at Aldi, €64.15): Groceries €52.15, Drinks €12.00', tell: 'shop', cats: {Groceries: 52.15, Drinks: 12}});
q = await box(`ref = 'l4'`);
ok('a shop line keeps its totals for the evening summary', q.length === 1 && q[0].cats && q[0].cats.Groceries === 52.15);
await line('l5', {kind: 'spending', text: 'x', tell: 'surprise'});
ok('an unknown tell is ignored', (await box(`ref = 'l5'`)).length === 0);
let r = await as('authenticated', R, `insert into answers (id, data) values ('a1', $1::jsonb)`,
  [JSON.stringify({kind: 'wish', ref: 'w1', asked: '2026-11-09T10:00:00.000Z', answer: 'yes', said: 'Go for it'})]);
ok('(setup) a question to answer is needed first', r.err === '22023');
await as('authenticated', T, `insert into docs (coll, id, data) values ('wishlist', 'w1', $1::jsonb)`, [JSON.stringify({what: 'Headphones', price: 89.99, addedAt: '2026-11-09T10:00:00.000Z', asked: '2026-11-09T10:00:00.000Z', status: 'waiting'})]);
r = await as('authenticated', R, `insert into answers (id, data) values ('a1', $1::jsonb)`,
  [JSON.stringify({kind: 'wish', ref: 'w1', asked: '2026-11-09T10:00:00.000Z', answer: 'yes', said: 'Go for it'})]);
q = await box(`ref = 'ansa1'`);
ok('Rory’s answer tells Thiago (and only Thiago)', !r.err && q.length === 1 && q[0].user_id === T && q[0].title === 'Rory answered' && /Rory said yes to Headphones: “Go for it”/.test(q[0].body), r.msg || JSON.stringify(q));

// Nothing disappears silently
r = await as('authenticated', T, `delete from docs where coll = 'changelog' and id = 'l2'`);
q = await box(`ref = 'l2'`);
ok('a History line deleted in the app is told, with who did it', !r.err && q.length === 1 && q[0].user_id === R && q[0].tell === 'edits' && /^Thiago deleted a History line: “Backup downloaded”/.test(q[0].body), JSON.stringify(q));
await sys(`update docs set data = data || '{"text":"Purchase: Headphones €79.99"}' where coll = 'changelog' and id = 'l1'`);
q = await box(`ref = 'l1' and tell = 'edits'`);
ok('a History line changed outside the app is told', q.length === 1 && /^Someone outside the app changed a History line: “Purchase: Headphones €89.99 · Thiago · want · from Joint account” is now “Purchase: Headphones €79.99”/.test(q[0].body), JSON.stringify(q));
await sys(`update docs set data = data || '{"seen":true}' where coll = 'changelog' and id = 'l1'`);
ok('a change that leaves the words as they were is not news', (await box(`ref = 'l1' and tell = 'edits'`)).length === 1);

// A backup coming back in is quiet
const n0 = (await box()).length;
r = await as('authenticated', T, `select doc_import($1::jsonb) as n`, [JSON.stringify([
  {coll: 'changelog', id: 'l1', data: {kind: 'spending', text: 'Purchase: Headphones €89.99', tell: 'buys'}},
  {coll: 'changelog', id: 'l9', data: {kind: 'transfer', text: 'Done: Joint → Bills Pocket', tell: 'moves'}},
  {coll: 'wishlist', id: 'w1', data: {what: 'Headphones', price: 89.99, addedAt: '2026-11-09T10:00:00.000Z', asked: '2026-11-09T10:00:00.000Z', status: 'waiting'}},
  {coll: 'answers', id: 'a1', data: {kind: 'wish', ref: 'w1', asked: '2026-11-09T10:00:00.000Z', answer: 'yes', said: 'Go for it', at: '2026-11-10T10:00:00.000Z'}}])]);
ok('importing a backup tells nobody anything', !r.err && (await box()).length === n0, r.msg || (await box()).length + ' vs ' + n0);
await line('l10', {kind: 'transfer', text: 'Done: Joint → Vault', tell: 'moves'});
ok('…and right after it, lines are told again', (await box(`ref = 'l10'`)).length === 1);

// Devices and choices: each of us, our own only
const DEV = {endpoint: 'https://web.push.apple.com/abc', p256dh: 'B'.repeat(87), auth: 'a'.repeat(22)};
r = await as('authenticated', R, `insert into push_devices (endpoint, p256dh, auth, label) values ($1, $2, $3, 'Rory’s iPhone')`, [DEV.endpoint, DEV.p256dh, DEV.auth]);
ok('Rory turns notifications on for his iPhone', !r.err, r.msg);
r = await as('authenticated', R, `select user_id from push_devices`);
ok('it is stamped as his', r.rows && r.rows.length === 1 && r.rows[0].user_id === R);
r = await as('authenticated', T, `select * from push_devices`);
ok('Thiago can’t see Rory’s devices', r.rows && r.rows.length === 0);
r = await as('authenticated', T, `insert into push_devices (endpoint, user_id, p256dh, auth) values ('https://x.y/1', $1, $2, $3)`, [R, DEV.p256dh, DEV.auth]);
ok('Thiago can’t add a device for Rory', r.err === '42501', r.err);
r = await as('authenticated', T, `delete from push_devices`);
ok('Thiago can’t remove Rory’s device', !r.err && r.n === 0);
r = await as('authenticated', X, `insert into push_devices (endpoint, p256dh, auth) values ('https://x.y/2', $1, $2)`, [DEV.p256dh, DEV.auth]);
ok('a stranger can’t add a device', r.err === '42501', r.err);
r = await as('anon', null, `select * from push_devices`);
ok('not signed in: nothing', !!r.err);
r = await as('authenticated', R, `insert into push_devices (endpoint, p256dh, auth) values ('http://plain/1', $1, $2)`, [DEV.p256dh, DEV.auth]);
ok('only a real push address is accepted', !!r.err);

r = await as('authenticated', R, `select push_my_prefs() as p`);
ok('defaults: right away, the shop in the evening at 21:00, quiet 23:00–08:00', r.rows && r.rows[0].p.buys === 'now' && r.rows[0].p.shop === 'evening' && r.rows[0].p.digestAt === '21:00' && r.rows[0].p.quiet.from === '23:00');
r = await as('authenticated', R, `insert into push_prefs (data) values ('{"moves":"loud"}')`);
ok('a choice that doesn’t exist is refused', !!r.err);
r = await as('authenticated', R, `insert into push_prefs (data) values ('{"digestAt":"25:00"}')`);
ok('a time that doesn’t exist is refused', !!r.err);
r = await as('authenticated', R, `insert into push_prefs (data) values ('{"edits":"evening","digestAt":"20:30"}')`);
ok('Rory saves his choices', !r.err, r.msg);
r = await as('authenticated', R, `select push_my_prefs() as p`);
ok('his choices win, the rest stays default', r.rows[0].p.edits === 'evening' && r.rows[0].p.digestAt === '20:30' && r.rows[0].p.buys === 'now');
r = await as('authenticated', T, `select * from push_prefs`);
ok('Thiago can’t see Rory’s choices', r.rows && r.rows.length === 0);
r = await as('authenticated', T, `update push_prefs set data = '{"buys":"off"}'`);
ok('Thiago can’t change Rory’s choices', !r.err && r.n === 0);
r = await as('authenticated', X, `select push_my_prefs() as p`);
ok('a stranger gets no choices', r.rows && r.rows[0].p === null);
await as('authenticated', R, `update push_prefs set data = '{}'`);

// The sender
r = await as('authenticated', T, `select push_take()`);
ok('the app can’t take the queue', r.err === '42501', r.err);
r = await as('authenticated', R, `select push_done('{1}')`);
ok('the app can’t mark things sent', r.err === '42501', r.err);
await clear();

await line('s1', {kind: 'spending', text: 'Purchase: Headphones €89.99', tell: 'buys'}); await at('s1', '2026-11-12T13:58:00Z');
await line('s2', {kind: 'spending', text: 'Deleted the purchase Lunch €8.50', tell: 'edits'}); await at('s2', '2026-11-12T13:59:00Z');
await line('s3', {kind: 'spending', text: 'Purchase: Aldi €52.15', tell: 'shop', cats: {Groceries: 52.15}}); await at('s3', '2026-11-12T12:00:00Z');
await line('s4', {kind: 'spending', text: 'Purchase: Londis €21.50', tell: 'shop', cats: {Cigarettes: 9.5, Drinks: 12}}); await at('s4', '2026-11-12T13:00:00Z');
await line('s5', {kind: 'answers', text: 'Rory said no', tell: 'answers'});   // for Thiago, who has no device
let out = await take('2026-11-12T14:00:00Z');
let ro = Array.isArray(out) && out.find(x => x.user === R);
ok('at 14:00 Rory gets one message with both things due', ro && ro.messages.length === 1 && ro.messages[0].title === '2 updates' && ro.messages[0].body === '• Purchase: Headphones €89.99\n• Deleted the purchase Lunch €8.50', JSON.stringify(out));
ok('with his device', ro && ro.devices.length === 1 && ro.devices[0].endpoint === DEV.endpoint && ro.devices[0].auth === DEV.auth);
ok('the shop waits for the evening', ro && ro.ids.length === 2);
q = await box(`ref = 's5'`);
ok('nobody to send to (no device): dropped, not kept forever', q[0].status === 'nodevice' && !(out || []).find(x => x.user === T));
out = await take('2026-11-12T14:01:00Z');
ok('what was taken isn’t taken twice', Array.isArray(out) && out.length === 0, JSON.stringify(out));
out = await take('2026-11-12T14:06:00Z');
ro = Array.isArray(out) && out.find(x => x.user === R);
ok('not confirmed in 5 minutes: taken again', ro && ro.ids.length === 2);
r = await as('service_role', null, `select push_done($1::bigint[], $2::text[], '{}', '2026-11-12T14:06:30Z')`, [ro.ids, [DEV.endpoint]]);
q = await box(`ref in ('s1', 's2')`);
ok('the sender marks them sent', !r.err && q.every(x => x.status === 'sent'), r.msg);
out = await take('2026-11-12T14:20:00Z');
ok('sent is sent', Array.isArray(out) && out.length === 0);

out = await take('2026-11-12T21:05:00Z');
ro = Array.isArray(out) && out.find(x => x.user === R);
ok('at 21:05 the evening summary, with totals by category', ro && ro.messages.length === 1 && ro.messages[0].title === 'The shop, cigarettes and drinks'
  && ro.messages[0].body === 'Groceries €52.15 · Drinks €12.00 · Cigarettes €9.50\n2 purchases logged' && ro.messages[0].tag === 'digest-2026-11-12', JSON.stringify(out));
await as('service_role', null, `select push_done($1::bigint[])`, [ro.ids]);
await line('s6', {kind: 'spending', text: 'Purchase: Centra €4.20', tell: 'shop', cats: {Groceries: 4.2}}); await at('s6', '2026-11-12T21:30:00Z');
out = await take('2026-11-12T21:40:00Z');
ok('a shop bought after the summary waits for tomorrow’s', Array.isArray(out) && out.length === 0, JSON.stringify(out));

await line('q1', {kind: 'transfer', text: 'Done: Joint → Bills Pocket €390', tell: 'moves'}); await at('q1', '2026-11-12T23:30:00Z');
out = await take('2026-11-12T23:31:00Z');
ok('quiet hours: nothing at 23:31', Array.isArray(out) && out.length === 0, JSON.stringify(out));
r = await as('authenticated', R, `select push_test() as n`);
out = await take('2026-11-12T23:32:00Z');
ro = Array.isArray(out) && out.find(x => x.user === R);
ok('“Send me a test” goes even in quiet hours, on its own', r.rows && r.rows[0].n === 1 && ro && ro.messages.length === 1 && ro.messages[0].body === 'Test: notifications work on this phone.', JSON.stringify(out));
await as('service_role', null, `select push_done($1::bigint[])`, [ro.ids]);
out = await take('2026-11-13T07:59:00Z');
ok('still quiet at 07:59', Array.isArray(out) && out.length === 0);
out = await take('2026-11-13T08:00:00Z');
ro = Array.isArray(out) && out.find(x => x.user === R);
ok('at 08:00 what waited arrives', ro && ro.messages.length === 1 && ro.messages[0].body === 'Done: Joint → Bills Pocket €390', JSON.stringify(out));
await as('service_role', null, `select push_done($1::bigint[])`, [ro.ids]);

await as('authenticated', R, `update push_prefs set data = '{"moves":"off","quiet":null}'`);
await line('o1', {kind: 'transfer', text: 'Done: Joint → Vault', tell: 'moves'}); await at('o1', '2026-11-13T10:00:00Z');
await line('o2', {kind: 'decision', text: 'Thiago asks: Apple One Family?', tell: 'asks'}); await at('o2', '2026-11-13T10:00:00Z');
out = await take('2026-11-13T10:01:00Z');
ro = Array.isArray(out) && out.find(x => x.user === R);
q = await box(`ref = 'o1'`);
ok('a kind Rory turned off is dropped; the rest comes', q[0].status === 'off' && ro && ro.messages.length === 1 && ro.messages[0].title === 'Thiago is asking you', JSON.stringify(out));
await as('service_role', null, `select push_done($1::bigint[])`, [ro.ids]);
await line('o3', {kind: 'transfer', text: 'Done: Joint → Vault', tell: 'asks'}); await at('o3', '2026-11-13T23:59:00Z');
out = await take('2026-11-13T23:59:30Z');
ok('no quiet hours: told even at midnight', Array.isArray(out) && out.length === 1);
await as('service_role', null, `select push_done($1::bigint[], '{}', $2::text[])`, [out[0].ids, [DEV.endpoint]]);
r = await as('authenticated', R, `select count(*)::int as n from push_devices`);
ok('a device the push service says is gone is removed', r.rows[0].n === 0);
r = await as('authenticated', R, `select push_test() as n`);
ok('a test with no device on says 0 (turn it on here first)', r.rows && r.rows[0].n === 0);
await as('authenticated', R, `insert into push_devices (endpoint, p256dh, auth) values ($1, $2, $3)`, [DEV.endpoint, DEV.p256dh, DEV.auth]);
for (let i = 0; i < 2; i++) await as('authenticated', R, `select push_test()`);
r = await as('authenticated', R, `select push_test()`);
ok('three tests in 10 minutes at most', r.err === '54000', r.err);
r = await as('authenticated', X, `select push_test()`);
ok('a stranger can’t send a test', r.err === '42501', r.err);
await sys(`update private.push_outbox set sent_at = null, status = null, taken_at = '2026-11-14T10:00:00Z', tries = 3 where ref = 'o2'`);
await take('2026-11-14T10:06:00Z');
q = await box(`ref = 'o2'`);
ok('after 3 tries it stops trying', q[0].status === 'failed');

console.log(`${pass} of ${pass + fail} passed`);
process.exit(fail ? 1 : 0);
