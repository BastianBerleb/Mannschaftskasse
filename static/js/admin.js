// CSRF Helper
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}
// --- Clipboard-Funktionen für Schulden Cockpit ---

function showToast(message, category = 'success') {
    const toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) { console.error('Toast container nicht gefunden!'); return; }
    const toastId = 'toast-' + Date.now();
    const toastBg = category === 'success' ? 'text-bg-success' : 'text-bg-danger';
    const toastIcon = category === 'success' ? '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-check-circle-fill" viewBox="0 0 16 16"><path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zm-3.97-3.03a.75.75 0 0 0-1.08.022L7.477 9.417 5.384 7.323a.75.75 0 0 0-1.06 1.06L6.97 11.03a.75.75 0 0 0 1.079-.02l3.992-4.99a.75.75 0 0 0-.01-1.05z"/></svg>' : '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-exclamation-triangle-fill" viewBox="0 0 16 16"><path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/></svg>';
    const toastHtml = `<div id="${toastId}" class="toast align-items-center ${toastBg} border-0" role="alert" aria-live="assertive" aria-atomic="true"><div class="d-flex"><div class="toast-body d-flex align-items-center"><span class="me-2">${toastIcon}</span><span>${message}</span></div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div></div>`;
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    const toast = new bootstrap.Toast(document.getElementById(toastId), { delay: 3500 });
    toast.show();
    document.getElementById(toastId).addEventListener('hidden.bs.toast', (e) => e.target.remove());
}

// NEW: Magic Link Generator
function generateMagicLink(playerId) {
    if (!confirm('Soll ein neuer Zugangslink für diesen Spieler generiert werden? (Der alte Link wird ungültig)')) return;

    fetch(`/generate_magic_link/${playerId}`, {
        method: 'POST',
        headers: {
            "X-CSRFToken": getCsrfToken(),
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            showToast(data.error, 'danger');
        } else {
            // Link in Zwischenablage kopieren
            navigator.clipboard.writeText(data.link).then(function() {
                showToast(data.message + ' Link kopiert!', 'success');
            }, function(err) {
                prompt("Link erstellt! Bitte manuell kopieren:", data.link);
            });
        }
    })
    .catch(error => {
        showToast('Fehler beim Generieren des Links', 'danger');
        console.error(error);
    });
}

// NEW: Guest Link Generator
function generateGuestLink() {
    if (!confirm('Soll ein neuer Gast-Link generiert werden? (Der alte Link wird ungültig)')) return;

    fetch(`/generate_guest_link`, {
        method: 'POST',
        headers: {
            "X-CSRFToken": getCsrfToken(),
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            showToast(data.error, 'danger');
        } else {
            const input = document.getElementById('guest-link-output');
            input.value = data.link;
            showToast(data.message, 'success');
        }
    })
    .catch(error => {
        showToast('Fehler beim Generieren des Gast-Links', 'danger');
        console.error(error);
    });
}

function copyGuestLink() {
    const input = document.getElementById('guest-link-output');
    if (!input.value) return;
    
    input.select();
    input.setSelectionRange(0, 99999); // Mobile
    navigator.clipboard.writeText(input.value).then(function() {
        showToast('Link kopiert!', 'success');
    }, function(err) {
        alert("Kopieren fehlgeschlagen. Bitte manuell auswählen.");
    });
}

// Global function: delegate to the existing '#copy-group-msg-btn' click handler
// so any button that calls copyGroupMessage() behaves exactly like the working
// "Gruppenerinnerung kopieren" button defined in the template.
function copyGroupMessage() {
    const textarea = document.getElementById('whatsapp-group-message-content') || document.getElementById('whatsapp-group-message');
    const copyBtn = document.getElementById('copy-group-msg-btn');
    if (!textarea) {
        if (typeof showToast === 'function') showToast('Keine Nachricht gefunden.', 'danger');
        return;
    }
    // Versuche moderne Clipboard-API
    navigator.clipboard.writeText(textarea.value).then(function() {
        if (copyBtn) {
            const originalText = copyBtn.innerHTML;
            copyBtn.innerHTML = '✅ Kopiert!';
            copyBtn.classList.remove('btn-success');
            copyBtn.classList.add('btn-secondary');
            setTimeout(function() {
                copyBtn.innerHTML = originalText;
                copyBtn.classList.remove('btn-secondary');
                copyBtn.classList.add('btn-success');
            }, 2000);
        } else if (typeof showToast === 'function') {
            showToast('Text wurde kopiert!', 'success');
        }
    }).catch(function(err) {
        // Fallback: select + execCommand
        try {
            textarea.style.display = 'block';
            textarea.select();
            document.execCommand('copy');
            textarea.style.display = 'none';
            if (copyBtn) {
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = '✅ Kopiert!';
                copyBtn.classList.remove('btn-success');
                copyBtn.classList.add('btn-secondary');
                setTimeout(function() {
                    copyBtn.innerHTML = originalText;
                    copyBtn.classList.remove('btn-secondary');
                    copyBtn.classList.add('btn-success');
                }, 2000);
            } else if (typeof showToast === 'function') {
                showToast('Text wurde kopiert!', 'success');
            }
        } catch (e) {
            if (typeof showToast === 'function') showToast('Kopieren nicht möglich!', 'danger');
        }
    });
}

// Make available to inline onclick handlers
window.copyGroupMessage = copyGroupMessage;

// Global function to copy the generated debt image into the clipboard
async function copyDebtImage() {
    const img = document.getElementById('debt-overview-image');
    if (!img) {
        if (typeof showToast === 'function') showToast('Kein Bild gefunden.', 'danger');
        return;
    }
    try {
        const response = await fetch(img.src);
        const blob = await response.blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        if (typeof showToast === 'function') showToast('Bild wurde kopiert!', 'success');
    } catch (err) {
        if (typeof showToast === 'function') showToast('Bild kopieren nicht möglich! (Browser/HTTPS nötig)', 'danger');
    }
}
window.copyDebtImage = copyDebtImage;

document.addEventListener('DOMContentLoaded', function () {
    // Funktion für Text kopieren (wie Gruppenerinnerung)
    document.querySelectorAll('button[onclick="copyGroupMessage()"], #copy-group-msg-btn').forEach(btn => {
        btn.addEventListener('click', async function () {
            // Verwende die versteckte Textarea, die in der Template steht
            const textarea = document.getElementById('whatsapp-group-message-content') || document.getElementById('whatsapp-group-message');
            if (!textarea) return;
            try {
                // Moderne API - funktioniert auch wenn das Textarea versteckt ist
                await navigator.clipboard.writeText(textarea.value);
                if (typeof showToast === 'function') showToast('Text wurde kopiert!', 'success');
            } catch (err) {
                // Fallback: falls Clipboard API nicht verfügbar, versuche select + execCommand
                try {
                    textarea.style.display = 'block';
                    textarea.select();
                    document.execCommand('copy');
                    textarea.style.display = 'none';
                    if (typeof showToast === 'function') showToast('Text wurde kopiert!', 'success');
                } catch (e) {
                    if (typeof showToast === 'function') showToast('Kopieren nicht möglich!', 'danger');
                }
            }
        });
    });
    // Funktion für Bild kopieren: direkt in die Zwischenablage
    document.querySelectorAll('button[onclick="copyDebtImage()"]').forEach(btn => {
        btn.addEventListener('click', async function () {
            const img = document.getElementById('debt-overview-image');
            if (!img) return;
            try {
                const response = await fetch(img.src);
                const blob = await response.blob();
                await navigator.clipboard.write([
                    new ClipboardItem({ [blob.type]: blob })
                ]);
                if (typeof showToast === 'function') showToast('Bild wurde kopiert!', 'success');
            } catch (err) {
                if (typeof showToast === 'function') showToast('Bild kopieren nicht möglich! (Browser/HTTPS nötig)', 'danger');
            }
        });
    });
});
console.log("admin.js wurde geladen und wird jetzt ausgeführt.");

document.addEventListener('DOMContentLoaded', function () {
    
    console.log("DOMContentLoaded event wurde ausgelöst. Event-Listener werden jetzt gebunden.");

    // --- TAB PERSISTENCE START ---
    // Speichert den zuletzt aktiven Tab, damit er nach dem Neuladen (z.B. nach Speichern) wieder offen ist.
    const tabLinks = document.querySelectorAll('button[data-bs-toggle="tab"]');
    tabLinks.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function (event) {
            localStorage.setItem('adminActiveTab', event.target.id);
        });
    });

    const activeTabId = localStorage.getItem('adminActiveTab');
    if (activeTabId) {
        const triggerEl = document.getElementById(activeTabId);
        // Verwende getOrCreateInstance für Robustheit und prüfe Existenz
        if (triggerEl && !triggerEl.classList.contains('active')) {
            const tabInstance = bootstrap.Tab.getOrCreateInstance(triggerEl);
            tabInstance.show();
        }
    }

    // --- TAB PERSISTENCE END ---

	function handleDomUpdate(data) {
		if (!data) return;
		const placeholders = '.text-muted, #no-fines-in-catalog, #no-inactive-players, #no-kistl-debtors, #no-transactions-row';

		if (data.removeElement) {
			const el = document.querySelector(data.removeElement);
			if (el) { 
				el.style.transition = 'opacity 0.4s'; 
				el.style.opacity = '0'; 
				setTimeout(() => el.remove(), 400); 
			}
		}
    
		if (data.updateElement) {
			const elToUpdate = document.querySelector(data.updateElement.selector);
			if (elToUpdate) {
                if (data.updateElement.outerHTML) {
                    elToUpdate.outerHTML = data.updateElement.html;
                } else if (data.updateElement.html) {
                    elToUpdate.innerHTML = data.updateElement.html;
                } else {
				    const textSpan = elToUpdate.querySelector('span:first-child');
				    if (textSpan) {
					    const playerName = textSpan.textContent.split('(')[0].trim();
					    textSpan.textContent = `${playerName} (${data.updateElement.remaining} Kistl offen)`;
				    }
                }
			}
		}

		if (data.html && data.appendTo) {
			const container = document.querySelector(data.appendTo);
			container?.querySelector(placeholders)?.remove();
			if (container) container.insertAdjacentHTML('beforeend', data.html);
		}
		if (data.html && data.prependTo) {
			const container = document.querySelector(data.prependTo);
			container?.querySelector(placeholders)?.remove();
			if (container) container.insertAdjacentHTML('afterbegin', data.html);
		}
		if (data.moveElement) {
			const sourceEl = document.querySelector(data.moveElement.source);
			const destContainer = document.querySelector(data.moveElement.destination);
			destContainer?.querySelector(placeholders)?.remove();
			if (sourceEl && destContainer) { 
				sourceEl.remove(); 
				destContainer.insertAdjacentHTML('beforeend', data.moveElement.html); 
			}
		}
	}

    async function doAjaxSubmit(form, submitButton) {
        const confirmMessage = submitButton?.dataset.confirm;
        if (confirmMessage && !confirm(confirmMessage)) return;

        const formData = new FormData(form);
        const url = form.action;
        const method = form.method;
        const originalButtonText = submitButton.innerHTML;
        submitButton.disabled = true;
        submitButton.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;

        try {
            const response = await fetch(url, { method, body: formData, headers: {
            "X-CSRFToken": getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' } });
            if (!response.ok) throw new Error(`HTTP error ${response.status}`);
            
            const data = await response.json();

            if (data.success) {
                
                // Explicit Reload Command from Server
                if (data.reload) {
                    showToast(data.message + " (Seite wird neu geladen...)", 'success');
                    setTimeout(() => window.location.reload(), 1000);
                    return;
                }

                // FORCE RELOAD for specific booking forms
                if (/add-transaction|add-custom-fine|add-payment|add-game-fee/.test(form.action)) {
                     showToast(data.message + " (Seite wird neu geladen...)", 'success');
                     setTimeout(() => {
                         // Redirect to Log Tab
                         // We assume the URLSearchParams (season) are already in window.location.search
                         // We append #nav-log-tab to make sure it opens the log
                         const baseUrl = window.location.pathname + window.location.search;
                         window.location.href = baseUrl + "#nav-log-tab";
                         window.location.reload(); 
                     }, 1000);
                     return;
                }

                showToast(data.message, 'success');
                handleDomUpdate(data);
                
                // RELOAD LOG after deleting a transaction or log entry so the log reflects the new state
                const isLogDelete = /delete-transaction|delete-kistl|delete-team-expense|settle-kistl/.test(form.action);
                if (isLogDelete) {
                    setTimeout(() => window.location.reload(), 800);
                    return;
                }
                
                const isEditOrActionForm = /edit|deactivate|reactivate|delete/.test(form.action);
                if (!isEditOrActionForm) {
                   form.reset();
                }
            } else {
                showToast(data.message || 'Ein unbekannter Fehler.', 'danger');
            }
        } catch (error) {
            console.error('AJAX Form Error:', error);
            showToast('Netzwerk- oder Serverfehler.', 'danger');
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalButtonText;
            }
        }
    }

	document.body.addEventListener('submit', function(event) {
		const form = event.target;
		if (form.matches('.ajax-form')) {
			event.preventDefault();
			const submitButton = event.submitter || form.querySelector('[type="submit"]');
			doAjaxSubmit(form, submitButton);
		}
	});

    document.body.addEventListener('click', function(event) {
        const button = event.target.closest('.manual-ajax-trigger');
        if (button) {
            event.preventDefault();
            const formId = button.dataset.formId;
            const form = document.getElementById(formId);

            if (form) {
                doAjaxSubmit(form, button);
            } else {
                console.error(`Fehler: Das zugehörige Formular mit der ID '${formId}' wurde nicht gefunden!`);
                showToast(`Fehler: Formular '${formId}' nicht gefunden.`, 'danger');
            }
        }
    });

    // --- Image Upload & Cropper Logic ---
    let cropperState = {
        img: null,
        playerId: null,
        targetInput: null, // Referenz auf das urspr. Input-Element
        zoom: 1,
        posX: 0,
        posY: 0,
        origWidth: 0,
        origHeight: 0,
        isDragging: false,
        startX: 0,
        startY: 0
    };

    const cropperModalEl = document.getElementById('cropperModal');
    const cropperModal = cropperModalEl ? new bootstrap.Modal(cropperModalEl) : null;
    const cropperImage = document.getElementById('cropperImage');
    const cropperZoom = document.getElementById('cropperZoom');
    const cropperSaveBtn = document.getElementById('cropperSaveBtn');

    // Helper: Update CSS transform based on state
    function updateCropperTransform() {
        if(!cropperImage) return;
        cropperImage.style.transform = `translate(${cropperState.posX}px, ${cropperState.posY}px) scale(${cropperState.zoom})`;
    }

    // 1. File Input Change -> Open Modal
    document.body.addEventListener('change', function(e) {
        if (e.target.matches('.image-upload-input')) {
            const input = e.target;
            const file = input.files[0];
            if (!file) return;

            // Reset input value damit man das gleiche Bild nochmal wählen kann wenn man abbricht
            // Aber Vorsicht: wir brauchen die File-Referenz noch. 
            // Besser: Wir lesen es ein, und resetten den Input erst bei "Abbruch" oder "Erfolg".
            
            const reader = new FileReader();
            reader.onload = function(evt) {
                if(!cropperModal) return; // Sollte da sein
                
                cropperState.playerId = input.dataset.playerId;
                cropperState.targetInput = input;
                cropperState.img = new Image();
                cropperState.img.onload = function() {
                    // Init State
                    cropperState.origWidth = this.width;
                    cropperState.origHeight = this.height;
                    cropperState.zoom = 1;
                    
                    // Center image initially in 300x300 container
                    // Container w=300, h=300. 
                    // Wenn Bild 600x400: wir skalieren es so, dass die *kleinere* Seite 300px ist, damit es "füllend" startet.
                    const ratio = Math.max(300 / this.width, 300 / this.height);
                    cropperState.zoom = ratio;
                    
                    // Zentrieren
                    // Bildgröße visual:  w*zoom, h*zoom
                    // Container center: 150, 150
                    // Bild center relative to top-left at 0,0: (w*zoom)/2 ...
                    // Wir wollen dass Bild-Mitte auf Container-Mitte liegt.
                    // Start Position: (300 - w)/2 ist falsch weil Zoom über Transform-Origin 0 0 läuft
                    
                    // Einfacher: Wir setzen pos X/Y so, dass es mittig ist.
                    // Formel: (ContainerSize - (ImgSize * Zoom)) / 2
                    cropperState.posX = (300 - ckVal(this.width * cropperState.zoom)) / 2;
                    cropperState.posY = (300 - ckVal(this.height * cropperState.zoom)) / 2;
                    
                    // Slider Value update
                    if(cropperZoom) {
                        cropperZoom.value = cropperState.zoom;
                        // Range Slider sinnvoller einstellen
                        cropperZoom.min = ratio * 0.5; 
                        cropperZoom.max = ratio * 3.0;
                    }

                    // Set Source & Show
                    cropperImage.src = evt.target.result;
                    updateCropperTransform();
                    cropperModal.show();
                };
                cropperState.img.src = evt.target.result;
            };
            reader.readAsDataURL(file);
        }
    });

    function ckVal(v) { return v || 0; }

    // 2. Cropper Interactions (Drag & Zoom)
    if(cropperImage && cropperZoom) {
        
        // Zoom Slider
        cropperZoom.addEventListener('input', function() {
            const oldZoom = cropperState.zoom;
            const newZoom = parseFloat(this.value);
            
            // Optional: Zoom ins Zentrum (Schwieriger). 
            // Simple: Zoom ändert Größe, User muss nachschieben.
            // Behalten wir zentrum nah:
            // Shift = (DiffSize) / 2
            const w = cropperState.origWidth;
            const h = cropperState.origHeight;
            
            const oldW = w * oldZoom;
            const newW = w * newZoom;
            
            const diffX = (oldW - newW) / 2;
            const diffY = ((h * oldZoom) - (h * newZoom)) / 2;
            
            cropperState.posX += diffX;
            cropperState.posY += diffY;
            cropperState.zoom = newZoom;
            
            updateCropperTransform();
        });

        // Mouse / Touch Dragging
        const container = cropperImage.parentElement;
        
        const startDrag = (clientX, clientY) => {
            cropperState.isDragging = true;
            cropperState.startX = clientX - cropperState.posX;
            cropperState.startY = clientY - cropperState.posY;
            container.style.cursor = 'grabbing';
            cropperImage.style.cursor = 'grabbing';
        };
        
        const moveDrag = (clientX, clientY) => {
            if(!cropperState.isDragging) return;
            event.preventDefault(); // Prevent scrolling on touch
            cropperState.posX = clientX - cropperState.startX;
            cropperState.posY = clientY - cropperState.startY;
            updateCropperTransform();
        };
        
        const endDrag = () => {
            cropperState.isDragging = false;
            container.style.cursor = 'default';
            cropperImage.style.cursor = 'move';
        };

        // Events Mouse
        container.addEventListener('mousedown', e => startDrag(e.clientX, e.clientY));
        document.addEventListener('mousemove', e => { if(cropperState.isDragging) moveDrag(e.clientX, e.clientY); });
        document.addEventListener('mouseup', endDrag);

        // Events Touch
        container.addEventListener('touchstart', e => {
            if(e.touches.length === 1) startDrag(e.touches[0].clientX, e.touches[0].clientY);
        }, {passive: false});
        document.addEventListener('touchmove', e => {
             if(cropperState.isDragging && e.touches.length === 1) moveDrag(e.touches[0].clientX, e.touches[0].clientY);
        }, {passive: false});
        document.addEventListener('touchend', endDrag);
    }

    // 3. Save -> Canvas -> Blob -> Upload
    if(cropperSaveBtn) {
        cropperSaveBtn.addEventListener('click', async function() {
            // Loading State
            const btnHtml = cropperSaveBtn.innerHTML;
            cropperSaveBtn.disabled = true;
            cropperSaveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Speichern...';

            try {
                // Canvas erstellen
                const canvas = document.createElement('canvas');
                canvas.width = 300;
                canvas.height = 300;
                const ctx = canvas.getContext('2d');
                
                // Hintergrund weiß (für transparente PNGs die zu JPG werden)
                ctx.fillStyle = "#FFFFFF";
                ctx.fillRect(0,0, 300, 300);

                // Bild zeichnen
                // drawImage(img, dx, dy, dWidth, dHeight)
                // dx, dy sind die Positionen auf dem Canvas. Das entspricht unserem posX/posY.
                // dWidth, dHeight sind die skalierten Dimensionen.
                ctx.drawImage(
                    cropperState.img, 
                    cropperState.posX, 
                    cropperState.posY, 
                    cropperState.origWidth * cropperState.zoom, 
                    cropperState.origHeight * cropperState.zoom
                );

                // Blob erzeugen (High Quality JPG)
                canvas.toBlob(async function(blob) {
                    if(!blob) return;
                    
                    const formData = new FormData();
                    // Dateiname generieren
                    formData.append('image', blob, "avatar_upload.jpg"); 

                    // Upload via fetch (wie vorher)
                    const playerId = cropperState.playerId;
                    
                    try {
                        const response = await fetch(`/admin/player/upload-image/${playerId}`, {
                            headers: { 'X-CSRFToken': getCsrfToken() }, 
                            method: 'POST',
                            body: formData,
                            headers: {
            "X-CSRFToken": getCsrfToken(),'X-Requested-With': 'XMLHttpRequest'}
                        });
                        const data = await response.json();

                        if (data.success) {
                            showToast(data.message, 'success');
                            cropperModal.hide();
                            
                            // UI Update beim Spieler
                            if(cropperState.targetInput) {
                                const wrapper = cropperState.targetInput.closest('.position-relative');
                                const oldEl = wrapper.querySelector('img, div.bg-light');
                                if(oldEl) oldEl.remove();
                                
                                const newImg = document.createElement('img');
                                newImg.src = data.image_url + '?t=' + new Date().getTime();
                                newImg.className = "rounded-circle w-100 h-100 object-fit-cover border";
                                newImg.alt = "Profilbild";
                                wrapper.insertBefore(newImg, wrapper.firstChild);
                                
                                // Input resetten
                                cropperState.targetInput.value = '';
                            }
                        } else {
                            showToast(data.message, 'danger');
                        }

                    } catch(err) {
                        console.error(err);
                        showToast('Fehler beim Upload.', 'danger');
                    } finally {
                        cropperSaveBtn.disabled = false;
                        cropperSaveBtn.innerHTML = btnHtml;
                    }
                }, 'image/jpeg', 0.95);

            } catch(e) {
                console.error(e);
                showToast('Fehler bei der Bildverarbeitung.', 'danger');
                cropperSaveBtn.disabled = false;
                cropperSaveBtn.innerHTML = btnHtml;
            }
        });
    }

    // --- KORREKTE PLATZIERUNG: Listener für den Fupa-Refresh-Button ---
    const refreshFupaBtn = document.getElementById('refresh-fupa-btn');
    if (refreshFupaBtn) {
        refreshFupaBtn.addEventListener('click', async () => {
            const originalHtml = refreshFupaBtn.innerHTML;
            refreshFupaBtn.disabled = true;
            refreshFupaBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Lade...`;

            try {
                const response = await fetch('/admin/refresh-fupa', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    showToast(data.message, 'success');
                    setTimeout(() => {
                        // Cache-Busting Reload: Zeitstempel an URL hängen
                        const url = new URL(window.location.href);
                        url.searchParams.set('ts', Date.now());
						window.location.href = url.toString();
                    }, 1500);
                } else {
                    showToast(data.message || 'Ein Fehler ist aufgetreten.', 'danger');
                    refreshFupaBtn.disabled = false;
                    refreshFupaBtn.innerHTML = originalHtml;
                }
            } catch (error) {
                console.error('Fehler beim Fupa-Refresh:', error);
                showToast('Netzwerk- oder Serverfehler beim Aktualisieren.', 'danger');
                refreshFupaBtn.disabled = false;
                refreshFupaBtn.innerHTML = originalHtml;
            }
        });
    }
    
	const gameFeeForm = document.getElementById('game-fee-form');
    /* Listener für gameFeeForm entfernt, da Datums-Check jetzt logisch im Backend gelöst (Split 1./2. Mannschaft) */

    // --- LIVE COUNTER FÜR SPIELGEBÜHREN ---
    function updateGameFeeCounts() {
        const team1Count = document.querySelectorAll('input[name="team1_player_ids"]:checked').length;
        const team2Count = document.querySelectorAll('input[name="team2_player_ids"]:checked').length;
        
        const badge1 = document.getElementById('count-team1');
        const badge2 = document.getElementById('count-team2');
        
        if (badge1) badge1.textContent = `Team 1: ${team1Count}`;
        if (badge2) badge2.textContent = `Team 2: ${team2Count}`;
    }

    // Listener auf alle Checkboxen
    document.querySelectorAll('input[name="team1_player_ids"], input[name="team2_player_ids"]').forEach(cb => {
        cb.addEventListener('change', updateGameFeeCounts);
    });

    // Initialer Aufruf
    updateGameFeeCounts();
	
}); // << HIER ENDET DOMContentLoaded NUN KORREKT

// NEW: Mass Booking Checkbox Toggle
function toggleMassCheckboxes(checked) {
    document.querySelectorAll('input[name="player_ids"]').forEach(cb => {
        cb.checked = checked;
    });
}