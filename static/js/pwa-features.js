// PWA-spezifische Features für bessere Native App Erfahrung

class PWAFeatures {
    constructor() {
        this.isPWA = this.checkPWAMode();
        this.init();
    }

    checkPWAMode() {
        return window.matchMedia('(display-mode: standalone)').matches || 
               window.navigator.standalone === true;
    }

    init() {
        if (this.isPWA) {
            this.enablePWAFeatures();
            this.setupAppBadge();
            this.setupScreenOrientation();
            this.setupStatusBarColor();
            this.enableVibration();
        }
    }

    enablePWAFeatures() {
        // Verstecke Browser-spezifische Elemente
        document.body.classList.add('pwa-mode');
        
        // PWA-Status wird nicht mehr angezeigt
    }

    // App Badge API (experimentell)
    setupAppBadge() {
        if ('setAppBadge' in navigator) {
            // Zeige Badge bei neuen Benachrichtigungen
            this.updateAppBadge(0);
        }
    }

    updateAppBadge(count) {
        if ('setAppBadge' in navigator) {
            if (count > 0) {
                navigator.setAppBadge(count);
            } else {
                navigator.clearAppBadge();
            }
        }
    }

    // Screen Orientation (für bessere UX)
    setupScreenOrientation() {
        if ('screen' in window && 'orientation' in window.screen) {
            // Für Tablets: Erlaube Rotation, für Phones: Portrait bevorzugen
            const isTablet = window.innerWidth > 768;
            if (!isTablet) {
                try {
                    screen.orientation.lock('portrait').catch(() => {
                        // Fehlschlag ignorieren, nicht alle Geräte unterstützen das
                    });
                } catch (e) {
                    // API nicht verfügbar
                }
            }
        }
    }

    // Status Bar Styling (iOS Safari)
    setupStatusBarColor() {
        const metaThemeColor = document.querySelector('meta[name=theme-color]');
        if (metaThemeColor) {
            // Dynamische Theme-Farbe basierend auf Tageszeit
            const hour = new Date().getHours();
            const isDark = hour < 7 || hour > 19;
            metaThemeColor.setAttribute('content', isDark ? '#1a1a1a' : '#212529');
        }
    }

    // Haptisches Feedback
    enableVibration() {
        // Füge Vibration zu wichtigen Buttons hinzu
        document.addEventListener('click', (e) => {
            if (e.target.matches('.btn-primary, .btn-success, .btn-danger')) {
                this.vibrate([10]);
            }
        });
    }

    vibrate(pattern) {
        if ('vibrate' in navigator) {
            navigator.vibrate(pattern);
        }
    }

    // Wake Lock (Bildschirm aktiv halten)
    async requestWakeLock() {
        if ('wakeLock' in navigator) {
            try {
                const wakeLock = await navigator.wakeLock.request('screen');
                return wakeLock;
            } catch (error) {
                console.log('Wake lock failed:', error);
                return null;
            }
        }
        return null;
    }
}

// Initialize PWA Features
document.addEventListener('DOMContentLoaded', () => {
    // PWA Features temporär deaktiviert
    // window.pwaFeatures = new PWAFeatures();
});

// Export für andere Module
window.PWAFeatures = PWAFeatures;
