const CACHE_NAME = 'getmypartition-v2';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// Installation : mise en cache du shell minimal PWA
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activation : nettoyage des anciens caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Interception des requêtes (Version sécurisée iOS / Safari)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. Ignorer tout ce qui n'est pas GET ou hors domaine
  if (event.request.method !== 'GET' || !url.protocol.startsWith('http')) {
    return;
  }

  // 2. Laisser passer TOUTES les routes API Flask (/api/*) directement par le réseau
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // 3. Pour le reste (fichiers statiques, alphaTab, etc.), on privilégie le réseau 
  // SANS cache dynamique intrusif pour ne pas bloquer Safari sur iOS.
  event.respondWith(
    fetch(event.request).catch(() => {
      // En cas de panne réseau totale, on tente le cache sur la page principale
      if (event.request.mode === 'navigate') {
        return caches.match('/');
      }
      return caches.match(event.request);
    })
  );
});