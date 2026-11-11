-- Week by Week app, step 2b (part 2): the sender's side in the database.
-- Two secrets live in Vault, never in the code or the chat: the wake key (made here, at random) that lets the database
-- wake the sender, and the VAPID keys (made by the sender on its first run). The app only ever gets the public key.
-- Every 20 seconds pg_cron asks private.push_due whether anything is due; only then pg_net wakes the sender.

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron with schema pg_catalog;

select vault.create_secret(encode(extensions.gen_random_bytes(32), 'hex'), 'wbw_push_wake', 'Week by Week: the database wakes the push sender with this');

-- For the sender (service role only): the wake key and the VAPID keys (null before the first run).
create function public.push_config() returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'wake', (select s.decrypted_secret from vault.decrypted_secrets s where s.name = 'wbw_push_wake'),
    'vapid', (select s.decrypted_secret::jsonb from vault.decrypted_secrets s where s.name = 'wbw_push_vapid'))
$$;

-- For the sender's first run: keeps the first VAPID keys ever saved and returns the ones kept
-- (two first runs at once can't end up with two different keys).
create function public.push_vapid_save(p jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if jsonb_typeof(p) is distinct from 'object' or length(coalesce(p->>'publicKey', '')) <> 87
     or jsonb_typeof(p->'privateKey') is distinct from 'object' or coalesce(p->'privateKey'->>'d', '') = '' then
    raise exception 'Those aren''t VAPID keys' using errcode = '22023';
  end if;
  if not exists (select 1 from vault.secrets s where s.name = 'wbw_push_vapid') then
    begin
      perform vault.create_secret(p::text, 'wbw_push_vapid', 'Week by Week: the VAPID keys for push (made by the sender on its first run)');
    exception when unique_violation then
      null;
    end;
  end if;
  return (select s.decrypted_secret::jsonb from vault.decrypted_secrets s where s.name = 'wbw_push_vapid');
end $$;
revoke all on function public.push_config() from public, anon, authenticated;
revoke all on function public.push_vapid_save(jsonb) from public, anon, authenticated;
grant execute on function public.push_config() to service_role;
grant execute on function public.push_vapid_save(jsonb) to service_role;

-- For the app: the public key a phone subscribes with (null until the sender's first run). Its inside lives in private.
create function private.push_public_key_in() returns text
language sql stable security definer set search_path = '' as $$
  select case when (select private.my_role()) is null then null
              else (select s.decrypted_secret::jsonb->>'publicKey' from vault.decrypted_secrets s where s.name = 'wbw_push_vapid') end
$$;
revoke all on function private.push_public_key_in() from public;
grant execute on function private.push_public_key_in() to authenticated;
create function public.push_public_key() returns text
language sql stable security invoker set search_path = '' as $$ select private.push_public_key_in() $$;
revoke all on function public.push_public_key() from public, anon;
grant execute on function public.push_public_key() to authenticated;

-- The wake-up: only when something is due, the database calls the sender with the wake key.
create function private.push_kick() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if exists (select 1 from private.push_due(now())) then
    perform net.http_post(
      url := 'https://kcdjqdebgfjfbyepaxvg.supabase.co/functions/v1/push',
      headers := jsonb_build_object('Content-Type', 'application/json',
                   'x-wbw-wake', (select s.decrypted_secret from vault.decrypted_secrets s where s.name = 'wbw_push_wake')),
      body := '{}'::jsonb, timeout_milliseconds := 20000);
  end if;
end $$;
revoke all on function private.push_kick() from public;

select cron.schedule('wbw-push', '20 seconds', 'select private.push_kick()');
