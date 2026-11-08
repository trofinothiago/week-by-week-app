-- Week by Week app, step 1: the data, who we are, and the locks.
-- One table holds every document exactly as the page keeps it today (collection, id, data),
-- so the page's logic doesn't change. Thiago (editor) can write; Rory (viewer) can only read;
-- nobody else sees anything. The locks live in the database (Row Level Security), not on screen.

create schema if not exists private;

-- Who we are. Rows are added by hand (dashboard or Claude through the connector), never from the app.
create table public.members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('editor', 'viewer')),
  name text not null,
  added_at timestamptz not null default now()
);

-- Every document: config/settings, bills/<id>, spending/<id>…
create table public.docs (
  coll text not null check (coll ~ '^[a-z][a-z0-9_]{0,39}$'),
  id text not null check (length(id) between 1 and 120 and position('/' in id) = 0),
  data jsonb not null default '{}'::jsonb check (jsonb_typeof(data) = 'object'),
  updated_at timestamptz not null default now(),
  updated_by uuid,
  primary key (coll, id)
);

-- The role of whoever is signed in (null for anyone who isn't one of us).
create function private.my_role() returns text
language sql stable security definer set search_path = '' as $$
  select m.role from public.members m where m.user_id = (select auth.uid())
$$;
revoke all on function private.my_role() from public;
grant usage on schema private to authenticated;
grant execute on function private.my_role() to authenticated;

-- Every write is stamped with when and by whom.
create function private.stamp() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  new.updated_by := auth.uid();
  return new;
end $$;
revoke all on function private.stamp() from public;
create trigger docs_stamp before insert or update on public.docs
  for each row execute function private.stamp();

-- The locks.
alter table public.members enable row level security;
alter table public.docs enable row level security;
revoke all on public.members, public.docs from anon, authenticated;
grant select on public.members to authenticated;
grant select, insert, update, delete on public.docs to authenticated;

create policy "members: each of us sees the two of us" on public.members
  for select to authenticated using ((select private.my_role()) is not null);
create policy "docs: both of us read" on public.docs
  for select to authenticated using ((select private.my_role()) is not null);
create policy "docs: only the editor adds" on public.docs
  for insert to authenticated with check ((select private.my_role()) = 'editor');
create policy "docs: only the editor changes" on public.docs
  for update to authenticated using ((select private.my_role()) = 'editor') with check ((select private.my_role()) = 'editor');
create policy "docs: only the editor deletes" on public.docs
  for delete to authenticated using ((select private.my_role()) = 'editor');

-- The page's update(): a shallow merge into an existing document, refused if it doesn't exist.
-- Returns the document as it now is: {data, at}.
create function public.doc_merge(p_coll text, p_id text, p_patch jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r jsonb;
begin
  if (select private.my_role()) is distinct from 'editor' then
    raise exception 'read only' using errcode = '42501';
  end if;
  update public.docs set data = data || p_patch where coll = p_coll and id = p_id
    returning jsonb_build_object('data', data, 'at', updated_at) into r;
  if r is null then
    raise exception 'no doc %/%', p_coll, p_id using errcode = 'P0002';
  end if;
  return r;
end $$;
revoke all on function public.doc_merge(text, text, jsonb) from public, anon;
grant execute on function public.doc_merge(text, text, jsonb) to authenticated;

-- The import: replaces everything in one go (all or nothing), editor only.
create function public.doc_import(p_docs jsonb) returns integer
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
    select d->>'coll', d->>'id', d->'data' from jsonb_array_elements(p_docs) d;
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.doc_import(jsonb) from public, anon;
grant execute on function public.doc_import(jsonb) to authenticated;

-- Live updates on both phones (Realtime still applies the read lock).
alter publication supabase_realtime add table public.docs;
