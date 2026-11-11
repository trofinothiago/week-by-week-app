// Week by Week: the push sender (Supabase Edge Function "push", verify_jwt off: it checks its own wake key).
// The database wakes it (private.push_kick, every 20 seconds, only when something is due) with the wake key from Vault.
// It takes what is due (push_take), sends each message to each of that person's phones, and reports back (push_done).
// The VAPID keys are made here on the first run and kept in Vault (push_vapid_save keeps the first ones ever saved).
import { newVapid, sendPush } from './webpush.mjs';

const BASE = Deno.env.get('SUPABASE_URL')!;
const KEY = (() => { try { return JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') || '{}').default; } catch { return undefined; } })()
  || Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const SUBJECT = 'https://trofinothiago.github.io/week-by-week-app/';   // who is sending, for the push services

async function rpc(name: string, args: Record<string, unknown> = {}) {
  const r = await fetch(`${BASE}/rest/v1/rpc/${name}`, {
    method: 'POST',
    headers: {apikey: KEY, 'Content-Type': 'application/json', ...(KEY.startsWith('sb_') ? {} : {Authorization: `Bearer ${KEY}`})},
    body: JSON.stringify(args),
  });
  const t = await r.text();
  if (!r.ok) throw new Error(`${name}: ${r.status} ${t.slice(0, 300)}`);
  return t ? JSON.parse(t) : null;
}

const same = (a: string, b: string) => { if (a.length !== b.length) return false; let x = 0; for (let i = 0; i < a.length; i++) x |= a.charCodeAt(i) ^ b.charCodeAt(i); return x === 0; };

Deno.serve(async (req) => {
  try {
    const cfg = await rpc('push_config');
    if (!cfg?.wake || !same(req.headers.get('x-wbw-wake') || '', cfg.wake)) return new Response('Not allowed', {status: 401});
    const vapid = cfg.vapid || await rpc('push_vapid_save', {p: await newVapid()});
    const batch = (await rpc('push_take')) || [];
    const done: number[] = [], ok: string[] = [], gone: string[] = [], errors: string[] = [];
    for (const u of batch) {
      let reached = false;
      for (const d of u.devices) {
        let all = true;
        for (const m of u.messages) {
          let r: Response;
          try { r = await sendPush(d, m, vapid, SUBJECT); } catch (e) { all = false; errors.push(String(e).slice(0, 200)); continue; }
          if (r.status === 404 || r.status === 410) { gone.push(d.endpoint); all = false; break; }   // that phone turned notifications off
          if (!r.ok) { all = false; errors.push(`${r.status} ${(await r.text()).slice(0, 200)}`); }
        }
        if (all) { ok.push(d.endpoint); reached = true; }
      }
      if (reached || u.devices.every((d: {endpoint: string}) => gone.includes(d.endpoint))) done.push(...u.ids);   // otherwise taken again in 5 minutes (3 tries)
    }
    if (done.length || ok.length || gone.length) await rpc('push_done', {p_ids: done, p_ok: ok, p_gone: gone});
    if (errors.length) console.error('push errors', errors);
    return Response.json({people: batch.length, done: done.length, phones: ok.length, gone: gone.length, errors});
  } catch (e) {
    console.error(e);
    return new Response('Sender error', {status: 500});
  }
});
