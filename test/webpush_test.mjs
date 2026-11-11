// Tests the push sender's Web Push code (supabase/functions/push/webpush.mjs) with Node's WebCrypto:
// the RFC 8291 example message byte for byte, a phone decrypting it (http_ece, the reference implementation),
// the VAPID signature and claims, the size limit, and the request the push service receives.
// usage: node test/webpush_test.mjs
import crypto from 'node:crypto';
import ece from 'http_ece';
import { b64u, newVapid, encrypt, vapidHeader, payload, sendPush } from '../supabase/functions/push/webpush.mjs';

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra && !cond ? '  ' + extra : '')); };
const S = crypto.webcrypto.subtle;

// RFC 8291, Appendix A
const A = {
  plain: 'When I grow up, I want to be a watermelon',
  uaPublic: 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
  asPrivate: 'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw',
  asPublic: 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8',
  auth: 'BTBZMqHH6r4Tts7J_aSIgg',
  salt: 'DGv6ra1nlYgDCS1FRnbzlw',
  out: 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN',
};
const asRaw = b64u.dec(A.asPublic);
const asKeys = {
  publicKey: await S.importKey('raw', asRaw, {name: 'ECDH', namedCurve: 'P-256'}, true, []),
  privateKey: await S.importKey('jwk', {kty: 'EC', crv: 'P-256', x: b64u.enc(asRaw.slice(1, 33)), y: b64u.enc(asRaw.slice(33)), d: A.asPrivate}, {name: 'ECDH', namedCurve: 'P-256'}, false, ['deriveBits']),
};
const rfc = await encrypt(A.uaPublic, A.auth, A.plain, b64u.dec(A.salt), asKeys);
ok('the RFC 8291 example message comes out byte for byte', b64u.enc(rfc) === A.out, b64u.enc(rfc));

// A phone (its own keys, like an iPhone's subscription) reads what we send
const phone = crypto.createECDH('prime256v1'); phone.generateKeys();
const sub = {endpoint: 'https://web.push.apple.com/QH8x', p256dh: b64u.enc(phone.getPublicKey()), auth: b64u.enc(crypto.randomBytes(16))};
const msg = {title: 'Purchase', body: 'Purchase: Aldi €52.15 · Thiago · need · from Joint account', tag: 'now-7', url: './'};
const enc = await encrypt(sub.p256dh, sub.auth, payload(msg));
const dec = ece.decrypt(Buffer.from(enc), {version: 'aes128gcm', privateKey: phone, authSecret: b64u.enc(b64u.dec(sub.auth))});
ok('a phone decrypts it with its own keys (reference implementation)', dec.toString('utf8') === JSON.stringify(msg), dec.toString('utf8'));
const enc2 = await encrypt(sub.p256dh, sub.auth, payload(msg));
ok('every message is encrypted afresh (new salt and key)', b64u.enc(enc) !== b64u.enc(enc2));
const other = crypto.createECDH('prime256v1'); other.generateKeys();
let wrong = false; try { ece.decrypt(Buffer.from(enc), {version: 'aes128gcm', privateKey: other, authSecret: b64u.enc(b64u.dec(sub.auth))}); } catch { wrong = true; }
ok('another phone can’t read it', wrong);

// VAPID
const V = await newVapid();
ok('new VAPID keys: a 65-byte public key for the phones, a private JWK kept back', b64u.dec(V.publicKey).length === 65 && V.privateKey.d && V.privateKey.kty === 'EC' && !('key_ops' in V.privateKey));
const NOW = Date.UTC(2026, 10, 12, 10, 0, 0);
const hdr = await vapidHeader(sub.endpoint, V, 'https://trofinothiago.github.io/week-by-week-app/', NOW);
const m = /^vapid t=([^.]+)\.([^.]+)\.([^,]+), k=(.+)$/.exec(hdr);
const claims = m && JSON.parse(Buffer.from(b64u.dec(m[2])).toString());
ok('the header is “vapid t=<JWT>, k=<public key>”', m && m[4] === V.publicKey && JSON.parse(Buffer.from(b64u.dec(m[1])).toString()).alg === 'ES256');
ok('the JWT is for the push service’s origin, 12 hours, with our contact', claims && claims.aud === 'https://web.push.apple.com' && claims.exp === NOW / 1000 + 12 * 3600 && claims.sub.startsWith('https://'));
const pub = await S.importKey('raw', b64u.dec(V.publicKey), {name: 'ECDSA', namedCurve: 'P-256'}, false, ['verify']);
const valid = m && await S.verify({name: 'ECDSA', hash: 'SHA-256'}, pub, b64u.dec(m[3]), new TextEncoder().encode(m[1] + '.' + m[2]));
ok('the signature checks out with the public key', valid === true);
const V2 = await newVapid();
const hdr2 = await vapidHeader(sub.endpoint, V2, 'https://x.y/', NOW), m2 = /t=([^.]+)\.([^.]+)\.([^,]+),/.exec(hdr2);
ok('a signature from other keys doesn’t', !(await S.verify({name: 'ECDSA', hash: 'SHA-256'}, pub, b64u.dec(m2[3]), new TextEncoder().encode(m2[1] + '.' + m2[2]))));

// Size
const long = payload({title: '30 updates', body: '• Purchase: Aldi €52.15 · Thiago · need · from Joint account\n'.repeat(80), tag: 'now-1', url: './'});
ok('a long message is cut to fit (under 3,000 bytes, ends with …)', new TextEncoder().encode(long).length <= 3000 && JSON.parse(long).body.endsWith('…'), new TextEncoder().encode(long).length);
ok('a short one is left as it is', payload(msg) === JSON.stringify(msg));

// The request the push service receives
let got = null;
const res = await sendPush(sub, msg, V, 'https://trofinothiago.github.io/week-by-week-app/', async (url, init) => { got = {url, init}; return new Response(null, {status: 201}); }, NOW);
ok('sent to the phone’s own push address, as a POST', res.status === 201 && got.url === sub.endpoint && got.init.method === 'POST');
ok('with the headers Apple needs (TTL, aes128gcm, VAPID)', got.init.headers.TTL === '86400' && got.init.headers['Content-Encoding'] === 'aes128gcm' && got.init.headers.Authorization.startsWith('vapid t='));
const back = ece.decrypt(Buffer.from(got.init.body), {version: 'aes128gcm', privateKey: phone, authSecret: b64u.enc(b64u.dec(sub.auth))});
ok('and the phone can read what was sent', JSON.parse(back.toString()).body === msg.body);

console.log(`${pass} of ${pass + fail} passed`);
process.exit(fail ? 1 : 0);
