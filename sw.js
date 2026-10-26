const CACHE_NAME = 'getmypartition-v1';
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

// Activation : nettoyage des anciens caches et prise de contrôle immédiate
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

// Interception des requêtes
self.addEventListener('fetch', (event) => {
  // Ignorer les requêtes non-GET et les protocoles exotiques (ex: chrome-extension)
  if (event.request.method !== 'GET' || !event.request.url.startsWith('http')) {
    return;
  }

  // Les appels d'API dynamiques (/api/*) passent toujours directement par le réseau
  if (event.request.url.includes('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Stratégie Network-First avec fallback Cache pour l'interface et les assets
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        // En cas d'échec réseau ou mode hors-ligne, chercher dans le cache
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // Pour la navigation, renvoyer la page racine en cache
          if (event.request.mode === 'navigate') {
            return caches.match('/');
          }
        });
      })
  );
});
