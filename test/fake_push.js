// Week by Week app tests: a stand-in for the phone's notifications (Notification, the service worker and PushManager),
// so the app's real bridge code (app/bridge.js, notify) runs in the test browser. Nothing is really subscribed or sent.
// window.__push.answer: what the phone answers when asked ('granted', 'denied' or 'default').
(() => {
  const P = window.__push = {permission: 'default', answer: 'granted', asked: 0, registered: false, sub: null};
  Object.defineProperty(window, 'Notification', {configurable: true, writable: true, value: {
    get permission(){ return P.permission; },
    requestPermission: async () => { P.asked++; P.permission = P.answer; return P.permission; }}});
  const subscription = key => ({
    endpoint: 'https://web.push.apple.com/test-' + Math.random().toString(36).slice(2), options: {applicationServerKey: key.buffer},
    toJSON(){ return {endpoint: this.endpoint, keys: {p256dh: 'B' + 'C'.repeat(86), auth: 'a'.repeat(22)}}; },
    unsubscribe: async () => { P.sub = null; return true; }});
  const reg = {scope: location.href, pushManager: {getSubscription: async () => P.sub, subscribe: async o => (P.sub = subscription(new Uint8Array(o.applicationServerKey)))}};
  Object.defineProperty(navigator, 'serviceWorker', {configurable: true, value: {
    register: async () => { P.registered = true; return reg; }, ready: Promise.resolve(reg), getRegistration: async () => (P.registered ? reg : undefined)}});
  window.PushManager = window.PushManager || function(){};
})();
