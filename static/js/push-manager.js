// CSRF Helper
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}
async function initializePushNotifications(viewedPlayerId) {
    // Version: 2025-01-24 - Performance Optimierungen für Multi-Device
    
    const pushContainer = document.getElementById('push-notification-container');
    const unsubscribeArea = document.getElementById('unsubscribe-area');
    
    // Wenn Container nicht existieren, abbrechen
    if (!pushContainer || !unsubscribeArea) {
        return;
    }

    // 1. Browser-Support prüfen
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        pushContainer.style.display = 'none'; // Push nicht unterstützt -> Container ausblenden
        return;
    }

    // 2. Session-Cache prüfen - verhindert wiederholte API-Calls
    const cacheKey = `push_state_${viewedPlayerId}`;
    const cachedState = sessionStorage.getItem(cacheKey);
    if (cachedState) {
        try {
            const state = JSON.parse(cachedState);
            // Cache nur 2 Minuten gültig
            if (Date.now() - state.timestamp < 120000) {
                applyPushUIState(state, viewedPlayerId, pushContainer, unsubscribeArea);
                return;
            }
        } catch(e) { /* Cache ignorieren */ }
    }

    let registration;
    try {
        // Zuerst prüfen, ob bereits eine Registration existiert
        registration = await navigator.serviceWorker.getRegistration();
        
        if (!registration) {
            registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
        }

        // Wenn wir hier sind, haben wir ein Registration-Objekt.
        // Wir müssen sicherstellen, dass es auch "active" ist.
        
        if (!registration.active) {
             // Warten auf Aktivierung - kürzerer Timeout
            const swReadyPromise = navigator.serviceWorker.ready;
            const timeoutPromise = new Promise((_, reject) => 
                setTimeout(() => reject(new Error('SW Timeout')), 3000)
            );
            await Promise.race([swReadyPromise, timeoutPromise]);
            registration = await navigator.serviceWorker.ready;
        }

    } catch (err) {
        // Detailliertere Fehlermeldung für Debugging
        pushContainer.innerHTML = `<div class="alert alert-warning small">Push-Service Fehler: ${err.message}<br>Bitte Seite neu laden.</div>`;
        return;
    }

    try {
        const deviceSub = await registration.pushManager.getSubscription();

        if (!deviceSub) {
            // Fall 1: Das Gerät hat KEIN Abo. Biete Anmeldung für den aktuellen Spieler an.
            
            // NEU: Prüfen ob wir eigentlich eines haben sollten (laut Cache)
            const cachedEndpoint = localStorage.getItem('cached_push_endpoint');
            if (cachedEndpoint) {
                // Auf dem Server aufräumen
                fetch('/api/unsubscribe', { headers: { 'X-CSRFToken': getCsrfToken() },
                    method: 'POST',
                    headers: {
            "X-CSRFToken": getCsrfToken(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: cachedEndpoint })
                }).then(() => {
                    localStorage.removeItem('cached_push_endpoint');
                    if (typeof showToast === 'function') {
                        showToast('Dein Push-Abo war nicht mehr aktiv und wurde zurückgesetzt. Bitte neu aktivieren.', 'warning');
                    }
                }).catch(() => {});
            }
            
            unsubscribeArea.style.display = 'none';
            pushContainer.innerHTML = `<button id="subscribe-button" class="btn btn-primary">🌟 Ich bin dieser Spieler!</button>`;
            document.getElementById('subscribe-button').addEventListener('click', () => subscribeDeviceForPlayer(viewedPlayerId, registration));
            
            // Zusatz-Check: Wenn wir lokal KEIN Abo haben, aber der Server noch welche hat.
            // Strategie: Wenn der Server genau EINES hat, gehen wir davon aus, dass es unser altes (ungültiges) ist
            // (z.B. nach Neuinstallation) und löschen es, damit der User sauber neu starten kann.
            // FIX: Dies darf nicht automatisch passieren, nur weil ein User (oder Fremder) die Seite ohne Push besucht!
            // Sonst löschen wir Abos von anderen Geräten.
            // attemptAutoCleanup(viewedPlayerId); // <--- DEAKTIVIERT WEGEN "LÖSCHT FREMDE ABOS"-BUG

        } else {
            // Fall 2: Das Gerät HAT ein Abo. Finde heraus, für wen es auf dem Server registriert ist.
            // Kürzerer Timeout für schnellere Reaktion
            const fetchPromise = fetch('/api/get-player-for-subscription', { headers: { 'X-CSRFToken': getCsrfToken() },
                method: 'POST',
                headers: {
            "X-CSRFToken": getCsrfToken(), 'Content-Type': 'application/json' },
                body: JSON.stringify(deviceSub.toJSON())
            });
            const apiTimeout = new Promise((_, reject) => setTimeout(() => reject(new Error('API Timeout')), 3000));
            
            const response = await Promise.race([fetchPromise, apiTimeout]);
            
            if (!response.ok) throw new Error('API Error');
            
            const data = await response.json();
            const subscribedPlayerId = data.player_id;
            const subscribedPlayerName = data.player_name;

            if (subscribedPlayerId === viewedPlayerId) {
                // Szenario A: Das Gerät ist für den aktuell angezeigten Spieler angemeldet.
                pushContainer.style.display = 'none';
                unsubscribeArea.innerHTML = `<button id="unsubscribe-button" class="btn btn-sm btn-outline-danger">Ich bin nicht dieser Spieler</button>`;
                document.getElementById('unsubscribe-button').addEventListener('click', () => unsubscribeDevice(deviceSub));
                // Cache speichern
                savePushStateCache(cacheKey, { type: 'subscribed_self' });
            } else if (subscribedPlayerId) {
                // Szenario B: Das Gerät ist für einen ANDEREN Spieler angemeldet.
                pushContainer.style.display = 'none';
                unsubscribeArea.innerHTML = `<p class="text-muted">Auf diesem Gerät sind bereits Benachrichtigungen für <strong>${subscribedPlayerName}</strong> aktiviert.</p>`;
                // Cache speichern
                savePushStateCache(cacheKey, { type: 'subscribed_other', playerName: subscribedPlayerName });
            } else {
                // Szenario C: Das Gerät hat ein Abo, aber der Server kennt es nicht. Biete Neuregistrierung an.
                unsubscribeArea.style.display = 'none';
                pushContainer.innerHTML = `<button id="subscribe-button" class="btn btn-primary">🌟 Ich bin dieser Spieler!</button>`;
                document.getElementById('subscribe-button').addEventListener('click', () => subscribeDeviceForPlayer(viewedPlayerId, registration, deviceSub));
            }
        }
    } catch (err) {
        console.error('Fehler im Push-Prozess:', err);
        pushContainer.innerHTML = `<p class="text-muted small">Status konnte nicht geladen werden.</p>`;
    }
}

// Hilfsfunktion: Cache für Push-Status speichern
function savePushStateCache(key, state) {
    try {
        state.timestamp = Date.now();
        sessionStorage.setItem(key, JSON.stringify(state));
    } catch(e) { /* Ignore storage errors */ }
}

// Hilfsfunktion: Cached Push-Status anwenden
function applyPushUIState(state, viewedPlayerId, pushContainer, unsubscribeArea) {
    if (state.type === 'subscribed_self') {
        pushContainer.style.display = 'none';
        unsubscribeArea.innerHTML = `<button id="unsubscribe-button" class="btn btn-sm btn-outline-danger">Ich bin nicht dieser Spieler</button>`;
        // Event-Listener muss bei gecachtem State neu hinzugefügt werden
        document.getElementById('unsubscribe-button')?.addEventListener('click', async () => {
            const reg = await navigator.serviceWorker.getRegistration();
            const sub = await reg?.pushManager?.getSubscription();
            if (sub) unsubscribeDevice(sub);
        });
    } else if (state.type === 'subscribed_other') {
        pushContainer.style.display = 'none';
        unsubscribeArea.innerHTML = `<p class="text-muted">Auf diesem Gerät sind bereits Benachrichtigungen für <strong>${state.playerName}</strong> aktiviert.</p>`;
    } else if (state.type === 'not_subscribed') {
        unsubscribeArea.style.display = 'none';
        pushContainer.innerHTML = `<button id="subscribe-button" class="btn btn-primary">🌟 Ich bin dieser Spieler!</button>`;
        document.getElementById('subscribe-button')?.addEventListener('click', async () => {
            const reg = await navigator.serviceWorker.getRegistration();
            if (reg) subscribeDeviceForPlayer(viewedPlayerId, reg);
        });
    }
}

// Hilfsfunktion: Versucht verwaiste Abos auf dem Server automatisch zu bereinigen
async function attemptAutoCleanup(playerId) {
    try {
        const response = await fetch(`/api/cleanup-orphaned-subs/${playerId}`, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } });
        
        if(response.ok) {
            const data = await response.json();
            
            if(data.status === 'deleted') {
                // Server hat alte Abos gelöscht
                const container = document.getElementById('push-notification-container');
                if(container) {
                     const alertDiv = document.createElement('div');
                     alertDiv.className = 'alert alert-warning small mt-2';
                     // Add a timestamp so we know it's fresh
                     const time = new Date().toLocaleTimeString();
                     alertDiv.innerHTML = `<strong>Hinweis (${time}):</strong> Alte Benachrichtigungs-Einstellungen wurden zurückgesetzt.<br>Bitte aktiviere die Push-Nachrichten jetzt erneut.`;
                     container.appendChild(alertDiv);
                }
            } else if (data.status === 'multiple_active') {
                // Es gibt mehrere Abos -> wir trauen uns nicht zu löschen, warnen aber
                const container = document.getElementById('push-notification-container');
                if(container) {
                     const alertDiv = document.createElement('div');
                     alertDiv.className = 'alert alert-info small mt-2';
                     alertDiv.innerHTML = 'Hinweis: Es existieren noch aktive Abos auf anderen Geräten.';
                     container.appendChild(alertDiv);
                }
            }
        }
    } catch(e) { console.warn('Cleanup fehlgeschlagen', e); }
}

async function subscribeDeviceForPlayer(playerId, registration, existingSub = null, silent = false) {
    const button = document.getElementById('subscribe-button');
    if (button && !silent) {
        button.disabled = true;
        button.textContent = 'Wird verarbeitet...';
    }

    try {
        const subscription = existingSub || await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: await getVapidKey()
        });
        
        await fetch(`/api/subscribe/player/${playerId}`, { headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
            method: 'POST',
            body: JSON.stringify(subscription),
            headers: {
            "X-CSRFToken": getCsrfToken(), 'Content-Type': 'application/json' }
        });
        
        try {
            // Merke, dass dieser Spieler sich gerade angemeldet hat
            localStorage.setItem('justSubscribedPlayerId', String(playerId));
            localStorage.setItem('cached_push_endpoint', subscription.endpoint);
        } catch (e) { console.warn('localStorage nicht verfügbar:', e); }

        // UI Feedback nur wenn Container vorhanden (sonst Silent Mode)
        const container = document.getElementById('push-notification-container');
        if (container && !silent) {
            container.innerHTML = `<p class="text-success">Erfolgreich angemeldet. Weiterleitung zur Übersicht...</p>`;
            setTimeout(() => { window.location.href = '/'; }, 800);
        }
        // Silent Mode: Keine UI-Rückmeldung

    } catch (err) {
        console.error('Fehler bei der Anmeldung:', err);
        if(button && !silent) {
            button.disabled = false;
            button.textContent = 'Erneut versuchen';
        }
        if (!silent) throw err; // Fehler weiterwerfen für Aufrufer
    }
}

async function unsubscribeDevice(subscription) {
    const button = document.getElementById('unsubscribe-button');
    if(button) {
        button.disabled = true;
        button.textContent = 'Wird abgemeldet...';
    }

    try {
        // Cache bereinigen
        localStorage.removeItem('cached_push_endpoint');
        
        // Zuerst beim Server abmelden
        await fetch('/api/unsubscribe', { headers: { 'X-CSRFToken': getCsrfToken() },
            method: 'POST',
            body: JSON.stringify(subscription.toJSON()),
            headers: {
            "X-CSRFToken": getCsrfToken(), 'Content-Type': 'application/json' }
        });
        // Dann im Browser
        await subscription.unsubscribe();
        document.getElementById('unsubscribe-area').innerHTML = `<p class="text-success">Erfolgreich abgemeldet. Bitte Seite neu laden.</p>`;
    } catch (err) {
        console.error('Fehler bei der Abmeldung:', err);
        if(button){
            button.disabled = false;
            button.textContent = 'Erneut versuchen';
        }
    }
}

async function getVapidKey() {
    const response = await fetch('/api/vapid-public-key');
    const data = await response.json();
    const padding = '='.repeat((4 - data.publicKey.length % 4) % 4);
    const base64 = (data.publicKey + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}
