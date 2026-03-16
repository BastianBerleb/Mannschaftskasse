if ('serviceWorker' in navigator) {
  let newWorkerWaiting = null;

  // Service Worker Registration
  navigator.serviceWorker.register('/sw.js', { scope: '/' })
    .then(reg => {
      // Update gefunden
      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed') {
            if (navigator.serviceWorker.controller) {
              newWorkerWaiting = newWorker;
              showUpdateNotification();
            } else {
              showInstallationSuccess();
            }
          }
        });
      });
    })
    .catch(() => {});

  // Update-Benachrichtigung
  function showUpdateNotification() {
    // Wait for bootstrap to be available
    if (typeof bootstrap === 'undefined') {
       setTimeout(showUpdateNotification, 500);
       return;
    }
    
    const updateNotification = document.createElement('div');
    // Fix: Background, Text-Color, Shadow und Pointer-Events für klickbare Elemente
    updateNotification.className = 'toast position-fixed bottom-0 end-0 m-3 bg-white text-dark shadow-lg border-0';
    // Fix: Z-Index extrem hoch, damit es über allem liegt
    updateNotification.style.zIndex = '999999';
    // Fix: Interaktion erzwingen
    updateNotification.style.pointerEvents = 'auto';
    
    updateNotification.innerHTML = '<div class="toast-header bg-primary text-white">' +
      '<strong class="me-auto">🔄 Update verfügbar</strong>' +
      '<button type="button" class="btn-close" data-bs-dismiss="toast"></button>' +
      '</div>' +
      '<div class="toast-body">' +
      'Eine neue Version der App ist verfügbar.' +
      '<div class="mt-2">' +
      '<button class="btn btn-primary btn-sm" onclick="updateApp()">Jetzt aktualisieren</button>' +
      '<button class="btn btn-secondary btn-sm" data-bs-dismiss="toast">Später</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(updateNotification);
    
    const toast = new bootstrap.Toast(updateNotification, { autohide: false });
    toast.show();
  }

  // Installations-Erfolg
  function showInstallationSuccess() {
    // Wait for bootstrap
    if (typeof bootstrap === 'undefined') {
        setTimeout(showInstallationSuccess, 500);
        return;
    }
    const successNotification = document.createElement('div');
    successNotification.className = 'toast position-fixed bottom-0 end-0 m-3';
    // Fix: Z-Index manuell hochsetzen
    successNotification.style.zIndex = '11000';
    
    successNotification.innerHTML = '<div class="toast-header">' +
      '<strong class="me-auto">✅ PWA bereit</strong>' +
      '<button type="button" class="btn-close" data-bs-dismiss="toast"></button>' +
      '</div>' +
      '<div class="toast-body">' +
      'Die App ist jetzt für Offline-Nutzung bereit!' +
      '</div>';
    document.body.appendChild(successNotification);
    
    const toast = new bootstrap.Toast(successNotification);
    toast.show();
  }

  // App Update durchführen
  window.updateApp = function() {
    if (newWorkerWaiting) {
      newWorkerWaiting.postMessage({ action: 'skipWaiting' });
      newWorkerWaiting = null;
      window.location.reload();
    }
  };
}
