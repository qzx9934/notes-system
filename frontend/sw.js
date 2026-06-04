/* 工作笔记系统 Service Worker
 * 策略：
 *  - /api/* 与所有非 GET 请求：直接走网络，永不缓存（保证登录态/数据实时）
 *  - 导航请求：网络优先，断网回退到已缓存的应用外壳（index.html）
 *  - 其余同源静态资源：缓存优先，未命中则网络并回填
 * 升级缓存：改 CACHE 版本号即可，activate 时清理旧缓存。
 */
const CACHE = 'notes-shell-v31';
const SHELL = [
  './',
  'index.html',
  'help.html',
  'vendor/marked.min.js',
  'vendor/purify.min.js',
  'manifest.webmanifest',
  'favicon.ico',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 仅处理同源 GET；API、POST/PUT/DELETE 等一律放行到网络，绝不缓存
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  // 导航：网络优先，断网回退到缓存的外壳
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('index.html').then((r) => r || caches.match('./')))
    );
    return;
  }

  // 静态资源：缓存优先
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((resp) => {
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      });
    })
  );
});
