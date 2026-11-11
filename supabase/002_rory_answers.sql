-- Week by Week app, step 2a: Rory answers Thiago's questions from his own account.
-- Only Rory's account can write an answer (Thiago can't, nor anyone else), an answer can never be changed or deleted,
-- it must answer a question that is really open, and the database itself writes the History line.

create table public.answers (
  id text primary key check (length(id) between 1 and 120 and position('/' in id) = 0),
  data jsonb not null check (
    jsonb_typeof(data) = 'object'
    and data->>'kind' in ('compare', 'wish')
    and data->>'answer' in ('yes', 'no')
    and length(coalesce(data->>'ref', '')) between 1 and 120
    and length(coalesce(data->>'asked', '')) between 10 and 40
    and length(btrim(coalesce(data->>'said', ''))) between 2 and 500),
  answered_by uuid not null default auth.uid(),
  at timestamptz not null default now()
);

-- Before an answer is saved: stamp it, check the question is open and not answered yet, and write the History line.
create function private.answer_in() returns trigger
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
    'step', 'answer', 'rory', ans, 'short', short));
  return new;
end $$;
revoke all on function private.answer_in() from public;
create trigger answers_in before insert on public.answers
  for each row execute function private.answer_in();

-- The locks: both of us read; only Rory's own account adds; nobody changes or deletes.
alter table public.answers enable row level security;
revoke all on public.answers from anon, authenticated;
grant select, insert on public.answers to authenticated;
create policy "answers: both of us read" on public.answers
  for select to authenticated using ((select private.my_role()) is not null);
create policy "answers: only Rory answers, as himself" on public.answers
  for insert to authenticated with check ((select private.my_role()) = 'viewer' and answered_by = (select auth.uid()));

-- The import now brings Rory's answers back too (into their own table), still all or nothing, still editor only.
-- Only putting the answers back needs more rights than the editor has, so that part lives in the private schema (not reachable from the app's API).
create function private.answers_replace(p_docs jsonb) returns integer
language plpgsql security definer set search_path = '' as $$
declare m integer;
begin
  if (select private.my_role()) is distinct from 'editor' then
    raise exception 'read only' using errcode = '42501';
  end if;
  delete from public.answers where true;
  insert into public.answers (id, data, at, answered_by)
    select d->>'id', d->'data', coalesce((d->'data'->>'at')::timestamptz, now()),
           (select mm.user_id from public.members mm where mm.role = 'viewer' limit 1)
    from jsonb_array_elements(p_docs) d where d->>'coll' = 'answers';
  get diagnostics m = row_count;
  return m;
end $$;
revoke all on function private.answers_replace(jsonb) from public;
grant execute on function private.answers_replace(jsonb) to authenticated;

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
  delete from public.docs where true;
  insert into public.docs (coll, id, data)
    select d->>'coll', d->>'id', d->'data' from jsonb_array_elements(p_docs) d where d->>'coll' <> 'answers';
  get diagnostics n = row_count;
  return n + private.answers_replace(p_docs);
end $$;
revoke all on function public.doc_import(jsonb) from public, anon;
grant execute on function public.doc_import(jsonb) to authenticated;

-- Live: Rory's answer appears on Thiago's phone as soon as he sends it.
alter publication supabase_realtime add table public.answers;
