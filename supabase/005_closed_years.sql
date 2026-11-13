-- Week by Week, step 5: a closed year report can never be changed (Thiago, 13 Nov 2026).
-- A year report (coll 'years', id 'YYYY') is written once, when Thiago closes the year in January, and never again:
-- nobody can change it, delete it or write over it (not the app, not Claude, not the scheduled tasks).
-- A backup import keeps every closed year already here and only adds the ones missing.

create function private.years_closed() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    if new.id !~ '^[0-9]{4}$' or new.data->'data'->>'y' is distinct from new.id
       or new.id::int >= extract(year from now() at time zone 'Europe/Dublin')::int then
      raise exception 'a year report can only be closed once the year is over' using errcode = '23514';
    end if;
    return new;
  end if;
  raise exception 'a closed year report can never be changed' using errcode = '42501';
end $$;

create trigger docs_years_in before insert on public.docs
  for each row when (new.coll = 'years') execute function private.years_closed();
create trigger docs_years_change before update on public.docs
  for each row when (old.coll = 'years' or new.coll = 'years') execute function private.years_closed();
create trigger docs_years_gone before delete on public.docs
  for each row when (old.coll = 'years') execute function private.years_closed();

-- The import keeps the closed years: everything else is replaced as before (quietly), a closed year is never touched.
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
  delete from public.docs where coll <> 'years';
  insert into public.docs (coll, id, data)
    select d->>'coll', d->>'id', d->'data' from jsonb_array_elements(p_docs) d
    where d->>'coll' <> 'answers'
      and not (d->>'coll' = 'years' and exists (select 1 from public.docs x where x.coll = 'years' and x.id = d->>'id'));
  get diagnostics n = row_count;
  n := n + private.answers_replace(p_docs);
  perform set_config('wbw.importing', 'off', true);
  return n;
end $$;
revoke all on function public.doc_import(jsonb) from public, anon;
grant execute on function public.doc_import(jsonb) to authenticated;
