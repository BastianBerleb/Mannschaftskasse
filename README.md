# ⚽ Mannschaftskasse TSV Alteglofsheim

Eine moderne, webbasierte Plattform zur Verwaltung der Mannschaftskasse des TSV Alteglofsheim. Diese Anwendung automatisiert die Buchung von Strafen, Spielgebühren und Guthaben und bietet ein intuitives Interface für Manager und Spieler.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![Flask](https://img.shields.io/badge/framework-Flask-lightgrey.svg)
![PWA](https://img.shields.io/badge/PWA-ready-green.svg)

## ✨ Features

*   **📱 Progressive Web App (PWA):** Installierbar auf Smartphones, offline-fähig und fühlt sich an wie eine native App.
*   **📊 Manager Dashboard:** Zentrale Verwaltung von Spielern, Strafkatalogen und Spieltagen.
*   **⚖️ Schulden & Guthaben:** Automatische Berechnung der Kontostände inklusive grafischer Auswertung.
*   **🔔 Benachrichtigungen:** Unterstützung für Push-Benachrichtigungen und WhatsApp-Integration (geplant/in Arbeit).
*   **🎂 Geburtstagskalender:** Übersicht über alle Geburtstage im Team.
*   **🛡️ Sicherheit:** Rollenbasierte Zugriffskontrolle (Mitarbeiter, Manager, Auditor), Passwort-Hashing und geschützte API-Endpunkte.
*   **☁️ Google Drive Backup:** Integrierte Datensicherung der SQLite-Datenbank direkt in die Cloud.

## 🛠️ Tech-Stack

*   **Backend:** Python 3.13+, Flask
*   **Datenbank:** SQLite (SQLAlchemy ORM)
*   **Frontend:** HTML5, CSS3 (Custom Premium Design & Bootstrap), JavaScript (ES6+)
*   **Visualisierung:** Chart.js
*   **Infrastruktur:** Google Cloud API (Drive Backup), Web Push Protocol (VAPID)

## 🚀 Installation & Setup

### Voraussetzungen
*   Python 3.13 oder höher
*   Pip (Python Package Manager)

### Schritt-für-Schritt Anleitung

1.  **Repository klonen:**
    ```bash
    git clone https://github.com/BastianBerleb/Mannschaftskasse.git
    cd Mannschaftskasse
    ```

2.  **Virtuelle Umgebung erstellen:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Auf Windows: venv\Scripts\activate
    ```

3.  **Abhängigkeiten installieren:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Konfiguration:**
    Kopiere die Beispiel-Konfiguration und passe sie an:
    ```bash
    cp .env.example .env
    ```
    Fülle die `.env` Datei mit deinen eigenen Schlüsseln (SECRET_KEY, VAPID Keys, etc.).

5.  **Datenbank initialisieren:**
    Die Anwendung erstellt die Datenbank beim ersten Start automatisch, wenn sie noch nicht existiert.

6.  **Starten:**
    ```bash
    python app.py
    ```
    Die App ist dann unter `http://localhost:5000` erreichbar.

## 🌐 Ubuntu Server Deployment (Automatisierung)

Für den Betrieb auf einem Ubuntu Server (z. B. DigitalOcean, Hetzner, AWS) empfiehlt sich die Nutzung von **Gunicorn** und **systemd**.

### 1. Installations-Skript (Automatisierung)
Du kannst dieses kombinierte Kommando nutzen, um das System vorzubereiten:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git nginx
git clone https://github.com/BastianBerleb/Mannschaftskasse.git
cd Mannschaftskasse
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Systemd Service (Automatischer Neustart)
Erstelle eine Service-Datei, damit die App nach einem Reboot automatisch startet:
`sudo nano /etc/systemd/system/mannschaftskasse.service`

Inhalt (Pfade anpassen!):
```ini
[Unit]
Description=Gunicorn instance to serve Mannschaftskasse
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/mannschaftskasse
Environment="PATH=/var/www/mannschaftskasse/venv/bin"
ExecStart=/var/www/mannschaftskasse/venv/bin/gunicorn --workers 3 --bind unix:app.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

Dann den Dienst aktivieren:
```bash
sudo systemctl start mannschaftskasse
sudo systemctl enable mannschaftskasse
```

### 3. Nginx als Reverse Proxy
Konfiguriere Nginx, um Anfragen an Gunicorn weiterzuleiten:
`sudo nano /etc/nginx/sites-available/mannschaftskasse`

```nginx
server {
    listen 80;
    server_name dein-domain.de;

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/mannschaftskasse/app.sock;
    }
}
```

## 📂 Projektstruktur

*   `app.py`: Die Hauptanwendung (Flask-Server & API).
*   `worker_scheduler.py`: Hintergrund-Tasks für zeitgesteuerte Aufgaben.
*   `backup.py`: Automatisierte Cloud-Backups.
*   `templates/`: HTML5 Jinja2 Templates.
*   `static/`: CSS, JS und Bilder.
*   `reset_admin_password.py`: Utility-Script für Notfall-Administratoren.

## 🔒 Sicherheitshinweise

Diese Anwendung wurde mit Fokus auf Datenschutz und Sicherheit entwickelt:
*   **Keine Passwörter im Klartext:** Alle Passwörter werden mittels `scrypt` gehasht.
*   **Umgebungsvariablen:** Alle sensitiven Schlüssel (API-Keys, Datenbank-Pfade) werden über eine `.env` Datei geladen, die **nicht** in die Versionsverwaltung eingeht.
*   **Gitignore:** Automatisch generierte Dateien wie `.db`, `venv/`, logs und Cache-Verzeichnisse werden ignoriert.

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe die [LICENSE](LICENSE) Datei für Details (falls vorhanden).

---
Entwickelt für den **TSV Alteglofsheim** 🖤🤍
