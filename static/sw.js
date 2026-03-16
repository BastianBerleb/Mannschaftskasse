// Service Worker für Mannschaftskasse PWA
// Version: 3.0 - Performance Optimierungen Multi-Device

const CACHE_NAME = 'mannschaftskasse-v3.0';
const STATIC_CACHE = 'static-v3.0'; 
const API_CACHE = 'api-v3.0';

// Kritische Dateien, die immer gecacht werden müssen
const CRITICAL_CACHE_FILES = [
  '/',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
  '/static/images/tsv-alteglofsheim.jpg',
  '/offline',
  '/static/app/manifest.json'
];

// Zusätzliche statische Ressourcen
const STATIC_CACHE_FILES = [
  '/static/js/admin.js',
  '/static/js/push-manager.js'
];

// Installation: Kritische Dateien cachen
self.addEventListener('install', event => {
  event.waitUntil(
    Promise.all([
      // Kritische Dateien
      caches.open(CACHE_NAME).then(cache => {
        return cache.addAll(CRITICAL_CACHE_FILES).catch(() => {});
      }),
      // Statische Dateien
      caches.open(STATIC_CACHE).then(cache => {
        return cache.addAll(STATIC_CACHE_FILES).catch(() => {});
      })
    ])
    .then(() => self.skipWaiting())
  );
});

// Aktivierung: Alte Caches löschen
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            if (cacheName !== CACHE_NAME && 
                cacheName !== STATIC_CACHE && 
                cacheName !== API_CACHE) {
              return caches.delete(cacheName);
            }
          })
        );
      })
      .then(() => self.clients.claim())
  );
});

// Fetch-Events: Intelligente Cache-Strategie
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // LOGIN/LOGOUT: Immer Netzwerk, kein Service Worker
  if (url.pathname === '/logout' || url.pathname === '/login') {
      return; // Browser Standard-Verhalten (Kein SW)
  }
  
  // Nur GET-Requests cachen
  if (event.request.method !== 'GET') {
    return;
  }
  
  // Navigation Requests (Seitenaufrufe)
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          // Erfolgreiche Navigation: Cache für offline
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(event.request)
            .then(cachedResponse => {
              if (cachedResponse) {
                return cachedResponse;
              }
              // Fallback: Startseite oder Offline-Seite
              return caches.match('/')
                .then(homeResponse => homeResponse || caches.match('/offline'));
            });
        })
    );
    return;
  }
  
  // Static Assets (CSS, JS, Images) - Cache First für bessere Performance
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request)
        .then(cachedResponse => {
          if (cachedResponse) {
            return cachedResponse;
          }
          return fetch(event.request)
            .then(response => {
              if (response.ok) {
                const responseClone = response.clone();
                caches.open(STATIC_CACHE).then(cache => {
                  cache.put(event.request, responseClone);
                });
              }
              return response;
            })
            .catch(error => {
              console.error('❌ Static asset failed:', error.message);
              throw error;
            });
        })
    );
    return;
  }
  
  // API Requests (Daten)
  if (url.pathname.startsWith('/api/') || 
      url.pathname.includes('ajax') ||
      url.pathname.includes('update')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(API_CACHE).then(cache => {
              cache.put(event.request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(event.request);
        })
    );
    return;
  }
  
  // Alle anderen Requests: Standard-Behandlung
  event.respondWith(
    fetch(event.request)
      .catch(() => caches.match(event.request))
  );
});

// Background Sync (für zukünftige Offline-Features)
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    event.waitUntil(doBackgroundSync());
  }
});

async function doBackgroundSync() {
  // Hier können später Offline-Daten synchronisiert werden
}

// Message Listener (für Skip Waiting, Reset, Logout)
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'LOGOUT') {
     // Nur API-Cache leeren (User-spezifische Daten)
     if (typeof API_CACHE !== 'undefined') {
         caches.delete(API_CACHE);
     }
  }
});

// Push Notifications
self.addEventListener('push', event => {
  let data = {};
  let title = 'Mannschaftskasse';
  let body = 'Neue Benachrichtigung';
  let url = '/';

  if (event.data) {
    try {
      // Versuche JSON zu parsen (das Format vom Backend)
      data = event.data.json();
      title = data.title || title;
      body = data.body || body;
      url = data.url || url;
    } catch(e) {
      // Fallback: Text
      body = event.data.text();
    }
  }
  
  const options = {
    body: body,
    icon: '/static/images/tsv-alteglofsheim.jpg',
    badge: '/static/images/tsv-alteglofsheim.jpg',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: '1',
      url: url // URL für Click-Handler speichern
    },
    actions: [
      {
        action: 'explore',
        title: 'Ansehen',
      },
      {
        action: 'close',
        title: 'Schließen'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// Notification Click
self.addEventListener('notificationclick', event => {
  event.notification.close();

  if (event.action === 'close') {
      return;
  }

  // Standard-Aktion oder 'explore'
  let targetUrl = '/';
  if (event.notification.data && event.notification.data.url) {
      targetUrl = event.notification.data.url;
  }
  
  event.waitUntil(
    clients.matchAll({type: 'window', includeUncontrolled: true}).then(windowClients => {
        // Prüfen ob Fenster schon offen ist
        for (let i = 0; i < windowClients.length; i++) {
            const client = windowClients[i];
            if (client.url === targetUrl && 'focus' in client) {
                return client.focus();
            }
        }
        // Sonst neu öffnen
        if (clients.openWindow) {
            return clients.openWindow(targetUrl);
        }
    })
  );
});
