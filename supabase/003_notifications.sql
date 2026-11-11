-- Week by Week app, step 2b (part 1): notifications on our iPhones, the database side.
-- What's said comes from the History lines the page already writes for everything it does, in its own words.
-- A line tells the database which kind it is (tell); the database queues it for whoever should know
-- (Rory for everything Thiago does; Thiago for Rory's answers). Each of us chooses, per kind:
-- right away, in the evening summary, or off, and our quiet hours. Nothing is sent from here:
-- the sender (an Edge Function, part 2) takes what is due with push_take() and reports back with push_done().
-- A History line changed or deleted outside the page is told too: nothing disappears silently.

-- Each iPhone (or computer) that turned notifications on. Each of us sees and manages only our own.
create table public.push_devices (
  endpoint text primary key check (endpoint ~ '^https://' and length(endpoint) <= 1000),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  p256dh text not null check (length(p256dh) between 40 and 200),
  auth text not null check (length(auth) between 10 and 100),
  label text check (length(label) <= 60),
  added_at timestamptz not null default now(),
  last_ok timestamptz
);

-- What each of us wants. Missing keys take the defaults (private.push_prefs_of).
create function private.push_prefs_ok(p jsonb) returns boolean
language sql immutable set search_path = '' as $$
  select jsonb_typeof(p) = 'object' and length(p::text) <= 2000
    and not exists (select 1 from jsonb_each(p) e where e.key in ('buys', 'shop', 'moves', 'pots', 'asks', 'decided', 'edits', 'report', 'answers')
                    and e.value #>> '{}' not in ('now', 'evening', 'off'))
    and coalesce(p->>'digestAt', '21:00') ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
    and (p->'quiet' is null or jsonb_typeof(p->'quiet') = 'null' or (
         coalesce(p->'quiet'->>'from', '') ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' and coalesce(p->'quiet'->>'to', '') ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'))
$$;
create table public.push_prefs (
  user_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb check (private.push_prefs_ok(data)),
  updated_at timestamptz not null default now()
);

create function private.push_prefs_of(p_user uuid) returns jsonb
language sql stable security definer set search_path = '' as $$
  select '{"buys":"now","shop":"evening","moves":"now","pots":"now","asks":"now","decided":"now","edits":"now","report":"now","answers":"now",
           "digestAt":"21:00","quiet":{"from":"23:00","to":"08:00"}}'::jsonb
         || coalesce((select p.data from public.push_prefs p where p.user_id = p_user), '{}'::jsonb)
$$;
revoke all on function private.push_prefs_of(uuid) from public;

-- For the app: my own choices, with the defaults filled in (so the defaults live in one place).
-- The part that needs more rights lives in the private schema (not reachable from the app's API), as in step 2a.
create function private.push_prefs_mine() returns jsonb
language sql stable security definer set search_path = '' as $$
  select case when (select private.my_role()) is null then null else private.push_prefs_of((select auth.uid())) end
$$;
revoke all on function private.push_prefs_mine() from public;
grant execute on function private.push_prefs_mine() to authenticated;
create function public.push_my_prefs() returns jsonb
language sql stable security invoker set search_path = '' as $$ select private.push_prefs_mine() $$;
revoke all on function public.push_my_prefs() from public, anon;
grant execute on function public.push_my_prefs() to authenticated;

-- The queue (private: not reachable from the app).
create table private.push_outbox (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  tell text not null,
  title text not null,
  body text not null,
  cats jsonb,                       -- for the evening summary: {"Groceries": 64.15, …}
  ref text,                         -- the History line it came from
  made_at timestamptz not null default now(),
  taken_at timestamptz,
  tries integer not null default 0,
  sent_at timestamptz,
  status text check (status in ('sent', 'off', 'nodevice', 'failed'))
);
create index push_outbox_waiting on private.push_outbox (user_id) where sent_at is null;

create function private.push_title(p_tell text, p_rory text) returns text
language sql immutable set search_path = '' as $$
  select case p_tell
    when 'buys' then 'Purchase' when 'shop' then 'The shop' when 'moves' then 'Money moved'
    when 'pots' then 'A pot was used' when 'asks' then 'Thiago is asking you'
    when 'decided' then case when p_rory = 'no' then 'Decided without you' else 'Decided' end
    when 'edits' then 'Changed or undone' when 'report' then 'Your weekly report'
    when 'answers' then 'Rory answered' else 'Week by Week' end
$$;

-- Watches the History: a new line with a tell is queued; a line changed or deleted is always told.
create function private.push_watch() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  d jsonb; tell text; body text; who text; ref text;
begin
  if current_setting('wbw.importing', true) = 'on' then   -- a backup coming back in is not news
    return null;
  end if;
  if tg_op = 'INSERT' then
    d := new.data; tell := d->>'tell'; ref := new.id;
    if tell is null or tell not in ('buys', 'shop', 'moves', 'pots', 'asks', 'decided', 'edits', 'report', 'answers') then
      return null;
    end if;
    body := coalesce(nullif(btrim(d->>'short'), ''), btrim(d->>'text'), '');
  else
    d := old.data; tell := 'edits'; ref := old.id;
    who := coalesce((select m.name from public.members m where m.user_id = (select auth.uid())), 'Someone outside the app');
    body := who || case when tg_op = 'DELETE' then ' deleted a History line: “' || coalesce(old.data->>'text', '') || '”'
                        else ' changed a History line: “' || coalesce(old.data->>'text', '') || '” is now “' || coalesce(new.data->>'text', '') || '”' end;
  end if;
  if body = '' then
    return null;
  end if;
  insert into private.push_outbox (user_id, tell, title, body, cats, ref)
    select m.user_id, tell, private.push_title(tell, d->>'rory'), left(body, 500),
           case when jsonb_typeof(d->'cats') = 'object' then d->'cats' end, ref
    from public.members m where m.role = case when tell = 'answers' then 'editor' else 'viewer' end;
  return null;
end $$;
revoke all on function private.push_watch() from public;
create trigger docs_push_new after insert on public.docs
  for each row when (new.coll = 'changelog') execute function private.push_watch();
create trigger docs_push_changed after update on public.docs
  for each row when (new.coll = 'changelog' and old.data->>'text' is distinct from new.data->>'text') execute function private.push_watch();
create trigger docs_push_gone after delete on public.docs
  for each row when (old.coll = 'changelog') execute function private.push_watch();

-- Quiet hours (Irish time; they can run past midnight).
create function private.push_quiet(p jsonb, p_now timestamptz) returns boolean
language sql stable set search_path = '' as $$
  select case when jsonb_typeof(p->'quiet') is distinct from 'object' or p->'quiet'->>'from' = p->'quiet'->>'to' then false
              when (p->'quiet'->>'from')::time < (p->'quiet'->>'to')::time
                then (p_now at time zone 'Europe/Dublin')::time >= (p->'quiet'->>'from')::time and (p_now at time zone 'Europe/Dublin')::time < (p->'quiet'->>'to')::time
              else (p_now at time zone 'Europe/Dublin')::time >= (p->'quiet'->>'from')::time or (p_now at time zone 'Europe/Dublin')::time < (p->'quiet'->>'to')::time end
$$;

-- The last evening summary time that has passed (Irish time).
create function private.push_last_digest(p jsonb, p_now timestamptz) returns timestamptz
language sql stable set search_path = '' as $$
  select case when x > (p_now at time zone 'Europe/Dublin') then x - interval '1 day' else x end at time zone 'Europe/Dublin'
  from (select (p_now at time zone 'Europe/Dublin')::date + coalesce(p->>'digestAt', '21:00')::time as x) s
$$;

create function private.money(x numeric) returns text
language sql immutable set search_path = '' as $$ select '€' || to_char(x, 'FM999,999,990.00') $$;

-- For the sender: what is due now, per person: their devices and one or two messages
-- (everything due right away together; the evening summary on its own). Each item is taken once;
-- one not confirmed sent in 5 minutes is taken again, up to 3 times.
create function public.push_take(p_now timestamptz default now()) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  u record; p jsonb; out jsonb := '[]'::jsonb; msgs jsonb; devs jsonb;
  ids_now bigint[]; ids_eve bigint[]; dg timestamptz; quiet boolean; t text; b text; cs text;
begin
  delete from private.push_outbox where sent_at < p_now - interval '30 days';
  update private.push_outbox set sent_at = p_now, status = 'failed'
    where sent_at is null and tries >= 3 and taken_at < p_now - interval '5 minutes';
  for u in select distinct o.user_id from private.push_outbox o where o.sent_at is null loop
    p := private.push_prefs_of(u.user_id); quiet := private.push_quiet(p, p_now); dg := private.push_last_digest(p, p_now);
    -- what this person turned off is dropped
    update private.push_outbox o set sent_at = p_now, status = 'off'
      where o.user_id = u.user_id and o.sent_at is null and o.tell <> 'test' and coalesce(p->>o.tell, 'now') = 'off';
    -- nothing to send to: no device turned on
    select coalesce(jsonb_agg(jsonb_build_object('endpoint', d.endpoint, 'p256dh', d.p256dh, 'auth', d.auth)), '[]'::jsonb) into devs
      from public.push_devices d where d.user_id = u.user_id;
    if jsonb_array_length(devs) = 0 then
      update private.push_outbox o set sent_at = p_now, status = 'nodevice' where o.user_id = u.user_id and o.sent_at is null;
      continue;
    end if;
    msgs := '[]'::jsonb;
    -- right away: a test always; the rest outside quiet hours, all due together in one message
    select array_agg(o.id order by o.made_at),
           case when count(*) = 1 then max(o.title)
                when count(distinct o.tell) = 1 then max(o.title) || ' · ' || count(*)
                else count(*) || ' updates' end,
           left(case when count(*) = 1 then max(o.body) else string_agg('• ' || o.body, E'\n' order by o.made_at) end, 1500)
      into ids_now, t, b
      from private.push_outbox o
      where o.user_id = u.user_id and o.sent_at is null and (o.taken_at is null or o.taken_at < p_now - interval '5 minutes')
        and (o.tell = 'test' or (coalesce(p->>o.tell, 'now') = 'now' and not quiet));
    if ids_now is not null then
      msgs := msgs || jsonb_build_array(jsonb_build_object('title', t, 'body', b, 'tag', 'now-' || ids_now[1], 'url', './'));
    end if;
    -- the evening summary: everything chosen for it from before the last summary time, outside quiet hours, with totals by category
    select array_agg(o.id order by o.made_at), left(string_agg('• ' || o.body, E'\n' order by o.made_at), 1500)
      into ids_eve, b
      from private.push_outbox o
      where o.user_id = u.user_id and o.sent_at is null and (o.taken_at is null or o.taken_at < p_now - interval '5 minutes')
        and o.tell <> 'test' and p->>o.tell = 'evening' and o.made_at < dg and not quiet;
    if ids_eve is not null then
      select string_agg(k || ' ' || private.money(s), ' · ' order by s desc) into cs
        from (select c.key k, sum((c.value #>> '{}')::numeric) s from private.push_outbox o, jsonb_each(coalesce(o.cats, '{}'::jsonb)) c
              where o.id = any(ids_eve) and jsonb_typeof(c.value) = 'number' group by c.key) tot;
      msgs := msgs || jsonb_build_array(jsonb_build_object(
        'title', 'The shop, cigarettes and drinks',
        'body', case when cs is not null then cs || E'\n' || cardinality(ids_eve) || case when cardinality(ids_eve) = 1 then ' purchase' else ' purchases' end || ' logged' else b end,
        'tag', 'digest-' || to_char(dg at time zone 'Europe/Dublin', 'YYYY-MM-DD'), 'url', './'));
    end if;
    if jsonb_array_length(msgs) = 0 then
      continue;
    end if;
    update private.push_outbox o set taken_at = p_now, tries = o.tries + 1 where o.id = any(coalesce(ids_now, '{}') || coalesce(ids_eve, '{}'));
    out := out || jsonb_build_array(jsonb_build_object('user', u.user_id, 'devices', devs, 'messages', msgs, 'ids', to_jsonb(coalesce(ids_now, '{}') || coalesce(ids_eve, '{}'))));
  end loop;
  return out;
end $$;

-- For the sender: what went out. Devices the push service says are gone (404/410) are removed.
create function public.push_done(p_ids bigint[], p_ok text[] default '{}', p_gone text[] default '{}', p_now timestamptz default now()) returns void
language sql security definer set search_path = '' as $$
  update private.push_outbox set sent_at = p_now, status = 'sent' where id = any(p_ids) and sent_at is null;
  update public.push_devices set last_ok = p_now where endpoint = any(p_ok);
  delete from public.push_devices where endpoint = any(p_gone);
$$;
revoke all on function public.push_take(timestamptz) from public, anon, authenticated;
revoke all on function public.push_done(bigint[], text[], text[], timestamptz) from public, anon, authenticated;
grant execute on function public.push_take(timestamptz) to service_role;
grant execute on function public.push_done(bigint[], text[], text[], timestamptz) to service_role;

-- "Send me a test", from the app: to the devices of whoever taps it, even in quiet hours (3 in 10 minutes at most).
-- Returns how many devices it goes to (0: turn notifications on here first).
create function private.push_test_in() returns integer
language plpgsql security definer set search_path = '' as $$
declare me uuid := (select auth.uid()); n integer;
begin
  if (select private.my_role()) is null then
    raise exception 'not one of us' using errcode = '42501';
  end if;
  if (select count(*) from private.push_outbox o where o.user_id = me and o.tell = 'test' and o.made_at > now() - interval '10 minutes') >= 3 then
    raise exception 'Three tests in 10 minutes is enough: try again a bit later' using errcode = '54000';
  end if;
  select count(*) into n from public.push_devices d where d.user_id = me;
  if n > 0 then
    insert into private.push_outbox (user_id, tell, title, body) values (me, 'test', 'Week by Week', 'Test: notifications work on this phone.');
  end if;
  return n;
end $$;
revoke all on function private.push_test_in() from public;
grant execute on function private.push_test_in() to authenticated;
create function public.push_test() returns integer
language sql volatile security invoker set search_path = '' as $$ select private.push_test_in() $$;
revoke all on function public.push_test() from public, anon;
grant execute on function public.push_test() to authenticated;

-- The locks: each of us, our own devices and choices only.
alter table public.push_devices enable row level security;
alter table public.push_prefs enable row level security;
revoke all on public.push_devices, public.push_prefs from anon, authenticated;
grant select, insert, update, delete on public.push_devices to authenticated;
grant select, insert, update on public.push_prefs to authenticated;
create policy "devices: our own" on public.push_devices for all to authenticated
  using (user_id = (select auth.uid()) and (select private.my_role()) is not null)
  with check (user_id = (select auth.uid()) and (select private.my_role()) is not null);
create policy "prefs: our own" on public.push_prefs for all to authenticated
  using (user_id = (select auth.uid()) and (select private.my_role()) is not null)
  with check (user_id = (select auth.uid()) and (select private.my_role()) is not null);
create function private.push_prefs_stamp() returns trigger
language plpgsql set search_path = '' as $$ begin new.updated_at := now(); return new; end $$;
revoke all on function private.push_prefs_stamp() from public;
create trigger push_prefs_stamp before insert or update on public.push_prefs
  for each row execute function private.push_prefs_stamp();

-- Rory's answer tells Thiago (the History line the database writes now carries tell: answers).
create or replace function private.answer_in() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  q jsonb; title text; short text; ts timestamptz := now();
  ans text := new.data->>'answer'; said text := btrim(new.data->>'said');
begin
  if (select private.my_role()) = 'editor' then   -- only a backup import (doc_import) gets here as the editor: old answers come back as they were
    return new;
  end if;
  new.at := ts;
  new.answered_by := auth.uid();
  new.data := new.data || jsonb_build_object('at', to_char(ts at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), 'said', said);
  if new.data->>'kind' = 'compare' then
    select d.data into q from public.docs d where d.coll = 'compare' and d.id = new.data->>'ref';
    if q is null or q->'rory' is null or q->>'status' = 'applied'
       or q->'rory'->>'asked' is distinct from new.data->>'asked' or q->'rory'->>'plan' is distinct from new.data->>'plan' then
      raise exception 'That question isn''t open' using errcode = '22023';
    end if;
    title := 'Compare, ' || coalesce(q->>'name', '') || ' · ' || coalesce(q->'rory'->>'planName', '');
    short := 'Rory said ' || ans || ' to ' || coalesce(q->>'name', '') || ' · ' || coalesce(q->'rory'->>'planName', '') || ': “' || said || '”';
  else
    select d.data into q from public.docs d where d.coll = 'wishlist' and d.id = new.data->>'ref';
    if q is null or coalesce(q->>'status', 'waiting') in ('bought', 'dropped')
       or coalesce(q->>'asked', q->>'addedAt') is distinct from new.data->>'asked' then
      raise exception 'That question isn''t open' using errcode = '22023';
    end if;
    title := 'wishlist, ' || coalesce(q->>'what', '') || ' €' || to_char(coalesce((q->>'price')::numeric, 0), 'FM999,990.00');
    short := 'Rory said ' || ans || ' to ' || coalesce(q->>'what', '') || ': “' || said || '”';
  end if;
  if exists (select 1 from public.answers a where a.data->>'kind' = new.data->>'kind' and a.data->>'ref' = new.data->>'ref' and a.data->>'asked' = new.data->>'asked') then
    raise exception 'Already answered' using errcode = '23505';
  end if;
  insert into public.docs (coll, id, data) values ('changelog', 'ans' || new.id, jsonb_build_object(
    'at', new.data->>'at', 'date', to_char(ts at time zone 'Europe/Dublin', 'YYYY-MM-DD'), 'kind', 'decision',
    'text', 'Rory’s answer, from his own account (' || title || '): ' || ans || ', “' || said || '”.',
    case when new.data->>'kind' = 'compare' then 'cmp' else 'wish' end, new.data->>'ref',
    'step', 'answer', 'rory', ans, 'short', short, 'tell', 'answers'));
  return new;
end $$;

-- The import is quiet: bringing a backup back in tells nobody anything.
create or replace function public.doc_import(p_docs jsonb) returns integer
language plpgsql security invoker set search_path = '' as $$
declare n integer;
begin
  if (select private.my_role()) is distinct from 'editor' then
    raise exception 'read only' using errcode = '42501';
  end if;
  if jsonb_typeof(p_docs) <> 'array' or jsonb_array_length(p_docs) = 0 then
    raise exception 'empty import' using errcode = '22023';
  end if;
  perform set_config('wbw.importing', 'on', true);
  delete from public.docs where true;
  insert into public.docs (coll, id, data)
    select d->>'coll', d->>'id', d->'data' from jsonb_array_elements(p_docs) d where d->>'coll' <> 'answers';
  get diagnostics n = row_count;
  n := n + private.answers_replace(p_docs);
  perform set_config('wbw.importing', 'off', true);
  return n;
end $$;
revoke all on function public.doc_import(jsonb) from public, anon;
grant execute on function public.doc_import(jsonb) to authenticated;
