// Week by Week: Web Push with nothing but WebCrypto (the same in Deno on Supabase and in Node for the tests).
// VAPID (RFC 8292): who is sending, signed with our own key. Encryption (RFC 8291, aes128gcm): only the phone can read it.

const te = new TextEncoder();
export const b64u = {
  enc: buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''),
  dec: s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0)),
};
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let i = 0; for (const p of parts) { out.set(p, i); i += p.length; } return out; };
const hkdf = async (salt, ikm, info, bytes) => new Uint8Array(await crypto.subtle.deriveBits(
  {name: 'HKDF', hash: 'SHA-256', salt, info}, await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']), bytes * 8));

// A new pair of VAPID keys: the public one (raw, base64url) goes to the phones; the private one (JWK) stays in Vault.
export async function newVapid() {
  const k = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
  const j = await crypto.subtle.exportKey('jwk', k.privateKey);
  return {publicKey: b64u.enc(await crypto.subtle.exportKey('raw', k.publicKey)), privateKey: {kty: 'EC', crv: 'P-256', x: j.x, y: j.y, d: j.d}};
}

// The message, encrypted for one phone (its p256dh and auth from the subscription). One record, rs 4096.
// salt and the sender's key pair are random each time; the tests pass fixed ones to check against the RFC.
export async function encrypt(p256dh, auth, plaintext, salt = crypto.getRandomValues(new Uint8Array(16)), asKeys = null) {
  const ua = b64u.dec(p256dh);
  const as = asKeys || await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  const asPub = new Uint8Array(await crypto.subtle.exportKey('raw', as.publicKey));
  const uaKey = await crypto.subtle.importKey('raw', ua, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({name: 'ECDH', public: uaKey}, as.privateKey, 256));
  const ikm = await hkdf(b64u.dec(auth), shared, cat(te.encode('WebPush: info\0'), ua, asPub), 32);
  const cek = await hkdf(salt, ikm, te.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, te.encode('Content-Encoding: nonce\0'), 12);
  const data = cat(typeof plaintext === 'string' ? te.encode(plaintext) : plaintext, new Uint8Array([2]));   // 0x02: the last (only) record
  const ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv: nonce}, await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']), data));
  const rs = new Uint8Array(4); new DataView(rs.buffer).setUint32(0, 4096);
  return cat(salt, rs, new Uint8Array([asPub.length]), asPub, ct);
}

// The Authorization header: a JWT for the push service's origin, valid 12 hours, signed with our private key.
export async function vapidHeader(endpoint, vapid, subject, now = Date.now()) {
  const key = await crypto.subtle.importKey('jwk', vapid.privateKey, {name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign']);
  const part = o => b64u.enc(te.encode(JSON.stringify(o)));
  const unsigned = part({typ: 'JWT', alg: 'ES256'}) + '.' + part({aud: new URL(endpoint).origin, exp: Math.floor(now / 1000) + 12 * 3600, sub: subject});
  const sig = await crypto.subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, key, te.encode(unsigned));
  return `vapid t=${unsigned}.${b64u.enc(sig)}, k=${vapid.publicKey}`;
}

// What the phone receives: {title, body, tag, url} as JSON, kept under 3,000 bytes (Apple takes 4 KB at most).
export function payload(msg) {
  let m = {...msg}, s = JSON.stringify(m);
  while (te.encode(s).length > 3000 && m.body.length > 20) { m = {...m, body: m.body.slice(0, Math.floor(m.body.length * 0.9)) + '…'}; s = JSON.stringify(m); }
  return s;
}

// One message to one phone. Returns the push service's response (201 sent; 404/410 the phone turned it off).
export async function sendPush(device, msg, vapid, subject, fetchFn = fetch, now = Date.now()) {
  return fetchFn(device.endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream', 'Content-Encoding': 'aes128gcm', TTL: '86400', Urgency: 'normal',
      Authorization: await vapidHeader(device.endpoint, vapid, subject, now),
    },
    body: await encrypt(device.p256dh, device.auth, payload(msg)),
  });
}
