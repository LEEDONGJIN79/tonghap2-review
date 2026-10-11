/* 통합사회2 중간대비 — 서비스 워커
 * 앱 셸(index.html, manifest.webmanifest, 아이콘): 캐시 우선 + 백그라운드 갱신
 * data/, images/: 네트워크 우선, 실패하면 캐시
 * 캐시를 통째로 새로 만들어야 할 때만 CACHE_VERSION을 올린다(예: 'v2').
 */
const CACHE_VERSION = 'v1';
const SHELL_CACHE = 't2r-shell-' + CACHE_VERSION;
const DATA_CACHE = 't2r-data-' + CACHE_VERSION;
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png', './icon-maskable-512.png'];

const scopePath = () => new URL(self.registration.scope).pathname;
const keyOf = (u) => { const url = new URL(u, self.registration.scope); return url.origin + url.pathname; };
function isData(url) {
  const base = scopePath();
  const rel = url.pathname.startsWith(base) ? url.pathname.slice(base.length) : url.pathname;
  return rel.startsWith('data/') || rel.startsWith('images/');
}
function cacheable(res) { return res && res.ok && !res.redirected && res.type === 'basic'; }

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.all(SHELL_FILES.map(async (f) => {
      try { const res = await fetch(f, { cache: 'no-cache' }); if (cacheable(res)) await cache.put(keyOf(f), res); } catch (e) { /* 다음 기회에 */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith('t2r-') && k !== SHELL_CACHE && k !== DATA_CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(scopePath())) return;
  if (url.pathname.endsWith('/sw.js')) return;
  if (isData(url)) { event.respondWith(networkFirst(req)); return; }
  if (req.mode === 'navigate') { event.respondWith(navigate(req, event)); return; }
  event.respondWith(cacheFirst(req, event));
});

async function networkFirst(req) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const res = await fetch(req);
    if (cacheable(res)) cache.put(keyOf(req.url), res.clone());
    return res;
  } catch (err) {
    const hit = (await cache.match(keyOf(req.url), { ignoreSearch: true })) || (await caches.match(keyOf(req.url), { ignoreSearch: true }));
    if (hit) return hit;
    return new Response('', { status: 504, statusText: 'offline' });
  }
}
async function cacheFirst(req, event) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = await cache.match(keyOf(req.url), { ignoreSearch: true });
  const net = fetch(req).then((res) => { if (cacheable(res)) cache.put(keyOf(req.url), res.clone()); return res; }).catch(() => null);
  if (hit) { event.waitUntil(net); return hit; }
  return (await net) || new Response('', { status: 504, statusText: 'offline' });
}
async function navigate(req, event) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = (await cache.match(keyOf('./index.html'))) || (await cache.match(keyOf('./')));
  const net = fetch(req).then((res) => { if (cacheable(res)) cache.put(keyOf('./index.html'), res.clone()); return res; }).catch(() => null);
  if (hit) { event.waitUntil(net); return hit; }
  return (await net) || new Response('<!doctype html><meta charset="utf-8"><p style="font:16px sans-serif;padding:24px">인터넷에 연결된 상태에서 한 번 열어 주세요.</p>', { status: 503, headers: { 'content-type': 'text/html; charset=utf-8' } });
}

/* 페이지의 '전체 문제 내려받기' → { type:'precache', urls } + MessagePort로 진행률 */
self.addEventListener('message', (event) => {
  const d = event.data || {};
  if (d.type === 'precache' && Array.isArray(d.urls)) event.waitUntil(precache(d.urls, event.ports && event.ports[0]));
  else if (d.type === 'skipWaiting') self.skipWaiting();
});
async function precache(urls, port) {
  const shell = await caches.open(SHELL_CACHE), data = await caches.open(DATA_CACHE);
  const total = urls.length; let done = 0, failed = 0;
  const queue = urls.slice();
  const post = (m) => { try { port && port.postMessage(m); } catch (e) { /* 무시 */ } };
  async function worker() {
    while (queue.length) {
      const u = queue.shift();
      try {
        const url = new URL(u, self.registration.scope);
        const res = await fetch(url.href, { cache: 'no-cache' });
        if (!cacheable(res)) throw new Error('bad ' + res.status);
        await (isData(url) ? data : shell).put(keyOf(url.href), res);
        if (url.pathname === scopePath()) await shell.put(keyOf('./index.html'), (await shell.match(keyOf(url.href))).clone());
      } catch (e) { failed++; }
      done++;
      post({ type: 'progress', done, failed, total });
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
  post({ type: 'done', done, failed, total });
}
