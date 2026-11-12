// Tests the service worker (sw.js) in Node: the file itself runs with a stand-in for the phone around it.
// A pushed message becomes a notification (title, text, its tag, the icon, where a tap goes); a message that isn't JSON
// still shows; a tap opens the app (or brings an open one to the front). No fetch handler: it never caches the app.
// usage: node test/sw_test.mjs
import fs from 'node:fs';
import vm from 'node:vm';

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra && !cond ? '  ' + JSON.stringify(extra) : '')); };
const src = fs.readFileSync(new URL('../sw.js', import.meta.url), 'utf8');

function phone(windows = []){
  const on = {}, shown = [], opened = [], focused = [];
  const self = {
    addEventListener: (t, f) => { on[t] = f; },
    skipWaiting: () => {},
    registration: {scope: 'https://trofinothiago.github.io/week-by-week-app/', showNotification: async (title, opt) => { shown.push({title, ...opt}); }},
    clients: {claim: async () => {}, matchAll: async () => windows.map(url => ({url, focus: async () => { focused.push(url); }})), openWindow: async url => { opened.push(url); }},
  };
  vm.runInNewContext(src, {self, URL});
  const fire = async (type, e) => { let p = null; e.waitUntil = x => { p = x; }; on[type](e); await p; };
  return {on, shown, opened, focused, fire};
}

const P = phone();
ok('it listens for push and taps only (no fetch handler: nothing is ever cached)', ['install', 'activate', 'push', 'notificationclick'].every(t => P.on[t]) && !P.on.fetch, Object.keys(P.on));
const msg = {title: 'Purchase', body: 'Purchase: Aldi €52.15 · Thiago · need · from Joint account', tag: 'now-7', url: './'};
await P.fire('push', {data: {json: () => msg, text: () => JSON.stringify(msg)}});
ok('a pushed message is shown: title, text, its tag, the app icon, where a tap goes', JSON.stringify(P.shown[0]) === JSON.stringify({title: 'Purchase', body: msg.body, tag: 'now-7', icon: 'icon-192.png', data: {url: './'}}), P.shown[0]);
await P.fire('push', {data: {json: () => { throw new Error('not JSON'); }, text: () => 'plain words'}});
ok('a message that isn’t JSON still shows (as text, under the app’s name)', P.shown[1].title === 'Week by Week' && P.shown[1].body === 'plain words', P.shown[1]);
await P.fire('push', {data: null});
ok('even an empty push shows something (iPhone requires every push to show)', P.shown[2] && P.shown[2].title === 'Week by Week', P.shown[2]);
let closed = false;
await P.fire('notificationclick', {notification: {data: {url: './'}, close: () => { closed = true; }}});
ok('a tap with the app closed opens it', closed && P.opened[0] === 'https://trofinothiago.github.io/week-by-week-app/', P.opened);
const Q = phone(['https://trofinothiago.github.io/week-by-week-app/#report']);
await Q.fire('notificationclick', {notification: {data: {url: './'}, close: () => {}}});
ok('a tap with the app open brings it to the front (no second copy)', Q.focused.length === 1 && Q.opened.length === 0, {focused: Q.focused, opened: Q.opened});
const O = phone(['https://example.com/']);
await O.fire('notificationclick', {notification: {data: null, close: () => {}}});
ok('another site’s window is never used', O.focused.length === 0 && O.opened[0] === 'https://trofinothiago.github.io/week-by-week-app/', O);

console.log(`${pass} of ${pass + fail} passed`);
process.exit(fail ? 1 : 0);
