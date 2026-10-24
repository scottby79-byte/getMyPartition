self.addEventListener('fetch', (event) => {
  // Laisse passer les requêtes normalement vers Flask
  event.respondWith(fetch(event.request));
});