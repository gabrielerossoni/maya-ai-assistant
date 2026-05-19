const CACHE_NAME = 'maya-cache-v3';

// Asset statici da precachare all'installazione
const STATIC_ASSETS = [
  '/static/maya_logo.png',
  '/static/maya_logo_no_sfondo.png',
  '/static/manifest.json',
  'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Syncopate:wght@400;700&family=Sora:wght@100;300;400;600&display=swap'
];

// Pagine principali: network-first (sempre aggiornate se online)
const NETWORK_FIRST_PATHS = [
  '/',
  '/static/jarvis_dashboard.html'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Non intercettare WebSocket, POST, o richieste cross-origin non statiche
  if (req.method !== 'GET') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;
  // Esclude le API dinamiche del backend
  if (url.pathname.startsWith('/ws') || url.pathname.startsWith('/api')) return;

  if (NETWORK_FIRST_PATHS.includes(url.pathname)) {
    // Network-first: usa cache solo se offline
    event.respondWith(
      fetch(req)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
          return response;
        })
        .catch(() => caches.match(req))
    );
  } else {
    // Cache-first: serve da cache, aggiorna in background
    event.respondWith(
      caches.match(req).then(cached => {
        const networkFetch = fetch(req).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
          }
          return response;
        }).catch(() => cached);
        return cached || networkFetch;
      })
    );
  }
});
