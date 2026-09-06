const CACHE_NAME = 'atomo-v1';
const ASSETS = [
  '/',
  '/home.html',
  '/visao-geral.html',
  '/vendedor.html',
  '/regiao.html',
  '/marcas.html',
  '/produtos.html',
  '/produtos-cliente.html',
  '/carteira.html',
  '/positivacao.html',
  '/shelflife.html',
  '/risco.html',
  '/compras.html',
  '/manifest.json',
  '/static/css/atomo.css',
  '/static/css/widgets.css',
  '/static/js/app.js',
  '/logo.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  if (event.request.url.includes('/api/')) {
    return event.respondWith(
      fetch(event.request)
        .catch(() => {
          return new Response(
            JSON.stringify({ error: 'Sem conexão com o servidor' }),
            { headers: { 'Content-Type': 'application/json' } }
          );
        })
    );
  }
  
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          fetch(event.request).then(res => {
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, res);
            });
          });
          return response;
        }
        return fetch(event.request);
      })
      .catch(() => {
        return new Response('Offline', { status: 503 });
      })
  );
});
