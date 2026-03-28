// PWA App Installation Manager
// Handles all aspects of PWA installation prompts and UI

class PWAInstallManager {
  constructor() {
    this.deferredPrompt = null;
    this.installButtons = [];
    this.mobileOverlay = null;
    this.miniInstallBanner = null;
    
    this.init();
  }

  init() {
    // Sammle alle Install-Buttons
    this.installButtons = [
      document.getElementById('pwa-install-button'),
      document.getElementById('install-app-mini-btn'), 
      document.getElementById('install-app-btn'), // Prominenter Button!
      document.getElementById('mobile-install-button')
    ].filter(btn => btn !== null);
    
    this.mobileOverlay = document.getElementById('mobile-install-overlay');
    this.miniInstallBanner = document.getElementById('app-install-mini-banner');
    this.mainInstallBanner = document.getElementById('app-install-banner'); // Prominenter Banner
    
    this.setupEventListeners();
    this.checkIOSAutoShow();
  }

  setupEventListeners() {
    // beforeinstallprompt Event
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      this.deferredPrompt = e;
      this.showInstallUI();
    });

    // Install Button Handlers
    this.installButtons.forEach(btn => {
      if (btn) {
        btn.addEventListener('click', () => this.handleInstallClick());
      }
    });

    // Mobile Overlay Controls
    const mobileInstructionsBtn = document.getElementById('mobile-install-instructions');
    const mobileDismissBtn = document.getElementById('mobile-install-dismiss');
    const mobileNeverBtn = document.getElementById('mobile-install-never');

    if (mobileInstructionsBtn) {
      mobileInstructionsBtn.addEventListener('click', () => {
        this.hideAllInstallUIs();
        this.showInstallInstructions();
      });
    }

    if (mobileDismissBtn) {
      mobileDismissBtn.addEventListener('click', () => {
        this.hideAllInstallUIs();
        localStorage.setItem('pwa-install-dismissed', Date.now());
      });
    }

    if (mobileNeverBtn) {
      mobileNeverBtn.addEventListener('click', () => {
        this.hideAllInstallUIs();
        localStorage.setItem('pwa-install-never', 'true');
      });
    }
  }

  isIOS() {
    return /iPhone|iPad|iPod/i.test(navigator.userAgent) && !window.MSStream;
  }

  checkIOSAutoShow() {
    if (this.isIOS() && !this.isStandalone()) {
        // iOS feuert kein beforeinstallprompt, also manuell UI zeigen
        this.showMobileInstallPrompt();
        
        // Buttons sichtbar machen
        this.installButtons.forEach(btn => {
            if (btn) btn.style.display = 'block';
        });
    }
  }

  showInstallUI() {
    if (this.isStandalone()) {
      return;
    }

    // Prüfe ob kürzlich dismissed (24h)
    const dismissed = localStorage.getItem('pwa-install-dismissed');
    if (dismissed && (Date.now() - parseInt(dismissed)) < 86400000) { 
      return;
    }

    if (this.isMobileDevice()) {
      this.showMobileInstallPrompt();
    } else {
      // Prominenten Install-Banner auf dem Desktop / Tablet statt nur des kleinen anzeigen:
      if (this.mainInstallBanner) {
        this.mainInstallBanner.classList.remove('d-none');
      } else if (this.miniInstallBanner) {
        this.miniInstallBanner.classList.remove('d-none');
      }
    }
    
    // Alle Buttons aktivieren
    this.installButtons.forEach(btn => {
      if (btn) btn.style.display = 'block';
    });
  }

  async handleInstallClick() {
    // Case 1: iOS oder Browser ohne deferredPrompt (manuelle Anleitung)
    if (!this.deferredPrompt) {
      this.hideAllInstallUIs(); // Zuerst Overlay verstecken!
      this.showInstallInstructions(); // Zeige Modal
      return;
    }

    // Case 2: Android / Chrome mit nativem Prompt
    try {
      // Verstecke alle Install-UIs
      this.hideAllInstallUIs();
      
      // Zeige nativen Install-Dialog
      this.deferredPrompt.prompt();
      
      // Warte auf Benutzerentscheidung
      const { outcome } = await this.deferredPrompt.userChoice;
      
      if (outcome === 'accepted') {
        this.showInstallSuccess();
      }
      
      // Event kann nur einmal verwendet werden
      this.deferredPrompt = null;
      
    } catch (error) {
      this.showInstallInstructions();
    }
  }

  isMobileDevice() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
           (window.innerWidth <= 768);
  }

  showMobileInstallPrompt() {
    // Prüfe ob schon installiert oder abgelehnt
    if (this.isStandalone() || localStorage.getItem('pwa-install-never') === 'true') {
      return;
    }
    
    // Prüfe ob kürzlich dismissed (24h)
    const dismissed = localStorage.getItem('pwa-install-dismissed');
    if (dismissed && (Date.now() - parseInt(dismissed)) < 86400000) { 
      return;
    }
    
    if (this.mobileOverlay) {
      this.mobileOverlay.classList.remove('d-none');
      // Animation frame für transition
      requestAnimationFrame(() => {
        this.mobileOverlay.style.opacity = '1';
      });
    }
  }

  hideAllInstallUIs() {
    if (this.mobileOverlay) {
      this.mobileOverlay.style.opacity = '0';
      setTimeout(() => {
        this.mobileOverlay.classList.add('d-none');
      }, 300);
    }
    if (this.miniInstallBanner) {
      this.miniInstallBanner.classList.add('d-none');
    }
    if (this.mainInstallBanner) {
      this.mainInstallBanner.classList.add('d-none');
    }
  }

  isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches ||
           window.navigator.standalone === true;
  }

  showInstallInstructions() {
    // Modal HTML dynamisch erstellen
    const instructions = this.getInstallInstructions();
    const modalId = 'pwaInstallModal';
    
    // Existierendes Modal löschen
    const existingModal = document.getElementById(modalId);
    if (existingModal) existingModal.remove();

    const isIOS = this.isIOS();
    
    const modalHtml = `
      <div class="modal fade" id="${modalId}" tabindex="-1" aria-hidden="true" style="z-index: 10000;">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content text-dark">
            <div class="modal-header bg-primary text-white">
              <h5 class="modal-title">📲 App installieren</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body p-4">
              ${instructions}
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Verstanden</button>
            </div>
          </div>
        </div>
      </div>`;
      
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Bootstrap Modal initialisieren und anzeigen
    const modalElement = document.getElementById(modalId);
    if (window.bootstrap && window.bootstrap.Modal) {
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
    } else {
        // Fallback falls Bootstrap nicht geladen (unwahrscheinlich)
        alert(instructions.replace(/<[^>]*>/g, ''));
    }
  }

  getInstallInstructions() {
    const userAgent = navigator.userAgent;
    
    if (/iPhone|iPad|iPod/i.test(userAgent)) {
      return `
        <div class="text-center mb-3">
            <span style="font-size: 3rem;">🍎</span>
        </div>
        <h6>So installierst du die App auf iOS:</h6>
        <ol class="list-group list-group-numbered list-group-flush text-start">
          <li class="list-group-item">Tippe unten in der Leiste auf den <strong>Teilen-Button</strong> <br><span class="fs-2">⬆️</span></li>
          <li class="list-group-item">Scrolle nach unten und wähle <strong>"Zum Home-Bildschirm"</strong> <br><span class="fs-4">➕</span></li>
          <li class="list-group-item">Tippe oben rechts auf <strong>"Hinzufügen"</strong></li>
        </ol>`;
    } else if (/Android/i.test(userAgent)) {
      return `
        <div class="text-center mb-3">
            <span style="font-size: 3rem;">🤖</span>
        </div>
        <h6>So installierst du die App auf Android:</h6>
        <ol class="list-group list-group-numbered list-group-flush text-start">
          <li class="list-group-item">Öffne das Browser-Menü (meist oben rechts) <br><span class="fs-4">⋮</span></li>
          <li class="list-group-item">Wähle <strong>"App installieren"</strong> oder <strong>"Zum Startbildschirm hinzufügen"</strong></li>
          <li class="list-group-item">Bestätige die Installation</li>
        </ol>`;
    } else {
      return `
        <div class="text-center mb-3">
            <span style="font-size: 3rem;">💻</span>
        </div>
        <h6>Installation auf dem Desktop:</h6>
        <ul class="list-group list-group-flush text-start">
          <li class="list-group-item">Klicke auf das <strong>Installations-Symbol</strong> rechts in der Adressleiste (Chrome/Edge)</li>
          <li class="list-group-item">Oder suche im Menü nach "App installieren"</li>
        </ul>`;
    }
  }

  showInstallSuccess() {
    const toast = document.createElement('div');
    toast.className = 'toast position-fixed bottom-0 end-0 m-3 align-items-center text-white bg-success border-0';
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          <strong>✅ Erfolg!</strong><br>
          Die App wurde erfolgreich installiert.
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    document.body.appendChild(toast);
    
    if (window.bootstrap && window.bootstrap.Toast) {
        const bootstrapToast = new bootstrap.Toast(toast);
        bootstrapToast.show();
    }
    
    setTimeout(() => {
      toast.remove();
    }, 5000);
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  window.pwaInstallManager = new PWAInstallManager();
});

// Globale Funktion für die Schließen-Buttons in base.html
window.dismissInstallBanner = function() {
  if (window.pwaInstallManager) {
    window.pwaInstallManager.hideAllInstallUIs();
  } else {
    const mainBanner = document.getElementById('app-install-banner');
    const miniBanner = document.getElementById('app-install-mini-banner');
    if (mainBanner) mainBanner.classList.add('d-none');
    if (miniBanner) miniBanner.classList.add('d-none');
  }
  localStorage.setItem('pwa-install-dismissed', Date.now());
};
