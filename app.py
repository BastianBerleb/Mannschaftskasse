from flask import send_file
from io import BytesIO
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

# app.py
import os
import time
import io
import pandas as pd
import requests 
import json
import secrets 
import threading
import logging
import traceback
import base64
from datetime import datetime, timedelta

# WebAuthn Imports
try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        AuthenticatorAttachment,
        AttestationConveyancePreference,
        UserVerificationRequirement,
        ResidentKeyRequirement,
        PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
except ImportError:
    # This might happen in the local environment, but we expect it on the production server
    print("WARNING: 'webauthn' library not found. Biometric login will not functional.")
    generate_registration_options = None
    verify_registration_response = None
    generate_authentication_options = None
    verify_authentication_response = None
import io
import hashlib
import calendar
from pytz import timezone
import pytz
from whitenoise import WhiteNoise
from flask_migrate import Migrate
from pywebpush import webpush, WebPushException
from sqlalchemy import text, event
from weasyprint import HTML, CSS
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, g, jsonify, send_from_directory, session, make_response, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from datetime import datetime, date, timedelta
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import re
from functools import wraps
import click
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash
import re
from functools import wraps
import click
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, unquote_plus
import traceback

# --- LOGGING KONFIGURATION ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler = logging.FileHandler('fupa_log.txt')
log_handler.setFormatter(log_formatter)
fupa_logger = logging.getLogger('fupa_scraper')
fupa_logger.setLevel(logging.INFO)
fupa_logger.addHandler(log_handler)

# --- PUSH LOGGING KONFIGURATION ---
def german_time(*args):
    return datetime.now(GERMAN_TZ).timetuple()

push_log_handler = logging.FileHandler('push_log.txt')
# Sage dem Formatter, dass er die deutsche Zeit verwenden soll
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
formatter.converter = german_time
push_log_handler.setFormatter(formatter)

push_logger = logging.getLogger('webpush')
push_logger.setLevel(logging.INFO)
push_logger.addHandler(push_log_handler)

# --- NEUER FUPA CACHE (File-Based for Worker Consistency) ---
# Ensure basedir is defined or use absolute path
_basedir = os.path.abspath(os.path.dirname(__file__))
FUPA_CACHE_FILE = os.path.join(_basedir, 'fupa_cache.json')

def load_fupa_cache():
    """Lädt den Fupa-Cache aus der JSON-Datei."""
    if os.path.exists(FUPA_CACHE_FILE):
        try:
            with open(FUPA_CACHE_FILE, 'r') as f:
                data = json.load(f)
                ts = datetime.fromisoformat(data['timestamp'])
                # fupa_logger.info("Fupa Cache loaded from disk.")
                return data['data'], ts
        except Exception as e:
            fupa_logger.error(f"Error loading fupa cache: {e}")
    return None, None

def save_fupa_cache_to_disk(data, timestamp):
    """Speichert den Fupa-Cache in die JSON-Datei."""
    try:
        def serialize_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
            
        with open(FUPA_CACHE_FILE, 'w') as f:
            json.dump({'data': data, 'timestamp': timestamp.isoformat()}, f, default=serialize_sets)
            fupa_logger.info("Fupa Cache saved to disk.")
    except Exception as e:
        fupa_logger.error(f"Error saving fupa cache: {e}")

# In-Memory Cache (wird initial geladen)
_data, _ts = load_fupa_cache()
fupa_cache = {
    "data": _data,
    "timestamp": _ts
}

# --- STATIC FILES HASH CACHE ---
static_hash_cache = {
    "hash": None,
    "timestamp": None
}

# NEUER BLOCK: Erstelle eine benutzerdefinierte WhiteNoise-Klasse
class WhiteNoiseWithHeaders(WhiteNoise):
    def __init__(self, application, root=None, prefix=None, **kwargs):
        super().__init__(application, root=root, prefix=prefix, **kwargs)
        # Füge den speziellen Header für die Service Worker Datei hinzu
        self.add_files(root, prefix=prefix)
        # Der Trick ist, die Header direkt auf die statische Datei zu setzen
        if 'sw.js' in self.files:
            self.files['/static/sw.js'].headers.append(
                ('Service-Worker-Allowed', '/')
            )
            
# --- ZEITZONEN-KONFIGURATION ---
GERMAN_TZ = timezone('Europe/Berlin')

# --- Konfiguration ---
try:
    from dotenv import load_dotenv
    # Lade Umgebungsvariablen aus der .env Datei (falls vorhanden)
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'mannschaftskasse.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Secret Key streng aus Umgebungsvariablen laden (Sicherheit)
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    # WICHTIG: Die App darf nicht ohne einen festen SECRET_KEY starten!
    # Ein zufälliger Key pro Neustart würde alle Benutzer sofort ausloggen.
    raise RuntimeError("KRITISCHER FEHLER: Kein SECRET_KEY in der `.env` oder in den Umgebungsvariablen gefunden. Die App wird nicht gestartet, um Datenverlust bei Sessions zu vermeiden.")

app.config['SECRET_KEY'] = secret_key
# --- KORREKTE WHITENOISE KONFIGURATION ---
# Sage WhiteNoise, wo die statischen Dateien auf der Festplatte liegen
static_folder_root = os.path.join(basedir, 'static')
# Sage WhiteNoise, dass es auf Anfragen unter der URL /static lauschen soll
# Setze max_age auf 1 Jahr (31536000 Sekunden), da wir Cache-Busting via Dateinamen nutzen
app.wsgi_app = WhiteNoise(app.wsgi_app, root=static_folder_root, prefix='static/', max_age=31536000)
# app.wsgi_app.add_files(static_folder_root, prefix='static/') # Redundant if root is passed to init, but keeps it safe.

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Bitte melde dich an, um auf diese Seite zuzugreifen."
login_manager.login_message_category = "info"

# --- CSRF PROTECTION INIT ---
csrf = CSRFProtect(app)

# --- AUDIT LOG MODEL ---
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_name = db.Column(db.String(100)) # Name des Users, der die Aktion ausführte
    action = db.Column(db.String(50))     # z.B. "CREATE", "UPDATE", "DELETE"
    module = db.Column(db.String(50))     # z.B. "PLAYER", "TRANSACTION", "SETTINGS"
    details = db.Column(db.Text)          # Was genau passiert ist

def log_audit(action, module, details):
    """Hilfsfunktion zum Erstellen eines Log-Eintrags"""
    try:
        user = current_user.username if current_user and current_user.is_authenticated else "System/Gast"
        new_log = AuditLog(user_name=user, action=action, module=module, details=details)
        db.session.add(new_log)
        # Commit muss vom Aufrufer oder hier erfolgen. 
        # Um Seiteneffekte mit Rollbacks zu vermeiden, committen wir hier oft direkt oder nutzen den Session-Flow.
        # Da wir oft innerhalb einer laufenden Transaktion loggen, adden wir es nur zur Session.
        # Aber Achtung: Wenn die Haupt-Transaktion fehlschlägt, wird auch das Log nicht geschrieben (was ok ist).
    except Exception as e:
        print(f"Audit Log Error: {e}")

# --- BILD-CACHE ---
# Speichert bereits generierte PNG-Daten, um Neuberechnung zu vermeiden.
# Wird bei jeder Datenbank- Änderung (commit) geleert.
fines_image_cache = {}

@event.listens_for(db.session, 'after_commit')
def on_db_commit(session):
    """Leert den Bild-Cache, sobald Transaktionen etc. in die DB geschrieben wurden."""
    global fines_image_cache
    fines_image_cache.clear()
    # Optional: Loggen
    # print("Datenbank-Update erkannt -> Bild-Cache geleert.")

# PWA-optimierte Session-Konfiguration
from datetime import timedelta
# HINWEIS: Die tatsächliche Dauer wird nun dynamisch im 'before_request' Handler gesetzt,
# basierend auf den 'settings' in der Datenbank.
app.permanent_session_lifetime = timedelta(days=3650)  # Standard-Fallback: 10 Jahre
login_manager.session_protection = "basic"  # Weniger restriktiv für PWA

# --- PUSH NOTIFICATION SETUP ---
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')

# WebAuthn Configuration
WEBAUTHN_RP_ID = os.environ.get('WEBAUTHN_RP_ID', 'kasse.berleb.me')
WEBAUTHN_RP_NAME = "TSV Kasse"
WEBAUTHN_ORIGIN = os.environ.get('WEBAUTHN_ORIGIN', f'https://{WEBAUTHN_RP_ID}')


if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
    print("WARNUNG: VAPID_PUBLIC_KEY oder VAPID_PRIVATE_KEY fehlt in den Umgebungsvariablen.")

VAPID_CLAIMS = {
    "sub": "mailto:bastianberleb@gmail.com"  # Ersetz dies mit einer Kontakt-E-Mail
}

# --- Hilfsfunktionen ---
def is_ajax():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

def get_date_from_form(form):
    """Hilfsfunktion, um ein Datum aus einem Formular zu extrahieren."""
    date_str = form.get('date')
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            # Nutzt jetzt die deutsche Zeit als Fallback
            return datetime.now(GERMAN_TZ).date()
    # Nutzt jetzt die deutsche Zeit als Fallback
    return datetime.now(GERMAN_TZ).date()

def get_deadline(tx_date):
    """
    Berechnet die Fälligkeit:
    Nächster Freitag, der mindestens 14 Tage nach dem Transaktionsdatum liegt.
    """
    if not tx_date:
        return datetime.utcnow().date()
        
    target = tx_date + timedelta(days=14)
    while target.weekday() != 4: # 4 = Friday
        target += timedelta(days=1)
    return target

def recalculate_settlements(player_id, team, _db_session=None):
    """
    Recalculates the 'amount_settled' for all fines of a player in a specific team.
    This ensures that available credit is correctly distributed to the oldest fines first,
    fixing desync issues after deletions.
    """
    session = _db_session or db.session
    try:
        # 1. Reset settled amount for ALL fines of this player/team
        # We stick to our convention: Transaction < 0 AND category='fine' are fines.
        fines = session.query(Transaction).filter(
            Transaction.player_id == player_id,
            Transaction.team == team,
            Transaction.category == 'fine',
            Transaction.amount < 0
        ).order_by(Transaction.date.asc(), Transaction.id.asc()).all()

        for f in fines:
            f.amount_settled = 0.0
            
        # 2. Calculate Total Available Credit (Pool)
        # Sum of all transactions (positive and negative) EXCEPT the fines themselves.
        others = session.query(Transaction).filter(
            Transaction.player_id == player_id,
            Transaction.team == team,
            (Transaction.category != 'fine') | (Transaction.amount >= 0) 
        ).all()
        
        # Calculate pool (Sum amounts). Note: Debit trxs in 'others' are negative, reducing the pool.
        pool = sum(t.amount for t in others)
        
        # 3. Distribute Pool to Fines (FIFO)
        if pool > 0:
            for f in fines:
                if pool <= 0.001: break
                
                needed = abs(f.amount)
                pay = min(pool, needed)
                
                f.amount_settled = pay
                pool -= pay
        
        # No commit here, caller handles commit
    except Exception as e:
        print(f"Error in recalculate_settlements: {e}")

def get_lastname_sort_key(player_or_name):

    """Sortier-Schlüssel für Spieler: Nachname, Vorname"""
    if isinstance(player_or_name, str):
        name = player_or_name
    elif hasattr(player_or_name, 'name'):
        name = player_or_name.name
    else:
        return ""

    if not name: return ""
    parts = name.strip().split()
    if not parts: return ""
    # Letztes Wort als Nachname angenommen, Rest als Vorname(n).
    lastname = parts[-1].lower()
    if len(parts) > 1:
        firstnames = " ".join(parts[:-1]).lower()
    else:
        firstnames = ""
    return f"{lastname} {firstnames}"

def send_push_notification(player_id, title, body, url):
    """Holt alle Abos für einen Spieler und sendet eine Push-Benachrichtigung.
    TTL=259200 (3 Tage): Der Push-Dienst hält die Nachricht 3 Tage
    und stellt sie zu sobald das Gerät online kommt.
    """
    player = Player.query.get(player_id)
    if not player:
        return

    subscriptions = player.subscriptions.all()
    if not subscriptions:
        push_logger.info(f"Keine Push-Abos für Spieler '{player.name}' gefunden.")
        return

    push_logger.info(f"Sende Push an {len(subscriptions)} Gerät(e) für '{player.name}'.")
    for sub_record in subscriptions:
        log_entry = PushLog(
            player_id=player_id,
            endpoint_fragment=sub_record.endpoint[-100:] if sub_record.endpoint else '',
            title=title
        )
        try:
            subscription_info = json.loads(sub_record.subscription_json)
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
                ttl=259200  # 3 Tage — Gerät empfängt auch wenn gerade offline
            )
            log_entry.status = 'ok'
            push_logger.info(f"Push OK: '{title}' → {player.name}")
        except WebPushException as e:
            push_logger.error(f"FEHLER beim Senden an Endpunkt {sub_record.endpoint}: {e}")
            if e.response and e.response.status_code in [404, 410]:
                push_logger.warning(f"Entferne ungültiges Abo: {sub_record.endpoint}")
                log_entry.status = 'removed'
                log_entry.error_msg = f"HTTP {e.response.status_code} – Abo entfernt"
                db.session.delete(sub_record)
            else:
                log_entry.status = 'error'
                log_entry.error_msg = str(e)[:500]
        except Exception as e:
            log_entry.status = 'error'
            log_entry.error_msg = str(e)[:500]
            push_logger.error(f"Unexpected error: {e}")
        finally:
            try:
                db.session.add(log_entry)
                db.session.commit()
            except Exception:
                db.session.rollback()

def notify_admins(title, body):
    """Sendet eine Push-Benachrichtigung an alle Admins mit Push-Abo."""
    try:
        # User Model muss hier verfügbar sein (wird zur Laufzeit aufgelöst)
        admins = User.query.filter_by(role='admin').all()
        admin_url = url_for('admin', _external=True)
        count = 0
        for admin in admins:
            if admin.player_id:
                send_push_notification(admin.player_id, title, body, admin_url)
                count += 1
        push_logger.info(f"Admin-Notification gesendet an {count} Admins: {title}")
    except Exception as e:
        push_logger.error(f"Fehler bei notify_admins: {e}")

def trigger_daily_birthday_notifications():
    """
    Prüft, ob heute bereits Geburtstags-Benachrichtigungen verschickt wurden.
    Falls nicht, wird der Check durchgeführt und die Pushes versendet.
    Wird in der index-Route aufgerufen.
    """
    try:
        today_str = datetime.now(GERMAN_TZ).strftime('%Y-%m-%d')
        
        # Check setting
        last_check = KasseSetting.query.filter_by(key='last_birthday_notify_date').first()
        if last_check and last_check.value == today_str:
            return # Bereits heute erledigt
            
        # 1. Update setting immediately (prevent double triggers)
        if not last_check:
            last_check = KasseSetting(key='last_birthday_notify_date', value=today_str)
            db.session.add(last_check)
        else:
            last_check.value = today_str
        
        db.session.commit()
        
        # 2. Logic (from worker_scheduler.py)
        today = datetime.now(GERMAN_TZ).date()
        all_players = Player.query.filter_by(is_active=True).all()
        birthday_kids = []
        
        for p in all_players:
            if p.birthday and p.birthday.month == today.month and p.birthday.day == today.day:
                birthday_kids.append(p)
        
        if not birthday_kids:
            push_logger.info("📅 Trigger: Keine Geburtstage heute.")
            return

        # Prepare messages
        if len(birthday_kids) == 1:
            kid = birthday_kids[0]
            title = "🎉 Happy Birthday!"
            body = f"{kid.name} hat heute Geburtstag! 🎂 Zeit zum Gratulieren!"
        else:
            names = ", ".join([p.name for p in birthday_kids])
            title = "🎉 Doppelte Party!"
            body = f"Heute haben Geburtstag: {names}. 🎂 Alles Gute!"
        
        birthday_ids = [k.id for k in birthday_kids]
        user_roles = {u.player_id: u.role for u in User.query.all()}
        
        # Who gets notified? (Admins/Viewers etc., but not the birthday kids themselves here)
        recipients = [
            p for p in all_players 
            if p.id not in birthday_ids 
            and user_roles.get(p.id) is not None 
            and user_roles.get(p.id) != 'player'
        ]
        
        count = 0
        url_to_open = url_for('geburtstage', _external=True)
        
        for recipient in recipients:
            try:
                send_push_notification(recipient.id, title, body, url_to_open)
                count += 1
            except: pass
        
        # Notify kids
        for kid in birthday_kids:
            try:
                 send_push_notification(kid.id, "🎈 Alles Gute!", "Das Team wünscht dir einen tollen Geburtstag!", url_to_open)
            except: pass

        push_logger.info(f"📅 Birthday-Trigger: {len(birthday_kids)} Geburtstag(e) gefunden. {count} Benachrichtigungen verschickt.")
        
    except Exception as e:
        push_logger.error(f"❌ Fehler im Birthday-Trigger: {e}")
        db.session.rollback()

def generate_static_files_hash():
    """
    Generiert einen MD5-Hash über alle relevanten App-Dateien (Python, HTML, Static).
    Verwendet einen Cache, um IO-Last zu reduzieren.
    """
    global static_hash_cache
    
    # 5 Minuten Cache-Dauer
    CACHE_DURATION = 300 
    now = time.time()
    
    if static_hash_cache["hash"] and static_hash_cache["timestamp"] and (now - static_hash_cache["timestamp"] < CACHE_DURATION):
        return static_hash_cache["hash"]

    hasher = hashlib.md5()
    
    # Definiere alle Verzeichnisse und Dateien, die in den Hash einfließen sollen
    paths_to_hash = [
        os.path.join(basedir, 'app.py'),         # Die Haupt-App-Datei
        os.path.join(basedir, 'templates'),      # Das gesamte Template-Verzeichnis
        os.path.join(basedir, 'static'),         # Das gesamte Static-Verzeichnis
    ]

    for path in paths_to_hash:
        if os.path.isfile(path):
            # Wenn es eine einzelne Datei ist
            try:
                with open(path, 'rb') as f:
                    while chunk := f.read(8192):
                        hasher.update(chunk)
            except IOError:
                continue
        elif os.path.isdir(path):
            # Wenn es ein Verzeichnis ist, gehe rekursiv durch
            for root, _, files in os.walk(path):
                for filename in sorted(files):
                    # Ignoriere die sw.js-Vorlage selbst, um eine Endlosschleife zu vermeiden
                    if filename.endswith('.j2'):
                        continue
                    
                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'rb') as f:
                            while chunk := f.read(8192):
                                hasher.update(chunk)
                    except IOError:
                        continue
    
    new_hash = hasher.hexdigest()
    static_hash_cache["hash"] = new_hash
    static_hash_cache["timestamp"] = now
                        
    return new_hash

# --- Benutzerrollen & Rechte-Management ---
VALID_ROLES = ['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2', 'viewer', 'guest', 'player']

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed_roles:
                if is_ajax():
                    return jsonify({'success': False, 'message': 'Keine Berechtigung für diese Aktion.'}), 403
                flash("Du hast keine Berechtigung, diese Aktion auszuführen.", "danger")
                return redirect(request.referrer or url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Erweiterte Fupa Scraper-Funktionen ---
def _get_json_from_fupa_page(url, timeout=10):
    """Holt und parst die JSON-Daten von einer Fupa-Seite."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    try:
        fupa_logger.info(f"Scraping URL ({timeout}s timeout): {url}")
        response = requests.get(url, headers=headers, timeout=timeout)
        
        if response.status_code != 200:
            fupa_logger.error(f"Fupa Request failed with status code: {response.status_code} for URL: {url}")
            return None
            
        html_content = response.text
        start_marker = 'window.REDUX_DATA = '
        start_index = html_content.find(start_marker)
        if start_index == -1: 
            fupa_logger.warning(f"MARKER NOT FOUND in response for {url}")
            return None
            
        end_marker = '</script>'
        json_start = start_index + len(start_marker)
        json_end = html_content.find(end_marker, json_start)
        json_data_str = html_content[json_start:json_end].strip()
        data = json.loads(json_data_str)
        return data
    except requests.Timeout:
        fupa_logger.error(f"TIMEOUT ({timeout}s) bei URL {url}")
        return None
    except Exception as e:
        fupa_logger.error(f"Fupa-Scraping EXCEPTION bei URL {url}: {e}")
        return None

def get_lineup_from_match_page(match_slug):
    """Holt die Namen der aufgestellten Spieler für ein bestimmtes Spiel."""
    try:
        url = f"https://www.fupa.net/match/{match_slug}/lineup"
        data = _get_json_from_fupa_page(url)
        if not data: return set()
        
        lineup_data = data.get('dataHistory', [{}])[0].get('MatchLineUpPage', {}).get('lineup', {})
        if not lineup_data: return set()
        
        player_names = set()
        for team_key in ['homeTeam', 'awayTeam']:
            team_lineup = lineup_data.get(team_key, {}).get('lineup', [])
            for player_entry in team_lineup:
                player_info = player_entry.get('player', {})
                first_name = player_info.get('firstName', '')
                last_name = player_info.get('lastName', '')
                if first_name and last_name:
                    player_names.add(f"{first_name} {last_name}")
        return player_names
    except Exception as e:
        print(f"Fehler beim Holen des Kaders von {match_slug}: {e}")
        return set()

def get_latest_fupa_game_data(season_str):
    """
    Holt die Spieldaten für die 1. und 2. Mannschaft und gibt die kombinierten Spielerdaten zurück.
    """
    fupa_data = {
        'team2_date': None, 'team2_opponent': None, 'team2_lineup': set(),
        'team1_lineup': set(), 'combined_info': {},
        'team1_date': None, 'team1_opponent': None # Explizit initialisieren
    }
    
    try:
        fupa_logger.info(f"Suche Fupa-Daten für Saison: {season_str}")
        parts = season_str.split('/')
        if len(parts) != 2: return fupa_data
        fupa_season = f"{parts[0]}-{parts[1][-2:]}"

        # --- Daten für die 2. Mannschaft holen ---
        team2_url = f"https://www.fupa.net/team/tsv-alteglofsheim-m2-{fupa_season}/matches"
        fupa_logger.info(f"Rufe URL für Team 2 auf: {team2_url}")
        team2_data = _get_json_from_fupa_page(team2_url)
        if not team2_data: 
            fupa_logger.error("Keine JSON-Daten von Team 2 URL erhalten.")
            team2_data = {} # Handle gracefully
            # return fupa_data <-- REMOVED

        team2_items = []
        if team2_data:
             team2_items = team2_data.get('dataHistory', [{}])[0].get('TeamMatchesPage', {}).get('items', [])
        if not team2_items:
            fupa_logger.warning("Keine Spiele für Team 2 in den JSON-Daten gefunden.")
            # return fupa_data  <-- REMOVED: Don't stop here, try Team 1!
            
        today = datetime.now().date()
        # Safe selection logic even if team2_items is empty
        team2_match = next((g for g in team2_items if g.get('kickoff') and today - timedelta(days=7) <= datetime.fromisoformat(g.get('kickoff').replace('Z', '+00:00')).date() <= today), team2_items[0] if team2_items else None)
        
        team2_kickoff = None
        if team2_match:
             try:
                 team2_kickoff = datetime.fromisoformat(team2_match.get('kickoff').replace('Z', '+00:00')).date()
                 fupa_data['team2_date'] = team2_kickoff.strftime('%Y-%m-%d')
             except Exception as e:
                 fupa_logger.error(f"Fehler beim Parsen des Team 2 Kickoff: {e}")

             # --- NEUE, ROBUSTERE GEGNER-ERKENNUNG ---
             home_team = team2_match.get('homeTeam', {})
             away_team = team2_match.get('awayTeam', {})

             home_team_name = home_team.get('name', {}).get('full', '').lower()
             away_team_name = away_team.get('name', {}).get('full', '').lower()

             if 'alteglofsheim' in home_team_name:
                 fupa_data['team2_opponent'] = away_team.get('name', {}).get('full', 'Unbekannt')
             elif 'alteglofsheim' in away_team_name:
                 fupa_data['team2_opponent'] = home_team.get('name', {}).get('full', 'Unbekannt')
             else:
                 fupa_data['team2_opponent'] = "Gegner nicht erkannt"

             team2_slug = team2_match.get('slug')
             if team2_slug:
                 fupa_logger.info(f"Hole Kader für Team 2 vom Spiel-Slug: {team2_slug}")
                 fupa_data['team2_lineup'] = get_lineup_from_match_page(team2_slug)
        else:
             fupa_logger.warning("Kein passendes Spiel für Team 2 gefunden.")


        # --- Daten für die 1. Mannschaft holen ---
        # Kurze Pause, um FuPa-Rate-Limiting nicht zu triggern
        time.sleep(1.5)
        
        team1_url = f"https://www.fupa.net/team/tsv-alteglofsheim-m1-{fupa_season}/matches"
        fupa_logger.info(f"Rufe URL für Team 1 auf: {team1_url} (Timeout: 15s)")
        
        # Reduzierter Timeout, um Hänger zu vermeiden, wenn Fupa zickt
        try:
             # Timeout erhöht auf 15s, da 8s zu kurz sein könnten
             # Neuer Parameter timeout wird jetzt korrekt verwendet
             team1_data = _get_json_from_fupa_page(team1_url, timeout=15)
        except Exception:
             team1_data = None
             fupa_logger.warning("Timeout oder Fehler beim Abrufen der Team 1 Daten.")

        if team1_data:
            team1_items = team1_data.get('dataHistory', [{}])[0].get('TeamMatchesPage', {}).get('items', [])
            fupa_logger.info(f"Gefundene Spiele Team 1: {len(team1_items)}")

            # Hilfsfunktion zum Parsen der Items
            parsed_t1 = []
            for item in team1_items:
                start_str = item.get('kickoff')
                if start_str:
                    try:
                        dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
                        parsed_t1.append((item, dt))
                    except:
                        continue
            
            # Sortiere: Neueste ZUERST (für vergangene Spiele wichtig)
            parsed_t1.sort(key=lambda x: x[1], reverse=True)
            
            team1_match = None
            today_dt = datetime.now().date()

            # STRATEGIE 1: Matching mit Team 2 (falls vorhanden)
            if team2_kickoff:
                 for item, dt in parsed_t1:
                     if abs((dt - team2_kickoff).days) <= 3:
                         team1_match = item
                         fupa_logger.info(f"Team 1 Match via Sync gefunden: {dt}")
                         break
            
            # STRATEGIE 2: Fallback -> Nimm das chronologisch letzte gespielte Spiel
            if not team1_match and parsed_t1:
                 # Wir suchen in unseren sortierten Matches (Desc) das erste, das <= heute ist.
                 # parsed_t1: [(item, dt), (item, dt)...] desc sorted by dt
                 for item, dt in parsed_t1:
                     if dt <= today_dt:
                         team1_match = item
                         fupa_logger.info(f"Team 1 Fallback (Last Played): {dt} (<= {today_dt})")
                         break
            
            # STRATEGIE 3: Fallback -> Nehme das neuste bekannte Spiel, falls Strategie 2 fehlschlägt (z.B. nur Zukunft)
            if not team1_match and parsed_t1:
                # Da parsed_t1 absteigend sortiert ist (Neueste zuerst), ist index 0 das Spiel, das am weitesten in der Zukunft liegt.
                # Wenn wir das letzte vergangene Spiel suchen und Strategie 2 nichts gefunden hat, heißt es, ALLE Spiele sind in der Zukunft.
                # Dann nehmen wir halt das nächste anstehende Spiel. Das ist Index -1 (das älteste der Zukünftigen)?
                # Nein Liste ist desc: [Mai, April, März]. Index -1 ist März (nächstes Spiel von heute aus gesehen).
                # Index 0 ist Mai (ganz weit weg).
                
                # Aber die User Logik war: "Last 5 matches" -> Future.
                # Wenn er sagt "da gab es nachher noch 6 Spiele", meint er vielleicht, dass in der Liste FEHLEN?
                
                # Wir nehmen einfach das erste Item (Index 0) als Notnagel.
                team1_match = parsed_t1[0][0] 
                fupa_logger.info(f"Team 1 Fallback (First Item in List): {parsed_t1[0][1]}")

            if team1_match:
                # Datum 1. Mannschaft
                try:
                    k_raw = team1_match.get('kickoff')
                    if k_raw:
                        # Verwende datetime.fromisoformat über das importierte Objekt
                        # Da 'from datetime import datetime' genutzt wird, ist 'datetime' die Klasse.
                        team1_kickoff = datetime.fromisoformat(k_raw.replace('Z', '+00:00')).date()
                        fupa_data['team1_date'] = team1_kickoff.strftime('%Y-%m-%d')
                        fupa_logger.info(f"Team 1 Date parsed: {fupa_data['team1_date']}")
                    else:
                        fupa_logger.warning("Team 1 Match has no kickoff string")
                except Exception as e:
                    fupa_logger.error(f"Error parsing Team 1 Date: {e} | Raw: {team1_match.get('kickoff')}")
                
                # Gegner 1. Mannschaft
                try:
                    t1_home = team1_match.get('homeTeam', {})
                    t1_away = team1_match.get('awayTeam', {})
                    t1_home_name = t1_home.get('name', {}).get('full', '').lower()
                    t1_away_name = t1_away.get('name', {}).get('full', '').lower()
                    
                    if 'alteglofsheim' in t1_home_name:
                        fupa_data['team1_opponent'] = t1_away.get('name', {}).get('full', 'Unbekannt')
                    elif 'alteglofsheim' in t1_away_name:
                        fupa_data['team1_opponent'] = t1_home.get('name', {}).get('full', 'Unbekannt')
                    else:
                        fupa_data['team1_opponent'] = "Gegner nicht erkannt"
                    fupa_logger.info(f"Team 1 Opponent: {fupa_data['team1_opponent']}")
                except Exception as e:
                    fupa_logger.error(f"Error parsing Team 1 Opponent: {e}")

                team1_slug = team1_match.get('slug')
                if team1_slug:
                    fupa_logger.info(f"Hole Kader für Team 1 vom Spiel-Slug: {team1_slug}")
                    fupa_data['team1_lineup'] = get_lineup_from_match_page(team1_slug)
            else:
                fupa_logger.warning("Kein passendes Spiel für Team 1 gefunden (Liste war nicht leer, aber Strategien schlugen fehl).")
        else:
            fupa_logger.warning("Keine JSON-Daten von Team 1 URL erhalten (Eventuell Timeout oder leer).")


        # ... (Rest der Funktion bleibt gleich) ...
        return fupa_data

    except Exception as e:
        fupa_logger.error(f"Komplettes Fupa-Scraping fehlgeschlagen: {e}", exc_info=True)
        return fupa_data
       
def update_fupa_cache_in_background(season_str):
    """Diese Funktion wird in einem separaten Thread ausgeführt, um den Cache zu aktualisieren."""
    fupa_logger.info("===== Starte Fupa-Daten-Update im Hintergrund =====")
    live_fupa_data = get_latest_fupa_game_data(season_str)
    
    # **NEUE, bessere Bedingung:**
    # Wir aktualisieren den Cache, sobald ein Spieldatum für Team 1 ODER Team 2 gefunden wurde.
    if live_fupa_data and (live_fupa_data.get('team2_date') or live_fupa_data.get('team1_date')):
        new_ts = datetime.utcnow()
        
        # Merge mit vorherigem Cache, um leere Daten (z.B. durch Rate-Limits) abzufangen
        old_data = fupa_cache.get("data")
        if not old_data: old_data, _ = load_fupa_cache()
            
        if old_data and isinstance(old_data, dict):
            if not live_fupa_data.get('team1_date') and old_data.get('team1_date'):
                live_fupa_data['team1_date'] = old_data.get('team1_date')
                live_fupa_data['team1_opponent'] = old_data.get('team1_opponent')
                live_fupa_data['team1_lineup'] = old_data.get('team1_lineup', set())
            if not live_fupa_data.get('team2_date') and old_data.get('team2_date'):
                live_fupa_data['team2_date'] = old_data.get('team2_date')
                live_fupa_data['team2_opponent'] = old_data.get('team2_opponent')
                live_fupa_data['team2_lineup'] = old_data.get('team2_lineup', set())
                
        fupa_cache["data"] = live_fupa_data
        fupa_cache["timestamp"] = new_ts
        save_fupa_cache_to_disk(live_fupa_data, new_ts)
        
        # Loggen, was wir gefunden haben
        teams_found = []
        if live_fupa_data.get('team2_date'):
            teams_found.append(f"Team 2 ({live_fupa_data.get('team2_opponent')})")
        if live_fupa_data.get('team1_date'):
            teams_found.append(f"Team 1 ({live_fupa_data.get('team1_opponent')})")
            
        fupa_logger.info(f"Cache aktualisiert. Gefundene Spiele: {', '.join(teams_found)}.")
        
        if live_fupa_data.get('team2_lineup'):
            fupa_logger.info(f"Team 2 Kader ({len(live_fupa_data['team2_lineup'])} Spieler) gefunden: {', '.join(sorted(live_fupa_data['team2_lineup']))}")
        else:
            fupa_logger.warning("Kein Kader für Team 2 gefunden.")
        
        if live_fupa_data.get('team1_lineup'):
            fupa_logger.info(f"Team 1 Kader ({len(live_fupa_data['team1_lineup'])} Spieler) gefunden: {', '.join(sorted(live_fupa_data['team1_lineup']))}")
        else:
            fupa_logger.warning("Kein Kader für Team 1 gefunden.")
    else:
        fupa_logger.warning("Kein brauchbares Spiel für Team 1 oder Team 2 auf Fupa gefunden. Cache nicht aktualisiert.")
    
    fupa_logger.info("===== Fupa-Daten-Update im Hintergrund beendet =====")
        
# --- Saison-Hilfsfunktionen ---
def get_season_for_date(dt):
    if dt.month >= 6: return f"{dt.year}/{dt.year + 1}"
    else: return f"{dt.year - 1}/{dt.year}"
def get_season_daterange(season_str):
    if not season_str or season_str == 'all': return date.min, date.max
    try:
        start_year = int(season_str.split('/')[0])
        return date(start_year, 6, 1), date(start_year + 1, 5, 31)
    except (ValueError, IndexError): return date.min, date.max
def get_available_seasons():
    min_date_tx = db.session.query(func.min(Transaction.date)).scalar()
    min_date_exp = db.session.query(func.min(TeamExpense.date)).scalar()
    max_date_tx = db.session.query(func.max(Transaction.date)).scalar()
    max_date_exp = db.session.query(func.max(TeamExpense.date)).scalar()
    all_dates = [d for d in [min_date_tx, min_date_exp, max_date_tx, max_date_exp] if d]
    if not all_dates: return [get_season_for_date(datetime.utcnow().date())]
    earliest_date = min(all_dates)
    latest_date = max(all_dates)
    seasons = set()
    current_year = earliest_date.year
    loop_date = date(current_year, 6, 1)
    if earliest_date.month < 6: loop_date = date(current_year - 1, 6, 1)
    while loop_date <= latest_date:
        seasons.add(get_season_for_date(loop_date))
        loop_date = date(loop_date.year + 1, 6, 1)
    seasons.add(get_season_for_date(datetime.utcnow().date()))
    return sorted(list(seasons), reverse=True)

# --- Datenbank-Modelle ---
class User(UserMixin, db.Model):
    __tablename__ = 'admin_user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(80), nullable=False, default='player')
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    login_token = db.Column(db.String(64), unique=True, nullable=True)
    is_placeholder = db.Column(db.Boolean, default=False)
    player = db.relationship('Player', backref='user', uselist=False)
    # NEW: Secondary Role for Quick-Toggle
    secondary_role = db.Column(db.String(80), nullable=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

    @property
    def has_biometrics(self):
        """Robust check for biometric credentials (avoids DetachedInstanceError)."""
        object_session = db.session.object_session(self)
        if object_session is None:
            # Falls das Objekt detached ist (zB wegen expunge)
            return WebAuthnCredential.query.with_session(db.session).filter_by(user_id=self.id).count() > 0
        else:
            return self.webauthn_credentials.count() > 0

    @property
    def has_push(self):
        """Robust check for push subscriptions (avoids DetachedInstanceError)."""
        if self.player_id:
            from app import PushSubscription # Fallback Import
            object_session = db.session.object_session(self)
            if object_session is None:
                return PushSubscription.query.with_session(db.session).filter_by(player_id=self.player_id).count() > 0
            elif self.player:
                return self.player.subscriptions.count() > 0
        return False

    # Relationships
    webauthn_credentials = db.relationship('WebAuthnCredential', backref='user', lazy='dynamic', cascade="all, delete-orphan")

class WebAuthnCredential(db.Model):
    """
    Stores WebAuthn public keys for biometric login.
    """
    __tablename__ = 'webauthn_credential'
    id = db.Column(db.String(255), primary_key=True) # Credential ID provided by authenticator
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, default=0)
    transports = db.Column(db.String(255), nullable=True) # JSON list of transports
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user:
        # Prevent DetachedInstanceError while evaluating templates/lazy-loading relationships:
        # We explicitly load the player object before expunging
        if getattr(user, 'player_id', None):
            _ = user.player

        # ROLE SWITCHING LOGIC
        # Store the genuine DB role so the switcher can always go back
        user.real_role = user.role

        # Check if a temporary role override is active in the session
        override = session.get('active_role_override')
        if override:
            # Sicherheits-Check: Ist der Override (noch) erlaubt?
            is_valid_override = False
            if user.role == 'admin':
                is_valid_override = True
            elif getattr(user, 'secondary_role', None) == override:
                is_valid_override = True

            if is_valid_override:
                # IMPORTANT: Expunge the user from the SQLAlchemy session BEFORE
                # changing user.role. This prevents the override from being treated
                # as a dirty DB write and accidentally committed to the database
                # when a booking endpoint calls db.session.commit().
                db.session.expunge(user)
                user.role = override
            else:
                # Berechtigung für diesen Override wurde entzogen oder ist ungültig
                session.pop('active_role_override', None)
    return user

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    phone_number = db.Column(db.String(20), nullable=True)
    birthday = db.Column(db.Date, nullable=True)
    team1 = db.Column(db.Boolean, nullable=False, default=False)
    team2 = db.Column(db.Boolean, nullable=False, default=False)
    image_path = db.Column(db.String(255), nullable=True) # Pfad zum Profilbild
    subscriptions = db.relationship('PushSubscription', backref='player', lazy='dynamic', cascade="all, delete-orphan")
    transactions = db.relationship('Transaction', backref='player', lazy='dynamic', cascade="all, delete-orphan")
    kistl_transactions = db.relationship('KistlTransaction', backref='player', lazy='dynamic', cascade="all, delete-orphan")

    @property
    def has_push(self):
        """Robust check for push subscriptions."""
        try:
            return self.subscriptions.count() > 0
        except (AttributeError, TypeError):
            try:
                return len(self.subscriptions) > 0
            except:
                return False

    @property
    def oldest_unpaid_fine(self):
        """Returns the oldest unpaid transaction of category 'fine'."""
        # Note: This does not account for doubling logic itself (dates), just returns the object transaction
        # Filter all fines for this player
        fines = self.transactions.filter(
            Transaction.amount < 0,
            Transaction.category == 'fine'
        ).order_by(Transaction.date.asc()).all()
        
        for f in fines:
             settled = f.amount_settled if f.amount_settled is not None else 0.0
             # Allow small float epsilon
             if settled < abs(f.amount) - 0.01:
                 # Check if covered by generic credit (Guthaben) to avoid false alerts
                 # If the player has a positive balance for the respective team, we consider the fine covered/irrelevant for a deadline.
                 if f.team == 'team1':
                     if self.balance_team1 >= -0.01: continue
                 else:
                     # Team 2 or None
                     if self.balance_team2 >= -0.01: continue

                 # Found oldest unpaid
                 return f
        return None

    def get_unpaid_fines(self, team_filter=None):
        """Gibt eine Liste aller unbezahlten Strafen zurück."""
        query = self.transactions.filter(
            Transaction.amount < 0,
            Transaction.category == 'fine'
        )
        if team_filter:
            query = query.filter(Transaction.team == team_filter)
            
        fines = query.order_by(Transaction.date.asc()).all()
        result = []
        
        for f in fines:
             settled = f.amount_settled if f.amount_settled is not None else 0.0
             if settled < abs(f.amount) - 0.01:
                 result.append(f)
        return result

    @property
    def balance(self):
        if hasattr(self, '_balance_cache'): return self._balance_cache
        return db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == self.id
        ).scalar() or 0.0

    def get_balance(self, team):
        # Note: caching for get_balance needs to be team-specific. 
        # Simpler to handle cache in balance_team1/2 properties directly.
        return db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == self.id,
            Transaction.team == team
        ).scalar() or 0.0

    def get_fine_balance(self, team):
        return db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == self.id,
            Transaction.team == team,
            Transaction.category == 'fine'
        ).scalar() or 0.0

    def get_general_balance(self, team):
        return db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == self.id,
            Transaction.team == team,
            Transaction.category == 'general'
        ).scalar() or 0.0

    @property
    def balance_team1(self):
        if hasattr(self, '_balance_team1_cache'): return self._balance_team1_cache
        return self.get_balance('team1')

    @property
    def fine_balance_team1(self):
        if hasattr(self, '_fine_balance_team1_cache'): return self._fine_balance_team1_cache
        return self.get_fine_balance('team1')

    @property
    def general_balance_team1(self):
        if hasattr(self, '_general_balance_team1_cache'): return self._general_balance_team1_cache
        return self.get_general_balance('team1')

    @property
    def balance_team2(self):
        if hasattr(self, '_balance_team2_cache'): return self._balance_team2_cache
        return self.get_balance('team2')

    @property
    def fine_balance_team2(self):
        if hasattr(self, '_fine_balance_team2_cache'): return self._fine_balance_team2_cache
        return self.get_fine_balance('team2')

    @property
    def general_balance_team2(self):
        if hasattr(self, '_general_balance_team2_cache'): return self._general_balance_team2_cache
        return self.get_general_balance('team2')

    @property
    def kistl_balance(self):
        if hasattr(self, '_kistl_balance_cache'): return self._kistl_balance_cache
        return db.session.query(func.sum(KistlTransaction.amount)).filter(
            KistlTransaction.player_id == self.id
        ).scalar() or 0

    def count_games(self, start_date, end_date, team=None):
        """Zählt nur Transaktionen, die als Spiel markiert sind (enthalten 'gg.')."""
        query = self.transactions.filter(
            Transaction.date.between(start_date, end_date),
            Transaction.description.ilike('%gg.%')  # ilike ist case-insensitive
        )
        if team:
            query = query.filter(Transaction.team == team)
        return query.count()

    def get_games(self, start_date, end_date, team=None):
        """Holt nur Transaktionen, die als Spiel markiert sind (enthalten 'gg.')."""
        query = self.transactions.filter(
            Transaction.date.between(start_date, end_date),
            Transaction.description.ilike('%gg.%')
        )
        if team:
            query = query.filter(Transaction.team == team)
        return query.order_by(Transaction.date.desc()).all()

class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Der 'endpoint' ist die eindeutige ID für ein Gerät/Browser
    endpoint = db.Column(db.String(512), unique=True, nullable=False)
    subscription_json = db.Column(db.Text, nullable=False)
    # Jedes Abo gehört zu genau einem Spieler
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)

class Fine(db.Model):
    id = db.Column(db.Integer, primary_key=True); 
    description = db.Column(db.String(200), nullable=False) # No longer unique globally
    amount = db.Column(db.Float, nullable=False); 
    type = db.Column(db.String(10), nullable=False, default='money')
    team = db.Column(db.String(50), nullable=False, default='team2')
    category = db.Column(db.String(20), nullable=False, default='general') # game, training, general

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date(), index=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    team = db.Column(db.String(50), nullable=True, index=True)  # Team 1 oder Team 2
    category = db.Column(db.String(20), nullable=False, default='general') # 'fine' or 'general'
    amount_settled = db.Column(db.Float, default=0.0) # Bei Strafen: Bereits bezahlter Betrag
    doubled_by_id = db.Column(db.Integer, default=None) # ID der Verdopplungs-Transaktion
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class KistlTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date(), index=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class PendingGameFee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team = db.Column(db.String(50), nullable=False) # 'team1' or 'team2'
    date = db.Column(db.Date, nullable=False)
    opponent = db.Column(db.String(100), nullable=False)
    player_ids_json = db.Column(db.Text, nullable=False) # List of IDs as JSON string
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeamExpense(db.Model):
    __tablename__ = 'team_expense_real' # Um Konflikte zu vermeiden
    id = db.Column(db.Integer, primary_key=True); 
    date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    team = db.Column(db.String(50), nullable=False, default='team2')
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class KasseSetting(db.Model):
    __tablename__ = 'kasse_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(100), nullable=False)

class PushLog(db.Model):
    """Protokolliert jeden Push-Benachrichtigungsversuch."""
    __tablename__ = 'push_log'
    id = db.Column(db.Integer, primary_key=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    player = db.relationship('Player', foreign_keys=[player_id])
    endpoint_fragment = db.Column(db.String(100))
    title = db.Column(db.String(200))
    status = db.Column(db.String(20))  # 'ok', 'error', 'removed'
    error_msg = db.Column(db.String(500), nullable=True)

# --- Request-Handling ---
@app.before_request
def ensure_schema():
    # Einfacher Check: Creates tables if not exist. 
    # Performance-technisch wäre ein einmaliger Check besser, aber create_all ist idempotent.
    # Um es effizient zu halten, machen wir das nur beim Start oder via Flag.
    # Da wir hier keinen persistenten State über Requests hinweg im Worker haben (außer Globals),
    # nutzen wir ein Attribut an der App.
    if not getattr(app, '_schema_checked', False):
        db.create_all()
        # Migration: Add secondary_role column if missing
        try:
             from sqlalchemy import inspect
             inspector = inspect(db.engine)
             columns = [c['name'] for c in inspector.get_columns('admin_user')]
             if 'secondary_role' not in columns:
                 with db.engine.connect() as conn:
                     conn.execute(text("ALTER TABLE admin_user ADD COLUMN secondary_role TEXT"))
                     conn.commit()
                 print("MIGRATION: Added secondary_role column to admin_user table.")
        except Exception as e:
             print(f"Schema Check Error (Migration): {e}")

        app._schema_checked = True

@app.before_request
def load_season_data():
    default_season = get_season_for_date(datetime.utcnow().date())
    g.current_season_str = request.args.get('season', default_season)
    g.start_date, g.end_date = get_season_daterange(g.current_season_str)
    
    # --- DYNAMISCHE SITZUNGSDAUER ---
    try:
        # Standard: 3650 Tage (10 Jahre)
        setting = KasseSetting.query.filter_by(key='session_lifetime_days').first()
        days = int(setting.value) if setting else 3650
        app.permanent_session_lifetime = timedelta(days=days)
        app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=days)
    except Exception:
         app.permanent_session_lifetime = timedelta(days=3650)
         app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=3650)


    # Push-Trigger Check (nur für HTML-Anfragen, nicht für background assets/sw.js)
    # Default auf False
    g.trigger_push_init = False
    
    if session.get('trigger_push_init'):
        # Prüfen ob es eine HTML-Anfrage ist (Seite, nicht Asset/SW)
        is_html_request = 'text/html' in request.headers.get('Accept', '')
        # Manche Browser senden bei Redirects nicht sofort die Header, daher auch Endpoint prüfen
        is_view_endpoint = request.endpoint and 'static' not in request.endpoint and request.endpoint != 'service_worker'
        
        if is_html_request and is_view_endpoint:
            g.trigger_push_init = True
            session.pop('trigger_push_init') # Nur jetzt verbrauchen!

@app.context_processor
def inject_seasons():
    other_params = {k: v for k, v in request.args.items() if k != 'season'}
    return dict(
        available_seasons=get_available_seasons(),
        selected_season=g.current_season_str,
        other_query_params=other_params
    )

@app.context_processor
def utility_processor():
    return dict(quote_plus=quote_plus, now=datetime.utcnow(), get_deadline=get_deadline)

# --- Öffentliche Routen ---
@app.route('/')
@login_required
def index():
    today = datetime.utcnow().date()
    
    # NEU: Geburtstags-Push-Trigger (Hotfix für fehlende Worker-Benachrichtigung)
    trigger_daily_birthday_notifications()
    
    # 1. Geburtstage: Auch Inaktive anzeigen (Wunsch des Users)
    birthday_players = Player.query\
        .filter(func.strftime('%m-%d', Player.birthday) == today.strftime('%m-%d'))\
        .all()
        
    search_query = request.args.get('query', ''); debtors_only = request.args.get('show_debtors') == 'on'
    
    # 2. Haupt-Liste (Spieler-Query)
    if current_user.role == 'player' and current_user.player_id:
        # Fall A: Eingeloggter Spieler sieht NUR sich selbst (auch wenn inaktiv)
        players_query = Player.query.filter(Player.id == current_user.player_id)
    else:
        # Fall B: Admin / Manager / Gast
        if search_query:
            # Bei SUCHE: Suche über ALLE Spieler (auch Inaktive aus dem Backlog), 
            # damit diese gefunden und bearbeitet werden können.
            players_query = Player.query
        else:
            # Standard-Ansicht (ohne Suche): Nur AKTIVE Spieler anzeigen
            players_query = Player.query.filter_by(is_active=True)

    # Such-Filter anwenden (falls vorhanden)
    if search_query: 
        players_query = players_query.filter(Player.name.ilike(f'%{search_query}%'))
    
    # Codeblock entfernt: War redundant durch das if/else oben
    # if current_user.role == 'player' and current_user.player_id:
    #    players_query = players_query.filter(Player.id == current_user.player_id)
        
    players_list = players_query.all()
    players_list.sort(key=get_lastname_sort_key)
    
    # OPTIMIERUNG: Berechne alle Carryover-Werte in einer Bulk-Query statt N+1 Queries
    player_ids = [p.id for p in players_list]
    
    # Bulk-Query für Carryover Balance (alle Spieler auf einmal)
    carryover_balances = {}
    if player_ids:
        carryover_results = db.session.query(
            Transaction.player_id,
            func.sum(Transaction.amount)
        ).filter(
            Transaction.player_id.in_(player_ids),
            Transaction.date < g.start_date
        ).group_by(Transaction.player_id).all()
        carryover_balances = {r[0]: r[1] or 0.0 for r in carryover_results}
    
    # Bulk-Query für Carryover Kistl (alle Spieler auf einmal)
    carryover_kistls = {}
    if player_ids:
        kistl_results = db.session.query(
            KistlTransaction.player_id,
            func.sum(KistlTransaction.amount)
        ).filter(
            KistlTransaction.player_id.in_(player_ids),
            KistlTransaction.date < g.start_date
        ).group_by(KistlTransaction.player_id).all()
        carryover_kistls = {r[0]: r[1] or 0 for r in kistl_results}
    
    # Bulk-Query für Push-Subscriptions (alle Spieler auf einmal)
    push_counts = {}
    if player_ids:
        push_results = db.session.query(
            PushSubscription.player_id,
            func.count(PushSubscription.id)
        ).filter(
            PushSubscription.player_id.in_(player_ids)
        ).group_by(PushSubscription.player_id).all()
        push_counts = {r[0]: r[1] for r in push_results}
    
    # OPTIMIERUNG: Preload alle Balances in Bulk-Queries
    # Balance Team1
    balance_team1_map = {}
    if player_ids:
        t1_results = db.session.query(
            Transaction.player_id,
            func.sum(Transaction.amount)
        ).filter(
            Transaction.player_id.in_(player_ids),
            Transaction.team == 'team1'
        ).group_by(Transaction.player_id).all()
        balance_team1_map = {r[0]: r[1] or 0.0 for r in t1_results}
        
        t1_fine_results = db.session.query(
            Transaction.player_id,
            func.sum(Transaction.amount)
        ).filter(
            Transaction.player_id.in_(player_ids),
            Transaction.team == 'team1',
            Transaction.category == 'fine'
        ).group_by(Transaction.player_id).all()
        fine_team1_map = {r[0]: r[1] or 0.0 for r in t1_fine_results}
    
    # Balance Team2
    balance_team2_map = {}
    fine_team2_map = {}
    if player_ids:
        t2_results = db.session.query(
            Transaction.player_id,
            func.sum(Transaction.amount)
        ).filter(
            Transaction.player_id.in_(player_ids),
            Transaction.team == 'team2'
        ).group_by(Transaction.player_id).all()
        balance_team2_map = {r[0]: r[1] or 0.0 for r in t2_results}
        
        t2_fine_results = db.session.query(
            Transaction.player_id,
            func.sum(Transaction.amount)
        ).filter(
            Transaction.player_id.in_(player_ids),
            Transaction.team == 'team2',
            Transaction.category == 'fine'
        ).group_by(Transaction.player_id).all()
        fine_team2_map = {r[0]: r[1] or 0.0 for r in t2_fine_results}
    
    # Kistl Balance
    kistl_balance_map = {}
    if player_ids:
        k_results = db.session.query(
            KistlTransaction.player_id,
            func.sum(KistlTransaction.amount)
        ).filter(
            KistlTransaction.player_id.in_(player_ids)
        ).group_by(KistlTransaction.player_id).all()
        kistl_balance_map = {r[0]: r[1] or 0 for r in k_results}
    
    # Cache die Balances auf den Player-Objekten (verhindert zusätzliche Queries im Template)
    for p in players_list:
        p._balance_team1_cache = balance_team1_map.get(p.id, 0.0)
        p._fine_balance_team1_cache = fine_team1_map.get(p.id, 0.0)
        p._general_balance_team1_cache = p._balance_team1_cache - p._fine_balance_team1_cache
        
        p._balance_team2_cache = balance_team2_map.get(p.id, 0.0)
        p._fine_balance_team2_cache = fine_team2_map.get(p.id, 0.0)
        p._general_balance_team2_cache = p._balance_team2_cache - p._fine_balance_team2_cache
        
        p._kistl_balance_cache = kistl_balance_map.get(p.id, 0)
        p._balance_cache = p._balance_team1_cache + p._balance_team2_cache
    
    # Spieler-Daten zusammenstellen (jetzt ohne N+1 Queries)
    players_with_stats = []
    
    for p in players_list:
        player_data = {
            'player': p, 
            'carryover_balance': carryover_balances.get(p.id, 0.0),
            'carryover_kistl': carryover_kistls.get(p.id, 0),
            'has_push_notifications': push_counts.get(p.id, 0) > 0
        }
        
        players_with_stats.append(player_data)
    
    if debtors_only:
        players_with_stats = [ps for ps in players_with_stats if ps['player'].balance < 0 or ps['player'].kistl_balance < 0]
        
    # LOGIC UPDATE: Wenn ein Spieler eingeloggt ist, sich selbst an 1. Stelle anzeigen (aber alphabetische Sortierung der anderen beibehalten)
    if current_user.player_id:
        players_with_stats.sort(key=lambda ps: 0 if ps['player'].id == current_user.player_id else 1)
        
    # Direkt aus DB prüfen ob User bereits Biometrie-Credentials hat
    user_has_biometrics = False
    if current_user.is_authenticated:
        cred_count = WebAuthnCredential.query.filter_by(user_id=current_user.id).count()
        user_has_biometrics = cred_count > 0

    return render_template('index.html', players_with_stats=players_with_stats, search_query=search_query, 
                           debtors_only=debtors_only, birthday_players=birthday_players,
                           user_has_biometrics=user_has_biometrics)

@app.route('/sw.js')
def service_worker():
    """
    Rendert die sw.js.j2-Vorlage dynamisch und fügt einen Hash
    aller statischen Dateien hinzu, um Cache-Busting zu automatisieren.
    """
    # 1. Berechne den aktuellen Hash der statischen Dateien
    files_hash = generate_static_files_hash()
    
    # 2. Rendere die Service-Worker-Datei wie ein Template
    template_str = render_template('sw.js.j2', files_hash=files_hash)
    
    # 3. Erstelle eine Antwort mit dem korrekten Content-Type und Headern
    response = app.response_class(
        response=template_str,
        mimetype='application/javascript'
    )
    response.headers['Service-Worker-Allowed'] = '/'
    # Verhindere Caching der sw.js, damit Updates sofort erkannt werden
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(basedir, 'static', 'images'),
                               'tsv-alteglofsheim.jpg', mimetype='image/jpeg')

@app.route('/offline')
def offline():
    return render_template('offline.html')

@app.route('/kasse')
@app.route('/kasse/<team_name>')
@login_required
@role_required(VALID_ROLES[:-1]) # Alle außer 'player'
def kasse(team_name=None):
    # Automatische Weiterleitung basierend auf Rolle
    if team_name is None:
        if current_user.role in ['strafen_manager_1', 'trikot_manager_1']:
            return redirect(url_for('kasse', team_name='team1'))
        elif current_user.role in ['strafen_manager_2', 'trikot_manager_2']:
            return redirect(url_for('kasse', team_name='team2'))
        else:
            # Fallback für Admin und Viewer
            return redirect(url_for('kasse', team_name='team2'))

    if team_name not in ['team1', 'team2']:
        team_name = 'team2'

    # Startguthaben (Legacy 'start_balance' count as team2 usually, or specific key)
    sb_key = 'start_balance' if team_name == 'team2' else f'start_balance_{team_name}'
    start_balance_setting = KasseSetting.query.filter_by(key=sb_key).first()
    start_balance = float(start_balance_setting.value) if start_balance_setting else 0.0

    # Total Deposits (Team filtered)
    total_deposits = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.amount > 0, 
        Transaction.description != "Startguthaben",
        Transaction.team == team_name
    ).scalar() or 0.0

    # Total Expenses (Team filtered)
    total_team_expenses_all = db.session.query(func.sum(TeamExpense.amount)).filter(
        TeamExpense.team == team_name
    ).scalar() or 0.0

    current_balance = start_balance + total_deposits - total_team_expenses_all

    # Seasonal Deposits (Team filtered)
    season_deposits = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.amount > 0,
        Transaction.description != "Startguthaben",
        Transaction.date.between(g.start_date, g.end_date),
        Transaction.team == team_name
    ).scalar() or 0.0

    # Seasonal Expenses (Team filtered)
    season_expenses_query = TeamExpense.query.filter(
        TeamExpense.date.between(g.start_date, g.end_date),
        TeamExpense.team == team_name
    )
    season_expenses = season_expenses_query.order_by(TeamExpense.date.desc()).all()
    
    # Calculate sum of expenses safely
    season_expenses_sum = 0.0
    if season_expenses:
            season_expenses_sum = sum((e.amount or 0.0) for e in season_expenses)

    # --- Previous Season Balance Calculation ---
    prev_balance = 0.0
    balance_diff = 0.0
    prev_season_str = ""
    try:
        # Determine previous season string
        current_start_year = int(g.current_season_str.split('/')[0])
        prev_start_year = current_start_year - 1
        prev_season_str = f"{prev_start_year}/{current_start_year}"
        
        # Get end date of previous season (which is typically May 31st of current start year)
        _, prev_season_end = get_season_daterange(prev_season_str)
        
        # Calculate Balance at end of previous season
        # Deposits up to prev_season_end
        prev_deposits = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.amount > 0, 
            Transaction.description != "Startguthaben",
            Transaction.team == team_name,
            Transaction.date <= prev_season_end
        ).scalar() or 0.0

        # Expenses up to prev_season_end
        prev_expenses = db.session.query(func.sum(TeamExpense.amount)).filter(
            TeamExpense.team == team_name,
            TeamExpense.date <= prev_season_end
        ).scalar() or 0.0
        
        prev_balance = start_balance + prev_deposits - prev_expenses
        balance_diff = current_balance - prev_balance
        
    except Exception as e:
        print(f"Error calculating previous season balance: {e}")


    # Debts / Credits based on Team Balance
    try:
        all_players = Player.query.filter_by(is_active=True).all()
        
        # PERFORMANCE OPTIMIERUNG: Bulk Loading der Salden statt N+1 Queries
        team_balances_query = db.session.query(
            Transaction.player_id, 
            func.sum(Transaction.amount)
        ).filter(
            Transaction.team == team_name
        ).group_by(Transaction.player_id).all()
        
        # Map erstellen: player_id -> balance
        balances_map = {pid: (amount or 0.0) for pid, amount in team_balances_query}
        
        # Calculate balance for this specific team for each player using the map
        team_balances = []
        for p in all_players:
            bal = balances_map.get(p.id, 0.0)
            team_balances.append(bal)
        
        total_debts = sum(b for b in team_balances if b < 0)
        total_player_credit = sum(b for b in team_balances if b > 0)
    except Exception as e:
        # Fallback bei Fehler
        print(f"Error calculating balances: {e}")
        total_debts = 0.0
        total_player_credit = 0.0

    return render_template('kasse.html', 
                        balance=current_balance, 
                        prev_balance=prev_balance,
                        balance_diff=balance_diff,
                        prev_season_str=prev_season_str,
                        income=season_deposits, 
                        total_debts=total_debts, 
                        total_player_credit=total_player_credit, 
                        expenses=season_expenses,
                        total_expenses=season_expenses_sum,
                        current_team=team_name)

@app.route('/player/<int:player_id>')
@login_required
def player_detail(player_id):
    player = Player.query.get_or_404(player_id)
    settings_query = KasseSetting.query.all()
    settings = {s.key: s.value for s in settings_query}
    
    # Seasonal Transaction Data
    seasonal_money_tx = player.transactions.filter(
        Transaction.date.between(g.start_date, g.end_date)
    ).all()

    def calc_team_stats(tx_list):
        g_txs, f_txs, p_txs = [], [], []
        for tx in tx_list:
            if tx.amount < 0:
                if tx.description and 'gg.' in tx.description.lower():
                    g_txs.append(tx)
                elif tx.description != 'Startguthaben' and "Startguthaben" not in tx.description:
                    f_txs.append(tx)
            elif tx.amount > 0:
                 if tx.description != 'Startguthaben' and "Startguthaben" not in tx.description:
                    p_txs.append(tx)
        return {
            'num_games': len(g_txs),
            'total_fines': sum(t.amount for t in f_txs) * -1,
            'total_payments': sum(t.amount for t in p_txs)
        }

    tx_t1 = [t for t in seasonal_money_tx if t.team == 'team1']
    tx_t2 = [t for t in seasonal_money_tx if t.team != 'team1'] # treat None as Team 2 (Legacy)

    stats_t1 = calc_team_stats(tx_t1)
    stats_t2 = calc_team_stats(tx_t2)

    # Legacy support if template uses single player_stats (Summed up?)
    # Or just pass new stats. Template needs update anyway.
    # We keep 'player_stats' as TOTAL for compatibility if some part relies on it, 
    # but the requested feature is to split it.
    player_stats = calc_team_stats(seasonal_money_tx) # TOTAL

    balance_before_season = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.player_id == player_id, 
        Transaction.date < g.start_date
    ).scalar() or 0.0
    
    # Zusätzlich: Startguthaben aus Setup (falls vorhanden)
    startguthaben = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.player_id == player_id,
        Transaction.description == "Startguthaben"
    ).scalar() or 0.0
    
    # Gesamter Übertrag = Transaktionen vor Saison + Startguthaben
    total_carryover = balance_before_season + startguthaben
    
    kistl_before_season = db.session.query(func.sum(KistlTransaction.amount)).filter(
        KistlTransaction.player_id == player_id, 
        KistlTransaction.date < g.start_date
    ).scalar() or 0
    # --- START NEUE TRANSAKTIONSLOGIK MIT LAUFENDEM SALDO ---
    
    seasonal_kistl_tx = player.kistl_transactions.filter(KistlTransaction.date.between(g.start_date, g.end_date)).all()

    # 1. Sammeln aller Einträge mit Rohdaten für Berechnung
    processed_transactions = []
    
    # Startguthaben / Übertrag (Geld)
    if total_carryover != 0:
        processed_transactions.append({
            'date': g.start_date,
            'desc': 'Übertrag aus Vorsaison(en)',
            'amount_raw': total_carryover,
            'type': 'money',
            'is_carry_over': True,
            'category': None
        })
        
    # Saisonale Geld-Transaktionen
    for tx in seasonal_money_tx:
        if tx.description == 'Startguthaben': continue
        
        entry = {
            'date': tx.date,
            'desc': tx.description,
            'amount_raw': tx.amount,
            'type': 'money',
            'category': tx.category,
            'is_fine_unpaid': False,
            'did_not_play': False
        }
        
        if tx.amount == 0 and tx.description and 'gg.' in tx.description.lower():
            entry['did_not_play'] = True
        
        # Deadline Logik
        if tx.category == 'fine' and tx.amount < 0:
             settled = tx.amount_settled if tx.amount_settled is not None else 0.0
             if settled < abs(tx.amount) - 0.01:
                 # Not fully paid, check if doubled
                 if tx.doubled_by_id is None:
                     entry['is_fine_unpaid'] = True
                     entry['deadline'] = get_deadline(tx.date)
                     entry['days_left'] = (entry['deadline'] - datetime.utcnow().date()).days
        
        processed_transactions.append(entry)
        
    # SORTIERUNG AUFSTEIGEND für Saldo-Berechnung
    # Wenn Datum gleich: Übertrag (is_carry_over=True) kommt zuerst.
    # "not x.get..." : True -> False(0), False -> True(1). 0 kommt vor 1. Passt.
    processed_transactions.sort(key=lambda x: (x['date'], not x.get('is_carry_over', False)))
    
    current_balance = 0.0
    for entry in processed_transactions:
        # Nur Geldtransaktionen beeinflussen den Saldo
        if entry['type'] == 'money':
            current_balance += entry['amount_raw']
            entry['running_balance_raw'] = current_balance
            entry['running_balance'] = f"{current_balance:,.2f} €"
        
        entry['val'] = f"{entry['amount_raw']:,.2f} €"
        
    # KISTL Logic (beeinflusst Geld-Saldo nicht)
    if kistl_before_season != 0:
        processed_transactions.append({
            'date': g.start_date,
            'desc': 'Kistl-Übertrag aus Vorsaison(en)',
            'val': f"{kistl_before_season} Kistl",
            'type': 'kistl',
            'is_carry_over': True
        })

    for k in seasonal_kistl_tx:
        processed_transactions.append({
            'date': k.date,
            'desc': k.description,
            'val': f"{k.amount} Kistl",
            'type': 'kistl'
        })
        
    # Finale Sortierung ABSTEIGEND für Anzeige (Neueste zuerst)
    processed_transactions.sort(key=lambda x: (x['date'], not x.get('is_carry_over', False)), reverse=True)
    
    all_transactions = processed_transactions
    
    # --- ENDE NEUE TRANSAKTIONSLOGIK ---
    
    # --- KORRIGIERTE LOGIK ---
    # Wir brauchen die Liste der abonnierten Spieler nicht mehr im Template,
    # da das JavaScript die Info jetzt selbst vom Server holt.
    # Wir übergeben hier nur eine leere Liste, um Fehler zu vermeiden,
    # falls alte Referenzen noch irgendwo existieren.
    
    return render_template('player_detail.html', 
                           player=player, 
                           all_transactions=all_transactions, 
                           settings=settings,
                           player_stats=player_stats,
                           stats_t1=stats_t1,
                           stats_t2=stats_t2)
        
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    
    # MAGIC TOKEN HANDLING
    prefill_username = ""
    token = request.args.get('token')
    magic_user = None
    
    if token:
        # Versuch, den User zum Token zu finden
        magic_user = User.query.filter_by(login_token=token).first()
        if magic_user:
             prefill_username = magic_user.username
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        password_confirm = request.form['password_confirm']
        
        # Token aus Hidden Field holen (falls vorhanden)
        post_token = request.form.get('token')
        if post_token and not magic_user:
             magic_user = User.query.filter_by(login_token=post_token).first()

        if password != password_confirm:
            notify_admins("⚠️ Registrierung gescheitert", f"Versuch von '{username}': Passwörter stimmen nicht überein.")
            log_audit("REGISTER", "FAILED", f"Registrierung gescheitert für '{username}': Passwörter stimmen nicht überein.")
            flash('Die Passwörter stimmen nicht überein.', 'danger')
            return redirect(url_for('register', token=post_token) if post_token else url_for('register'))
            
        # Check if user already exists
        existing_user_by_name = User.query.filter_by(username=username).first()
        
        # Determine if this is a magic link upgrade (User Placeholder -> Real User)
        is_magic_upgrade = False
        
        # Fall 1: Wir haben einen Magic User via Token identifiziert und der Username im Form matcht
        if magic_user and existing_user_by_name and existing_user_by_name.id == magic_user.id:
             is_magic_upgrade = True
        
        # Fall 2: Kein Token, aber der existierende User ist ein Placeholder (manuelles Ausfüllen)
        elif existing_user_by_name and existing_user_by_name.is_placeholder:
             # Hier könnte man argumentieren, dass das unsicher ist, wenn jeder einfach Placeholder "claimen" kann.
             # Aber da Placeholder zufällige Passwörter haben und man sie nicht einloggen kann ohne Token,
             # ist das Überschreiben hier der einzige Weg, sie "in Besitz" zu nehmen.
             # Voraussetzung: Man kennt den exakten Namen.
             is_magic_upgrade = True
             magic_user = existing_user_by_name

        if existing_user_by_name and not is_magic_upgrade:
            notify_admins("⚠️ Registrierung gescheitert", f"Versuch von '{username}': Name bereits vergeben.")
            log_audit("REGISTER", "FAILED", f"Registrierung gescheitert für '{username}': Name bereits vergeben.")
            flash('Dieser Benutzername ist bereits vergeben.', 'danger')
            return redirect(url_for('register'))
            
        # Check if player exists (exact match required as per instructions)
        player = Player.query.filter_by(name=username).first()
        if not player:
            notify_admins("⚠️ Registrierung gescheitert", f"Versuch von '{username}': Spielername nicht in der Liste gefunden.")
            log_audit("REGISTER", "FAILED", f"Registrierung gescheitert für '{username}': Spielername nicht in der Liste.")
            flash(f'Spieler "{username}" nicht gefunden. Bitte Namen exakt wie in der Liste eingeben.', 'danger')
            return redirect(url_for('register'))
            
        # Check if player is already linked
        existing_user = User.query.filter_by(player_id=player.id).first()
        
        # Logic to handle upgrades or new users
        if existing_user:
            if existing_user.is_placeholder or is_magic_upgrade:
                # Upgrade placeholder user
                existing_user.username = username
                existing_user.set_password(password)
                existing_user.is_placeholder = False
                existing_user.login_token = None # Clear magic token to enforce password usage or re-generate later
                db.session.commit()
                
                notify_admins("✅ Benutzer Upgrade", f"Registrierung erfolgreich: '{username}' hat sein Konto aktiviert (Magic Link / Upgrade).")
                log_audit("REGISTER", "SUCCESS", f"Benutzer '{username}' hat Konto aktiviert (Upgrade).")
                login_user(existing_user, remember=True, duration=timedelta(days=3650)) # Valid for 10 years
                flash(f'Willkommen, {username}! Dein Konto wurde aktiviert und du wurdest angemeldet.', 'success')
                return redirect(url_for('index'))
            else:
                notify_admins("⚠️ Registrierung gescheitert", f"Versuch von '{username}': Spieler hat bereits ein Konto.")
                log_audit("REGISTER", "FAILED", f"Registrierung gescheitert für '{username}': Spieler hat bereits ein Konto.")
                flash('Für diesen Spieler existiert bereits ein Benutzerkonto.', 'warning')
                return redirect(url_for('login'))
            
        # Create User
        new_user = User(username=username, role='player', player_id=player.id)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        notify_admins("✅ Neuer Benutzer", f"Registrierung erfolgreich: '{username}' hat sich angemeldet.")
        log_audit("REGISTER", "SUCCESS", f"Benutzer '{username}' erfolgreich registriert.")
        
        # Sofort einloggen (Hürde senken) - 10 Jahre gültig
        login_user(new_user, remember=True, duration=timedelta(days=3650))
        flash(f'Willkommen, {username}! Du wurdest automatisch angemeldet.', 'success')
        
        return redirect(url_for('index'))
        
    return render_template('register.html', prefill_username=prefill_username, token=token)

# --- Rechtliches ---
@app.route('/impressum')
def impressum():
    return render_template('impressum.html')

@app.route('/datenschutz')
def datenschutz():
    return render_template('datenschutz.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            # "Angemeldet bleiben" Feature für PWA
            remember_me = request.form.get('remember_me') == 'true'
            
            if remember_me:
                # Permanente Session für PWA (30 Tage)
                session.permanent = True
                login_user(user, remember=True, duration=timedelta(days=30))
                log_audit("LOGIN", "SUCCESS", f"Benutzer '{user.username}' erfolgreich eingeloggt (Remember Me).")
            else:
                # Standard Session (bis Browser geschlossen wird)
                login_user(user, remember=False)
                log_audit("LOGIN", "SUCCESS", f"Benutzer '{user.username}' erfolgreich eingeloggt.")
            
            # --- PUSH FIX: Abo direkt beim Login verarbeiten (spart Permission Dialog auf iOS) ---
            push_sub_json = request.form.get('push_subscription')
            
            if push_sub_json and user.player_id:
                try:
                    import json
                    sub_data = json.loads(push_sub_json)
                    endpoint = sub_data.get('endpoint')
                    if endpoint:
                        # Bereinigung alter Einträge dieses Endpoints
                        PushSubscription.query.filter_by(endpoint=endpoint).delete()
                        
                        # Neuen Eintrag erstellen
                        new_sub = PushSubscription(
                            player_id=user.player_id, 
                            subscription_json=push_sub_json, 
                            endpoint=endpoint
                        )
                        db.session.add(new_sub)
                        db.session.commit()
                except Exception:
                    # Login fortsetzen, auch wenn Push-Registrierung fehlschlägt
                    db.session.rollback()

            return redirect(url_for('index', login=1))
        else: 
            flash('Ungültiger Benutzername oder Passwort.', 'danger')
            log_audit("LOGIN", "FAILED", f"Login-Versuch gescheitert für '{request.form.get('username')}'.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Session komplett bereinigen
    log_audit("LOGOUT", "SUCCESS", f"Benutzer '{current_user.username}' hat sich ausgeloggt.")
    logout_user()
    session.clear()
    
    # Cache-Control Headers für sauberen Logout
    response = make_response(redirect(url_for('login')))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    # Explizit das Remember-Cookie löschen
    response.delete_cookie('remember_token')
    
    return response

# --- Role Switching ---
@app.route('/switch-role/<target_role>')
@login_required
def switch_role(target_role):
    # Only allow switching if the USER actually has admin rights basically (real_role)
    # OR if they have a secondary_role and are switching to it, or resetting to their real_role.
    
    if not hasattr(current_user, 'real_role'):
         # Fallback if load_user logic failed somehow
         current_user.real_role = current_user.role

    is_admin = current_user.real_role == 'admin'
    is_switching_to_secondary = (target_role == getattr(current_user, 'secondary_role', None))

    if not is_admin and target_role != 'reset' and not is_switching_to_secondary:
        flash("Keine Berechtigung zum Wechseln in diese Rolle.", "danger")
        return redirect(url_for('index'))

    if target_role == 'reset':
        session.pop('active_role_override', None)
        if is_admin:
            flash("Ansicht zurückgesetzt.", "success")
        else:
            flash(f"Arbeitsbereich gewechselt zu: {current_user.real_role.replace('_', ' ').title()}", "success")
    else:
        if target_role in VALID_ROLES and target_role != 'admin':
            session['active_role_override'] = target_role
            flash(f"Arbeitsbereich gewechselt zu: {target_role.replace('_', ' ').title()}", "info")
        else:
            flash("Ungültige Rolle.", "danger")
    
    log_audit("SECURITY", "ROLE_SWITCH", f"Rolle/Arbeitsbereich gewechselt zu: {target_role}")
    return redirect(request.referrer or url_for('index'))

# ---- WEBAUTHN / BIOMETRISCHE LOGIN FEATURES ----

@app.route('/webauthn/register/options', methods=['POST'])
@login_required
def webauthn_register_options():
    if generate_registration_options is None:
        return jsonify({'error': 'WebAuthn-Bibliothek nicht geladen. Bitte "pip install webauthn" auf dem Server ausführen.'}), 500
        
    user_id_bytes = str(current_user.id).encode('utf-8')
    
    # Sicherstellen, dass keine DetachedInstanceError auftreten kann
    existing_db_creds = WebAuthnCredential.query.filter_by(user_id=current_user.id).all()
    
    existing_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(cred.id))
        for cred in existing_db_creds
    ]
    
    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=user_id_bytes,
        user_name=current_user.username,
        user_display_name=current_user.username,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=existing_credentials,
    )
    
    session['webauthn_registration_challenge'] = bytes_to_base64url(options.challenge)
    return Response(options_to_json(options), mimetype='application/json')

@app.route('/webauthn/register/verify', methods=['POST'])
@login_required
def webauthn_register_verify():
    if verify_registration_response is None:
        return jsonify({'error': 'WebAuthn-Bibliothek nicht geladen.'}), 500
        
    registration_response = request.get_json()
    expected_challenge = session.pop('webauthn_registration_challenge', None)
    
    if not expected_challenge:
        return jsonify({'error': 'Missing registration challenge'}), 400
        
    try:
        
        verification = verify_registration_response(
            credential=registration_response,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            require_user_verification=False,
        )
        
        cid = bytes_to_base64url(verification.credential_id)
        new_credential = WebAuthnCredential(
            id=cid,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=json.dumps(registration_response.get('response', {}).get('transports', []) if isinstance(registration_response, dict) else []),
            user_id=current_user.id
        )
        
        db.session.add(new_credential)
        db.session.commit()
        
        log_audit("SECURITY", "WEBAUTHN_REG", f"Biometrisches Gerät für User '{current_user.username}' registriert.")
        return jsonify({'success': True, 'message': 'Gerät erfolgreich registriert!'})
        
    except Exception as e:
        app.logger.error(f"WebAuthn registration error: {e}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': f'Registrierung fehlgeschlagen: {str(e)}'}), 400

@app.route('/webauthn/login/options', methods=['POST'])
def webauthn_login_options():
    if generate_authentication_options is None:
        return jsonify({'error': 'WebAuthn-Bibliothek nicht geladen.'}), 500

    try:
        options = generate_authentication_options(
            rp_id=WEBAUTHN_RP_ID,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        
        session['webauthn_authentication_challenge'] = bytes_to_base64url(options.challenge)
        
        return Response(options_to_json(options), mimetype='application/json')
    except Exception as e:
        app.logger.error(f"WebAuthn login options error: {e}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': f'Fehler: {str(e)}'}), 500

@app.route('/webauthn/login/verify', methods=['POST'])
def webauthn_login_verify():
    if verify_authentication_response is None:
        return jsonify({'error': 'WebAuthn library not loaded'}), 500
        
    authentication_response = request.get_json()
    expected_challenge = session.pop('webauthn_authentication_challenge', None)
    
    if not expected_challenge:
        return jsonify({'error': 'Authentication session expired or missing'}), 400
    
    # Get user from userHandle (set during registration as user_id)
    user_handle = authentication_response.get('response', {}).get('userHandle')
    if not user_handle:
        return jsonify({'error': 'Kein Benutzer im Passkey gefunden.'}), 400
    
    try:
        user_id_str = base64url_to_bytes(user_handle).decode('utf-8')
        user = db.session.get(User, int(user_id_str))
    except Exception:
        return jsonify({'error': 'Ungültiger Benutzer im Passkey.'}), 400
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    # Find the specific credential
    credential_id = authentication_response.get('id')
    db_credential = db.session.get(WebAuthnCredential, credential_id)
    
    if not db_credential:
        return jsonify({'error': 'Passkey nicht gefunden. Bitte erneut registrieren.'}), 400
    if db_credential.user_id != user.id:
        return jsonify({'error': 'Passkey gehört nicht zu diesem Benutzer.'}), 400
        
    try:
        verification = verify_authentication_response(
            credential=authentication_response,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            credential_public_key=db_credential.public_key,
            credential_current_sign_count=db_credential.sign_count,
            require_user_verification=False,
        )
        
        # Update sign count to prevent replay attacks
        db_credential.sign_count = verification.new_sign_count
        db.session.commit()
        
        # Log the user in
        login_user(user, remember=True)
        log_audit("LOGIN", "WEBAUTHN_SUCCESS", f"Biometrischer Login erfolgreich für User '{user.username}'.")
        
        return jsonify({'success': True, 'redirect': url_for('index')})
        
    except Exception as e:
        app.logger.error(f"WebAuthn authentication error: {e}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': f'Authentifizierung fehlgeschlagen: {str(e)}'}), 400

@app.route('/webauthn/credentials', methods=['GET'])
@login_required
def webauthn_get_credentials():
    creds = WebAuthnCredential.query.filter_by(user_id=current_user.id).all()
    return jsonify([
        {
            'id': c.id,
            'created_at': c.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'sign_count': c.sign_count
        } for c in creds
    ])

@app.route('/webauthn/credentials/<credential_id>', methods=['DELETE'])
@login_required
def webauthn_delete_credential(credential_id):
    cred = db.session.get(WebAuthnCredential, credential_id)
    if not cred or cred.user_id != current_user.id:
        return jsonify({'error': 'Credential not found'}), 404
        
    db.session.delete(cred)
    db.session.commit()
    log_audit("SECURITY", "WEBAUTHN_DELETE", f"Biometrisches Gerät gelöscht für User '{current_user.username}'.")
    return jsonify({'success': True})

# ---- MAGIC LINK FEATURES ----

@app.route('/generate_magic_link/<int:player_id>', methods=['POST'])
@login_required
def generate_magic_link(player_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    player = Player.query.get_or_404(player_id)
    user = User.query.filter_by(player_id=player.id).first()
    
    if not user:
        # Create user if not exists
        # Name: Spielername. Passwort: Random (wird nie genutzt)
        user = User(username=player.name, role='player', player_id=player.id, is_placeholder=True)
        # 32 bytes random string
        user.set_password(secrets.token_urlsafe(32)) 
        db.session.add(user)
    
    # Generate new token with expiry (7 Tage)
    token_core = secrets.token_urlsafe(32)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp())
    full_token = f"{token_core}|{expiry}"
    
    user.login_token = full_token
    db.session.commit()
    
    log_audit("SECURITY", "MAGIC_LINK_GEN", f"Magic Link für Spieler '{player.name}' generiert.")
    
    link = url_for('magic_login', token=full_token, _external=True)
    return jsonify({'link': link, 'message': f'Magic Link für {player.name} erstellt!'})

@app.route('/auth/token/<token>')
def magic_login(token):
    user = User.query.filter_by(login_token=token).first()
    
    valid = False
    if user:
        try:
            # Check for expiry format
            if '|' in token:
                parts = token.split('|')
                if len(parts) == 2:
                    expiry = int(parts[1])
                    if datetime.utcnow().timestamp() < expiry:
                        valid = True
            else:
                valid = False 
        except Exception:
            valid = False

    if not valid:
        flash('Dieser Einladungs-Link ist ungültig oder abgelaufen.', 'danger')
        log_audit("LOGIN", "MAGIC_FAILED", "Login via Magic Link gescheitert (Token ungültig/abgelaufen).")
        return redirect(url_for('login'))
        
    # LOGIC UPDATE: Wenn User noch "Placeholder" ist -> Redirect zur Registrierung (Namen vorbefüllen)
    if user.is_placeholder:
        # Wir leiten zur Registrierungsseite weiter und übergeben den Token oder Namen
        # Da der Name evtl. Leerzeichen enthält, wird er URL-kodiert
        flash(f'Hallo {user.username}! Bitte lege ein Passwort fest, um deinen Zugang zu aktivieren.', 'info')
        return redirect(url_for('register', token=token))
        
    # Log user in standardmäßig
    login_user(user, remember=True)
    
    # Token invalidieren (Sicherheit: Einmaliger Login - außer es wäre gewünscht, dass der Link mehrmals geht, was aber unsicher ist)
    # user.login_token = None  
    # Wenn wir den Token hier löschen, kann er nicht nochmal verwendet werden. Das ist korrekt so.
    user.login_token = None
    db.session.commit()
    
    flash(f'Willkommen, {user.username}! Du hast dich erfolgreich per Link angemeldet.', 'success')
    log_audit("LOGIN", "MAGIC_LINK", f"Login via Magic Link erfolgreich für '{user.username}'.")
    return redirect(url_for('index'))

# ---- GUEST ACCESS FEATURES ----

@app.route('/generate_guest_link', methods=['POST'])
@login_required
@role_required(['admin'])
def generate_guest_link():
    """Generiert einen Link für Gastzugriff (View-Only), gültig für 7 Tage."""
    
    # 1. Sicherstellen, dass ein Gast-User existiert
    guest_user = User.query.filter_by(username='gast_view').first()
    if not guest_user:
        guest_user = User(username='gast_view', role='guest', is_placeholder=True) 
        guest_user.set_password(secrets.token_urlsafe(32))
        db.session.add(guest_user)
    else:
        # SICHERSTELLEN, dass die Rolle korrekt ist (falls durch alte Bugs 'admin' war)
        if guest_user.role != 'guest':
            guest_user.role = 'guest'
            db.session.add(guest_user)
    
    db.session.commit()
        
    # 2. Token generieren und speichern (in Settings)
    token = secrets.token_urlsafe(16)
    
    # Speichern in Settings mit Timestamp
    # Format: token|expiry_timestamp
    expiry = datetime.utcnow() + timedelta(days=7)
    token_value = f"{token}|{expiry.timestamp()}"
    
    setting = KasseSetting.query.filter_by(key='guest_token').first()
    if setting:
        setting.value = token_value
    else:
        db.session.add(KasseSetting(key='guest_token', value=token_value))
    
    db.session.commit()
    
    log_audit("SECURITY", "GUEST_LINK_GEN", "Gast-Zugangslink generiert.")
    
    link = url_for('guest_login', token=token, _external=True)
    return jsonify({'link': link, 'message': 'Gast-Link erstellt (7 Tage gültig).'})

@app.route('/auth/guest/<token>')
def guest_login(token):
    setting = KasseSetting.query.filter_by(key='guest_token').first()
    if not setting or not setting.value:
        flash('Kein gültiger Gast-Link gefunden.', 'danger')
        log_audit("LOGIN", "GUEST_FAILED", "Gast-Login gescheitert (Kein Setting vorhanden).")
        return redirect(url_for('login'))
        
    try:
        stored_token, expiry_ts = setting.value.split('|')
    except ValueError:
        flash('Fehlerhafter Token in Datenbank.', 'danger')
        return redirect(url_for('login'))
    
    if token != stored_token:
        flash('Ungültiger Link.', 'danger')
        log_audit("LOGIN", "GUEST_FAILED", "Gast-Login gescheitert (Token mismatch).")
        return redirect(url_for('login'))
        
    if datetime.utcnow().timestamp() > float(expiry_ts):
        flash('Dieser Gast-Link ist abgelaufen.', 'danger')
        log_audit("LOGIN", "GUEST_FAILED", "Gast-Login gescheitert (Token abgelaufen).")
        return redirect(url_for('login'))
        
    # Login als Gast-User
    guest_user = User.query.filter_by(username='gast_view').first()
    if not guest_user:
        # Fallback create
        guest_user = User(username='gast_view', role='guest', is_placeholder=True)
        guest_user.set_password(secrets.token_urlsafe(32))
        db.session.add(guest_user)
        db.session.commit()
    elif guest_user.role != 'guest':
        # Auto-Correction
        guest_user.role = 'guest'
        db.session.commit()
        
    # Login für die Session
    login_user(guest_user, remember=True, duration=timedelta(days=7))
    log_audit("LOGIN", "GUEST_LINK", "Gast-Login erfolgreich.")
    flash('Als Gast angemeldet (Eingeschränkter Zugriff).', 'info')
    
    # Check if trigger_push_init is set in session? No need for guest.
    
    return redirect(url_for('index'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if not current_user.check_password(current_password):
            log_audit("SECURITY", "PASSWORD_CHANGE_FAILED", f"Passwortänderung gescheitert für '{current_user.username}': Aktuelles Passwort falsch.")
            flash('Das aktuelle Passwort ist nicht korrekt.', 'danger')
            return redirect(url_for('change_password'))
        if not new_password:
            flash('Das neue Passwort darf nicht leer sein.', 'danger')
            return redirect(url_for('change_password'))
        if new_password != confirm_password:
            flash('Die neuen Passwörter stimmen nicht überein.', 'danger')
            return redirect(url_for('change_password'))
        # Get a fresh user instance. If current_user has a role override,
        # it has been expunged and modifications won't be saved by the session.
        db_user = User.query.get(current_user.id)
        db_user.set_password(new_password)
        db.session.commit()
        log_audit("SECURITY", "PASSWORD_CHANGE", f"Passwort für '{current_user.username}' wurde geändert.")
        flash('Dein Passwort wurde erfolgreich geändert.', 'success')
        return redirect(url_for('index'))
    return render_template('change_password.html')

# --- NEUE FUNKTION: Saisonabschluss-Bericht ---
@app.route('/admin/report/season')
@login_required
@role_required(['admin'])
def generate_season_report():
    try:
        # 1. Daten sammeln
        
        # Holen der Startguthaben-Einstellungen
        start_balance_legacy = KasseSetting.query.filter_by(key='start_balance').first()
        start_balance_t1_set = KasseSetting.query.filter_by(key='start_balance_team1').first()
        start_balance_t2_set = KasseSetting.query.filter_by(key='start_balance_team2').first()
        
        initial_val_t1 = float(start_balance_t1_set.value) if start_balance_t1_set else 0.0
        # Fallback: Wenn Team 2 specific nicht gesetzt ist, nutze Legacy "start_balance"
        if start_balance_t2_set:
            initial_val_t2 = float(start_balance_t2_set.value)
        else:
            initial_val_t2 = float(start_balance_legacy.value) if start_balance_legacy else 0.0
            
        # Berechne den Kassenstand ZU BEGINN der ausgewählten Saison PRO TEAM
        # Einkommen vor Saison
        total_deposits_before_t1 = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.date < g.start_date,
            Transaction.team == 'team1'
        ).scalar() or 0.0
        
        total_deposits_before_t2 = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.date < g.start_date,
            (Transaction.team == 'team2') | (Transaction.team == None)
        ).scalar() or 0.0
        
        # Ausgaben vor Saison
        total_expenses_before_t1 = db.session.query(func.sum(TeamExpense.amount)).filter(
            TeamExpense.date < g.start_date,
            TeamExpense.team == 'team1'
        ).scalar() or 0.0
        
        total_expenses_before_t2 = db.session.query(func.sum(TeamExpense.amount)).filter(
            TeamExpense.date < g.start_date,
            (TeamExpense.team == 'team2') | (TeamExpense.team == None)
        ).scalar() or 0.0
        
        kasse_balance_at_season_start_t1 = initial_val_t1 + total_deposits_before_t1 - total_expenses_before_t1
        kasse_balance_at_season_start_t2 = initial_val_t2 + total_deposits_before_t2 - total_expenses_before_t2
        
        # Gesamt Start
        kasse_balance_at_season_start = kasse_balance_at_season_start_t1 + kasse_balance_at_season_start_t2

        # Berechne Einnahmen und Ausgaben INNERHALB der Saison (Gesamt)
        income_this_season = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.date.between(g.start_date, g.end_date),
            Transaction.amount > 0,
            Transaction.description != "Startguthaben"
        ).scalar() or 0.0
        
        # Breakdown Team 1
        income_team1 = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.date.between(g.start_date, g.end_date),
            Transaction.amount > 0,
            Transaction.description != "Startguthaben",
            Transaction.team == 'team1'
        ).scalar() or 0.0
        
        # Breakdown Team 2 (Rest)
        income_team2 = income_this_season - income_team1
        
        expenses_this_season_list = TeamExpense.query.filter(
            TeamExpense.date.between(g.start_date, g.end_date)
        ).order_by(TeamExpense.date).all()
        expenses_total_this_season = sum(e.amount for e in expenses_this_season_list)

        expenses_team1 = sum(e.amount for e in expenses_this_season_list if e.team == 'team1')
        expenses_team2 = expenses_total_this_season - expenses_team1

        # Berechne den Kassenstand AM ENDE der Saison PRO TEAM
        kasse_balance_at_season_end_t1 = kasse_balance_at_season_start_t1 + income_team1 - expenses_team1
        kasse_balance_at_season_end_t2 = kasse_balance_at_season_start_t2 + income_team2 - expenses_team2
        
        kasse_balance_at_season_end = kasse_balance_at_season_end_t1 + kasse_balance_at_season_end_t2

        # Hole die finalen Salden ALLER Spieler (aktiv + archiviert) am Ende der Saison
        player_final_balances = []
        players = Player.query.all() # Reload all for report
        players.sort(key=get_lastname_sort_key)
        for p in players:
            # Gesamter Geldsaldo bis zum Saisonende
            money_balance = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.player_id == p.id,
                Transaction.date <= g.end_date
            ).scalar() or 0.0
            
            money_balance_t1 = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.player_id == p.id,
                Transaction.date <= g.end_date,
                Transaction.team == 'team1'
            ).scalar() or 0.0
            
            money_balance_t2 = money_balance - money_balance_t1
            
            # Gesamter Kistlsaldo bis zum Saisonende
            kistl_balance = db.session.query(func.sum(KistlTransaction.amount)).filter(
                KistlTransaction.player_id == p.id,
                KistlTransaction.date <= g.end_date
            ).scalar() or 0

            if abs(money_balance) > 0.01 or kistl_balance > 0:
                player_final_balances.append({
                    'name': p.name,
                    'money_balance': money_balance,
                    'money_balance_t1': money_balance_t1,
                    'money_balance_t2': money_balance_t2,
                    'kistl_balance': kistl_balance
                })
            
        # 2. HTML-Template mit den Daten rendern
        report_context = {
            "season_str": g.current_season_str,
            "generation_date": datetime.now(),
            "kasse_start": kasse_balance_at_season_start,
            "kasse_start_t1": kasse_balance_at_season_start_t1,
            "kasse_start_t2": kasse_balance_at_season_start_t2,
            "kasse_end": kasse_balance_at_season_end,
            "kasse_end_t1": kasse_balance_at_season_end_t1,
            "kasse_end_t2": kasse_balance_at_season_end_t2,
            "season_income": income_this_season,
            "income_team1": income_team1,
            "income_team2": income_team2,
            "season_expenses_total": expenses_total_this_season,
            "expenses_team1": expenses_team1,
            "expenses_team2": expenses_team2,
            "player_balances": player_final_balances,
            "expense_details": expenses_this_season_list
        }
        
        html_string = render_template('_season_report_template.html', **report_context)

        # 3. PDF aus dem gerenderten HTML erstellen
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        # 4. PDF als Datei-Download zurückgeben
        filename = f"Saisonbericht_{g.current_season_str.replace('/', '-')}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        
        log_audit("DOWNLOAD", "SEASON_REPORT", f"Saisonbericht für '{g.current_season_str}' heruntergeladen.")
        return send_file(
            io.BytesIO(pdf_bytes),
            download_name=filename,
            as_attachment=True,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Fehler beim Erstellen des PDF-Berichts: {e}")
        flash(f"Konnte PDF-Bericht nicht erstellen: {e}", "danger")
        return redirect(url_for('admin'))

@app.route('/schulden/settle-kistl/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def settle_kistl_cockpit(player_id):
    player = Player.query.get_or_404(player_id)
    try:
        tx = KistlTransaction(player_id=player.id, description="Kistl beglichen (via Cockpit)", amount=1, date=datetime.utcnow().date(), created_by=current_user.username)
        db.session.add(tx)
        log_audit("UPDATE", "KISTL_SETTLEMENT", f"Kistl für {player.name} beglichen (Cockpit-Schnellauswahl).")
        flash(f'Ein Kistl für {player.name} wurde als beglichen markiert.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Begleichen des Kistls: {e}', 'danger')
    return redirect(url_for('schulden'))

@app.route('/schulden')
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2', 'viewer']) # Guest excluded, Viewer included
def schulden():
    all_active_players = Player.query.filter_by(is_active=True).all()
    # Nur Spieler mit Schulden
    debtors = [p for p in all_active_players if p.balance_team1 < 0 or p.balance_team2 < 0 or p.kistl_balance < 0]
    
    # Sortieren nach Gesamtschulden (Summe aus beiden Teams) (Primär)
    # Und Alphabetisch (Sekundär)
    debtors.sort(key=lambda p: (
        (p.balance_team1 + p.balance_team2), 
        get_lastname_sort_key(p)
    ))

    settings_query = KasseSetting.query.all()
    settings = {s.key: s.value for s in settings_query}
    
    lnk_t1_gen = settings.get('paypal_link_team1_general', '')
    lnk_t1_fine = settings.get('paypal_link_team1_fine', '')
    lnk_t2_gen = settings.get('paypal_link_team2_general', '')
    lnk_t2_fine = settings.get('paypal_link_team2_fine', '')
    
    mail_t1_gen = settings.get('paypal_email_team1_general', '')
    mail_t1_fine = settings.get('paypal_email_team1_fine', '')
    mail_t2_gen = settings.get('paypal_email_team2_general', '')
    mail_t2_fine = settings.get('paypal_email_team2_fine', '')

    # --- HILFSFUNKTION FÜR PAYPAL-BLOCK ---
    def build_paypal_text(gen_link, fine_link, team_name, mail_gen="", mail_fine=""):
        if not gen_link and not fine_link:
            return f"{team_name}: Bitte bar bezahlen!"
        
        lines = []
        if gen_link == fine_link:
            line = f"{team_name} Gesamt: ➡ {gen_link}"
            if mail_gen: line += f" ({mail_gen})"
            lines.append(line)
        else:
            if gen_link:
                line_gen = f"{team_name} Trikot/Sonstiges: ➡ {gen_link}"
                if mail_gen: line_gen += f" ({mail_gen})"
            else:
                line_gen = f"{team_name} Trikot/Sonstiges: Bitte bar bezahlen!"
            lines.append(line_gen)
            
            if fine_link:
                line_fine = f"{team_name} Strafen: ➡ {fine_link}"
                if mail_fine: line_fine += f" ({mail_fine})"
            else:
                line_fine = f"{team_name} Strafen: Bitte bar bezahlen!"
            lines.append(line_fine)
            
        return "\n".join(lines)
    
    # PayPal Block für Bildnachricht (Beide Teams)
    t1_block = build_paypal_text(lnk_t1_gen, lnk_t1_fine, "Erste", mail_t1_gen, mail_t1_fine)
    t2_block = build_paypal_text(lnk_t2_gen, lnk_t2_fine, "Zweite", mail_t2_gen, mail_t2_fine)
    
    has_any_link = any([lnk_t1_gen, lnk_t1_fine, lnk_t2_gen, lnk_t2_fine])
    if has_any_link:
        paypal_lines_all = ["Zahlung per PayPal (wichtig: als 'Freunde und Familie' senden!):", "Achtung: Bitte je nach Mannschaft (und Trikot/Strafe) den richtigen Link verwenden!"]
        if t1_block: paypal_lines_all.append(t1_block)
        if t2_block: paypal_lines_all.append(t2_block)
        paypal_msg_block = "\n".join(paypal_lines_all) + "\n\n"
    else:
        paypal_msg_block = "Bitte bei der Versammlung bar bezahlen.\n\n"

    # paypal blocks for individual teams
    has_t1_link = bool(lnk_t1_gen or lnk_t1_fine)
    if has_t1_link:
        paypal_msg_block_t1 = "Zahlung per PayPal (wichtig: als 'Freunde und Familie' senden!):\n" + t1_block + "\n\n"
    else:
        paypal_msg_block_t1 = "Erste: Bitte bar bezahlen!\n\n"
        
    has_t2_link = bool(lnk_t2_gen or lnk_t2_fine)
    if has_t2_link:
        paypal_msg_block_t2 = "Zahlung per PayPal (wichtig: als 'Freunde und Familie' senden!):\n" + t2_block + "\n\n"
    else:
        paypal_msg_block_t2 = "Zweite: Bitte bar bezahlen!\n\n"

    base_url = request.url_root
    full_url_all = f"{base_url}"
    full_url_t1 = f"{base_url}"
    full_url_t2 = f"{base_url}"

    # --- MANAGER NAMEN ERMITTELN OHNE DOPPELUNGEN ---
    def get_team_managers(role_name_1, role_name_2):
        users = User.query.filter(
            (User.role.in_([role_name_1, role_name_2])) | 
            (User.secondary_role.in_([role_name_1, role_name_2]))
        ).all()
        names = set()
        for u in users:
            if u.player:
                names.add(u.player.name)
            else:
                names.add(u.username)
        
        if not names:
            return "den Managern"
            
        return " und ".join(sorted(names))

    mgrs_t1 = get_team_managers('trikot_manager_1', 'strafen_manager_1')
    mgrs_t2 = get_team_managers('trikot_manager_2', 'strafen_manager_2')

    mgr_t1_text = f"Zusätzlich kann bar bei {mgrs_t1} bezahlt werden."
    mgr_t2_text = f"Zusätzlich kann bar bei {mgrs_t2} bezahlt werden."

    # Generiere WhatsApp-Texte mit PayPal-Links
    app_hint = "\n💡 Tipp: Ihr könnt die Kasse direkt als App auf dem Handy installieren!"
    msg_all = f"Hier ist die aktuelle Übersicht der Mannschaftskasse Gesamt.\nBitte begleicht eure Schulden zeitnah.\n\n{paypal_msg_block}\nErste:\n{mgr_t1_text}\n\nZweite:\n{mgr_t2_text}\n\nDie Details seht ihr hier: {full_url_all}\n{app_hint}"
    msg_t1 = f"Hier ist die aktuelle Übersicht der Mannschaftskasse Erste.\nBitte begleicht eure Schulden zeitnah.\n\n{paypal_msg_block_t1}\nErste:\n{mgr_t1_text}\n\nDie Details seht ihr hier: {full_url_t1}\n{app_hint}"
    msg_t2 = f"Hier ist die aktuelle Übersicht der Mannschaftskasse Zweite.\nBitte begleicht eure Schulden zeitnah.\n\n{paypal_msg_block_t2}\nZweite:\n{mgr_t2_text}\n\nDie Details seht ihr hier: {full_url_t2}\n{app_hint}"

    return render_template('schulden.html', 
                           debtors=debtors, 
                           msg_all=msg_all,
                           msg_t1=msg_t1,
                           msg_t2=msg_t2)
# Wiederhergestellte, Unicode-fähige Bildroute für die Schulden-Übersicht
# --- IMAGE GENERATION HELPER (BACKGROUND & CACHING) ---
def trigger_image_regeneration():
    """Startet die Hintergrund-Generierung der Schuldenbilder."""
    def task():
        with app.app_context():
            # Kurzes Delay, damit die DB-Transaktion des Aufrufers sicher abgeschlossen ist
            time.sleep(1) 
            _regenerate_all_images()
    
    # Thread starten (Daemon=False, damit er zu Ende läuft)
    t = threading.Thread(target=task, daemon=False)
    t.start()

def _regenerate_all_images():
    """Generiert synchron alle Bildvarianten und aktualisiert den Cache."""
    try:
        # print("DEBUG: Regenerating debt images cache...")
        global fines_image_cache
        
        # 3 Varianten generieren
        modes = ['all', 'team1', 'team2']
        for m in modes:
            img_bytes = _generate_debt_image_bytes(m)
            if img_bytes:
                fines_image_cache[m] = img_bytes
                
        # print("DEBUG: Debt images cache updated.")
    except Exception as e:
        app.logger.error(f"Error regenerating images: {e}")

def _generate_debt_image_bytes(filter_mode):
    """Core logic für die Bilderzeugung using Pillow."""
    try:
        if Image is None or ImageDraw is None or ImageFont is None:
            return None

        all_active_players = Player.query.filter_by(is_active=True).all()
        debtors = []
        creditors = []
        
        # --- FILTER LOGIC ---
        if filter_mode == 'team1':
            # Nur Spieler mit Schulden/Guthaben bei Team 1
            relevant = [p for p in all_active_players if (abs(p.balance_team1) > 0.001 or p.kistl_balance != 0)]
            debtors = [p for p in relevant if (p.balance_team1 < 0 or p.kistl_balance < 0)]
            debtor_set = set(debtors)
            creditors = [p for p in relevant if p not in debtor_set]
            debtors.sort(key=lambda p: (p.balance_team1, p.kistl_balance))
            creditors.sort(key=lambda p: (p.balance_team1, p.kistl_balance), reverse=True)
            title = 'Schuldenübersicht (1. Mannschaft)'
            
        elif filter_mode == 'team2':
            relevant = [p for p in all_active_players if (abs(p.balance_team2) > 0.001 or p.kistl_balance != 0)]
            debtors = [p for p in relevant if (p.balance_team2 < 0 or p.kistl_balance < 0)]
            debtor_set = set(debtors)
            creditors = [p for p in relevant if p not in debtor_set]
            debtors.sort(key=lambda p: (p.balance_team2, p.kistl_balance))
            creditors.sort(key=lambda p: (p.balance_team2, p.kistl_balance), reverse=True)
            title = 'Schuldenübersicht (2. Mannschaft)'
            
        else:
            # Debtor if ANY team has debt or kistl is negative
            debtors = [p for p in all_active_players if p.balance_team1 < -0.01 or p.balance_team2 < -0.01 or p.kistl_balance < 0]
            # Sort: money debts first (0), then kistl-only (1); within each group by total balance
            debtors.sort(key=lambda p: (0 if (p.balance_team1 < -0.01 or p.balance_team2 < -0.01) else 1, p.balance_team1 + p.balance_team2, p.kistl_balance))
            debtor_set = set(debtors)
            creditors = [p for p in all_active_players if p not in debtor_set]
            creditors.sort(key=lambda p: (p.balance_team1 + p.balance_team2, p.kistl_balance), reverse=True)
            title = 'Schuldenübersicht (Gesamt)'

        sequence = debtors + creditors

        # --- PREMIUM CONFIGURATION (2x Retina) ---
        S = 2  # Scale factor for high-res output
        width = (1500 if filter_mode == 'all' else 1650) * S
        padding_x = 30 * S
        header_height = 80 * S
        base_row_height = 52 * S
        
        player_heights = []
        player_unpaid_fines = []
        for p in sequence:
            if filter_mode in ['team1', 'team2']:
                tm = filter_mode
                p_fines = [t for t in p.transactions if t.category == 'fine' and t.team == tm and t.amount < 0]
                unpaid = [f for f in sorted(p_fines, key=lambda x: x.date, reverse=False) if (getattr(f, 'amount_settled', 0.0) or 0.0) < abs(f.amount) - 0.01]
                player_unpaid_fines.append(unpaid)
                gen_bal = getattr(p, f'general_balance_{tm}')
                fine_bal = getattr(p, f'fine_balance_{tm}')
                if (gen_bal + fine_bal < 0) and unpaid:
                    h = max(base_row_height, (len(unpaid) * 22 * S) + 20 * S)
                    player_heights.append(h)
                else:
                    player_heights.append(base_row_height)
            else:
                player_unpaid_fines.append([])
                player_heights.append(base_row_height)
                
        column_header_height = (58 if filter_mode == 'all' else 38) * S
        accent_line_height = 3 * S
        
        # Premium color palette
        COLOR_BG = (250, 251, 252)
        COLOR_HEADER_BG_TOP = (30, 41, 59)
        COLOR_HEADER_BG_BOT = (15, 23, 42)
        COLOR_HEADER_TEXT = (241, 245, 249)
        COLOR_TEXT = (33, 37, 41)
        COLOR_TEXT_LIGHT = (100, 116, 139)
        COLOR_ROW_ALT = (241, 245, 249) 
        COLOR_ROW_WHITE = (255, 255, 255)
        COLOR_DEBT = (220, 38, 38)
        COLOR_CREDIT = (22, 163, 74)
        COLOR_WARNING = (234, 88, 12)
        COLOR_LINE = (226, 232, 240)
        COLOR_ACCENT = (16, 185, 129)
        COLOR_COL_HEADER_BG = (241, 245, 249)
        COLOR_COL_HEADER_TEXT = (51, 65, 85)

        num_rows = len(sequence)
        total_height = header_height + accent_line_height + column_header_height + sum(player_heights) + 40 * S

        img = Image.new('RGBA', (width, total_height), COLOR_BG)
        draw = ImageDraw.Draw(img)

        # --- FONTS (scaled) ---
        def load_font(name_list, size, _cache={}):
            cache_key = (tuple(name_list), size)
            if cache_key in _cache:
                return _cache[cache_key]

            for name in name_list:
                paths = [
                    os.path.join(basedir, 'static', 'app', 'fonts', name),
                    f'C:\\Windows\\Fonts\\{name}',
                    f'/usr/share/fonts/truetype/{name.split(".")[0]}/{name}',
                    f'/usr/share/fonts/truetype/dejavu/{name}',
                ]
                try: 
                    font = ImageFont.truetype(name, size)
                    _cache[cache_key] = font
                    return font
                except: pass
                
                for p in paths:
                     if os.path.exists(p):
                         try: 
                             font = ImageFont.truetype(p, size)
                             _cache[cache_key] = font
                             return font
                         except: continue
            
            default_font = ImageFont.load_default()
            _cache[cache_key] = default_font
            return default_font

        font_regular = load_font(['DejaVuSans.ttf', 'arial.ttf', 'seguiemj.ttf', 'NotoSans-Regular.ttf'], 17 * S)
        font_bold = load_font(['DejaVuSans-Bold.ttf', 'arialbd.ttf', 'seguiemj.ttf', 'NotoSans-Bold.ttf'], 17 * S)
        font_title = load_font(['DejaVuSans-Bold.ttf', 'arialbd.ttf', 'seguiemj.ttf', 'NotoSans-Bold.ttf'], 26 * S)
        font_small = load_font(['DejaVuSans.ttf', 'arial.ttf', 'seguiemj.ttf', 'NotoSans-Regular.ttf'], 12 * S)
        font_group = load_font(['DejaVuSans-Bold.ttf', 'arialbd.ttf', 'seguiemj.ttf', 'NotoSans-Bold.ttf'], 13 * S)
        font_date = load_font(['DejaVuSans.ttf', 'arial.ttf', 'seguiemj.ttf', 'NotoSans-Regular.ttf'], 14 * S)
        # 14px Regular - distinctly smaller than the rest
        font_desc_large = load_font(['DejaVuSans.ttf', 'arial.ttf', 'seguiemj.ttf', 'NotoSans-Regular.ttf'], 14 * S)
        
        # --- DRAW GRADIENT HEADER ---
        for row_y in range(header_height):
            ratio = row_y / header_height
            r = int(COLOR_HEADER_BG_TOP[0] + (COLOR_HEADER_BG_BOT[0] - COLOR_HEADER_BG_TOP[0]) * ratio)
            g = int(COLOR_HEADER_BG_TOP[1] + (COLOR_HEADER_BG_BOT[1] - COLOR_HEADER_BG_TOP[1]) * ratio)
            b = int(COLOR_HEADER_BG_TOP[2] + (COLOR_HEADER_BG_BOT[2] - COLOR_HEADER_BG_TOP[2]) * ratio)
            draw.line([(0, row_y), (width, row_y)], fill=(r, g, b))
        
        # --- TSV LOGO ---
        logo_size = 50 * S
        logo_x = padding_x
        logo_y = (header_height - logo_size) // 2
        try:
            logo_path = os.path.join(basedir, 'static', 'images', 'tsv-alteglofsheim.jpg')
            if os.path.exists(logo_path):
                logo_img = Image.open(logo_path).convert('RGBA')
                logo_img.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
                logo_mask = Image.new("L", logo_img.size, 0)
                logo_mask_draw = ImageDraw.Draw(logo_mask)
                logo_mask_draw.ellipse((0, 0) + logo_img.size, fill=255)
                draw.ellipse([logo_x - 2*S, logo_y - 2*S, logo_x + logo_size + 2*S, logo_y + logo_size + 2*S], fill=(255, 255, 255, 60))
                img.paste(logo_img, (logo_x, logo_y), logo_mask)
                text_start_x = logo_x + logo_size + 18 * S
            else:
                text_start_x = padding_x
        except Exception:
            text_start_x = padding_x
        
        draw.text((text_start_x, logo_y + 4 * S), title, font=font_title, fill=COLOR_HEADER_TEXT)
        subtitle = "TSV Alteglofsheim · Mannschaftskasse"
        draw.text((text_start_x, logo_y + 34 * S), subtitle, font=font_date, fill=(148, 163, 184))
        
        date_str = datetime.now().strftime('%d.%m.%Y')
        try: date_w = font_date.getlength(date_str)
        except: date_w = 100 * S
        draw.text((width - padding_x - date_w, logo_y + 10 * S), date_str, font=font_date, fill=(148, 163, 184))
        
        # --- ACCENT LINE ---
        draw.rectangle([(0, header_height), (width, header_height + accent_line_height)], fill=COLOR_ACCENT)

        # --- COLUMNS (scaled) ---
        y_start = header_height + accent_line_height
        
        if filter_mode == 'team1':
            col_ges_x = 350 * S
            col_trikot_x = 510 * S
            col_fines_x = 670 * S
            col_kistl_x = 820 * S
            col_letzte_strafe_x = 880 * S
            headers_col_player_x = 85 * S
            headers = [("Spieler", headers_col_player_x), ("Gesamt", col_ges_x), ("Trikot", col_trikot_x), ("Strafe", col_fines_x), ("Kistl", col_kistl_x), ("Offene Strafen", col_letzte_strafe_x)]
        elif filter_mode == 'team2':
            col_ges_x = 350 * S
            col_trikot_x = 510 * S
            col_fines_x = 670 * S
            col_kistl_x = 820 * S
            col_letzte_strafe_x = 880 * S
            headers_col_player_x = 85 * S
            headers = [("Spieler", headers_col_player_x), ("Gesamt", col_ges_x), ("Trikot", col_trikot_x), ("Strafe", col_fines_x), ("Kistl", col_kistl_x), ("Offene Strafen", col_letzte_strafe_x)]
        else:
            col_t1_ges_x = 340 * S
            col_t1_trikot_x = 480 * S
            col_t1_fines_x = 610 * S
            col_t2_ges_x = 830 * S
            col_t2_trikot_x = 970 * S
            col_t2_fines_x = 1100 * S
            col_kistl_x = 1320 * S
            headers_col_player_x = 85 * S
            headers = None

        # Column header background
        draw.rectangle([(0, y_start), (width, y_start + column_header_height)], fill=COLOR_COL_HEADER_BG)
        draw.line([(0, y_start + column_header_height - 1), (width, y_start + column_header_height - 1)], fill=COLOR_LINE, width=2 * S)
        
        if headers is not None:
            for name, x in headers:
                draw.text((x, y_start + 10 * S), name, font=font_bold, fill=COLOR_COL_HEADER_TEXT)
        else:
            group_color = (100, 116, 139)
            draw.text((col_t1_ges_x, y_start + 6 * S), "── 1. Mannschaft ──", font=font_group, fill=group_color)
            draw.text((col_t2_ges_x, y_start + 6 * S), "── 2. Mannschaft ──", font=font_group, fill=group_color)
            
            sub_y = y_start + 28 * S
            draw.text((headers_col_player_x, sub_y), "Spieler", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t1_ges_x, sub_y), "Gesamt", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t1_trikot_x, sub_y), "Trikot", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t1_fines_x, sub_y), "Strafe", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t2_ges_x, sub_y), "Gesamt", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t2_trikot_x, sub_y), "Trikot", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_t2_fines_x, sub_y), "Strafe", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            draw.text((col_kistl_x, sub_y), "Kistl", font=font_bold, fill=COLOR_COL_HEADER_TEXT)
            
            sep_x = (col_t1_fines_x + col_t2_ges_x) // 2 + 30 * S
            draw.line([(sep_x, y_start + 6 * S), (sep_x, y_start + column_header_height - 6 * S)], fill=(203, 213, 225), width=S)
            sep_x2 = (col_t2_fines_x + col_kistl_x) // 2 + 20 * S
            draw.line([(sep_x2, y_start + 6 * S), (sep_x2, y_start + column_header_height - 6 * S)], fill=(203, 213, 225), width=S)
            
        y_pos = y_start + column_header_height
        
        # --- SHADOW UNDER HEADER ---
        for s in range(6 * S):
            alpha = int(30 - s * 5 / S)
            if alpha > 0:
                draw.line([(0, y_pos + s), (width, y_pos + s)], fill=(0, 0, 0, alpha))
        
        # --- ROWS ---
        accent_width = 4 * S
        col_rank_x = accent_width + 6 * S
        col_img_x = accent_width + 28 * S
        col_player_x = col_img_x + 48 * S
        
        for i, player in enumerate(sequence):
            current_row_height = player_heights[i]
            row_bg = COLOR_ROW_WHITE if i % 2 == 0 else COLOR_ROW_ALT
            draw.rectangle([(0, y_pos), (width, y_pos + current_row_height)], fill=row_bg)
            draw.line([(padding_x, y_pos + current_row_height - 1), (width - padding_x, y_pos + current_row_height - 1)], fill=COLOR_LINE, width=S)
            
            is_debtor = (player.balance_team1 < -0.01 if filter_mode == 'team1' 
                         else (player.balance_team2 < -0.01 or player.kistl_balance < 0 if filter_mode == 'team2' 
                         else (player.balance_team1 < -0.01 or player.balance_team2 < -0.01 or player.kistl_balance < 0)))
            
            has_any_balance = False
            if filter_mode == 'team1':
                has_any_balance = abs(player.balance_team1) > 0.01 or player.kistl_balance != 0
            elif filter_mode == 'team2':
                has_any_balance = abs(player.balance_team2) > 0.01 or player.kistl_balance != 0
            else:
                has_any_balance = abs(player.balance_team1) > 0.01 or abs(player.balance_team2) > 0.01 or player.kistl_balance != 0
            
            # Left accent bar
            if is_debtor:
                accent_color = (220, 38, 38, 180)
            elif has_any_balance:
                accent_color = (22, 163, 74, 180)
            else:
                accent_color = (203, 213, 225, 100)
            draw.rectangle([(0, y_pos), (accent_width, y_pos + current_row_height)], fill=accent_color)
            
            # Ranking number
            rank_num = str(i + 1)
            try: rank_w = font_small.getlength(rank_num)
            except: rank_w = 10 * S
            draw.text((col_rank_x + (16 * S - rank_w) / 2, y_pos + 18 * S), rank_num, font=font_small, fill=(148, 163, 184))
            
            avatar_size = 38 * S
            avatar_padding_top = (base_row_height - avatar_size) // 2
            ring_color = (220, 38, 38) if is_debtor else ((22, 163, 74) if has_any_balance else (203, 213, 225))
            ring_w = 2 * S
            
            # Profile image with colored ring
            has_image = False
            if player.image_path:
                try:
                    rel_path = player.image_path
                    full_path = os.path.join(basedir, *rel_path.split('/'))
                    if os.path.exists(full_path):
                        p_img = Image.open(full_path).convert('RGBA')
                        p_img.thumbnail((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                        mask = Image.new("L", p_img.size, 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0) + p_img.size, fill=255)
                        ring_box = [col_img_x - ring_w, y_pos + avatar_padding_top - ring_w, col_img_x + avatar_size + ring_w, y_pos + avatar_padding_top + avatar_size + ring_w]
                        draw.ellipse(ring_box, outline=ring_color, width=ring_w)
                        img.paste(p_img, (col_img_x, y_pos + avatar_padding_top), mask)
                        has_image = True
                except Exception:
                    pass
            
            if not has_image:
                 ring_box = [col_img_x - ring_w, y_pos + avatar_padding_top - ring_w, col_img_x + avatar_size + ring_w, y_pos + avatar_padding_top + avatar_size + ring_w]
                 draw.ellipse(ring_box, outline=ring_color, width=ring_w)
                 circle_bbox = [col_img_x, y_pos + avatar_padding_top, col_img_x + avatar_size, y_pos + avatar_padding_top + avatar_size]
                 draw.ellipse(circle_bbox, fill=(226, 232, 240))
                 initials = player.name[:1]
                 if ' ' in player.name: initials += player.name.split(' ')[-1][:1]
                 initials = initials.upper()
                 try: text_len = font_bold.getlength(initials)
                 except: text_len = 15 * S
                 draw.text((col_img_x + (avatar_size - text_len)/2, y_pos + avatar_padding_top + 7 * S), initials, font=font_bold, fill=(71, 85, 105))
            
            name_color = COLOR_TEXT if is_debtor else COLOR_TEXT_LIGHT
            draw.text((col_player_x, y_pos + 14 * S), player.name, font=font_bold if is_debtor else font_regular, fill=name_color)
            
            if filter_mode in ['team1', 'team2']:
                tm = filter_mode
                v = getattr(player, f'balance_{tm}')
                if abs(v) > 0.01:
                    c = COLOR_DEBT if v < 0 else (COLOR_CREDIT if v > 0 else (150,150,150))
                    draw.text((col_ges_x, y_pos + 14 * S), f"{v:.2f} €", font=font_bold, fill=c)
                
                g = getattr(player, f'general_balance_{tm}')
                if abs(g) > 0.01 and v < 0:
                    c = COLOR_DEBT if g < 0 else (COLOR_CREDIT if g > 0 else (150,150,150))
                    draw.text((col_trikot_x, y_pos + 14 * S), f"{g:.2f} €", font=font_regular, fill=c)
                
                f_val = getattr(player, f'fine_balance_{tm}')
                if abs(f_val) > 0.01 and v < 0:
                    c = COLOR_DEBT if f_val < 0 else (COLOR_CREDIT if f_val > 0 else (150,150,150))
                    draw.text((col_fines_x, y_pos + 14 * S), f"{f_val:.2f} €", font=font_regular, fill=c)
                
                k = player.kistl_balance
                if k < 0:
                     pill_text = f"{abs(k)} x"
                     try: pw = font_bold.getlength(pill_text)
                     except: pw = 30 * S
                     pill_pad = 8 * S
                     pill_h = 22 * S
                     pill_y = y_pos + (base_row_height - pill_h) // 2
                     draw.rounded_rectangle([(col_kistl_x - pill_pad, pill_y), (col_kistl_x + pw + pill_pad, pill_y + pill_h)], radius=11 * S, fill=COLOR_WARNING)
                     draw.text((col_kistl_x, pill_y + 2 * S), pill_text, font=font_bold, fill=(255, 255, 255))
                
                try:
                    unpaid_fines = player_unpaid_fines[i]
                    if unpaid_fines and (g + f_val < -0.01):
                        block_height = len(unpaid_fines) * 22 * S
                        current_fines_y = y_pos + (current_row_height - block_height) // 2 + 3 * S # +3 for optical adjustment
                        for f in unpaid_fines:
                            f_date_str = f.date.strftime('%d.%m.')
                            f_desc = f"{f_date_str} - {f.description}"
                            max_text_w = width - padding_x - col_letzte_strafe_x
                            try:
                                while f_desc and font_desc_large.getlength(f_desc + '...') > max_text_w:
                                    f_desc = f_desc[:-1]
                                if len(f_desc) < len(f"{f_date_str} - {f.description}"): f_desc += '...'
                            except Exception: f_desc = f_desc[:90]
                            
                            draw.text((col_letzte_strafe_x, current_fines_y), f_desc, font=font_desc_large, fill=COLOR_DEBT)
                            current_fines_y += 22 * S
                except Exception:
                    pass

            else: # mode: all
                t1 = player.balance_team1
                if abs(t1) > 0.01:
                    c = COLOR_DEBT if t1 < 0 else (COLOR_CREDIT if t1 > 0 else (150,150,150))
                    draw.text((col_t1_ges_x, y_pos + 14 * S), f"{t1:.2f} €", font=font_bold, fill=c)
                t1_g = player.general_balance_team1
                if abs(t1_g) > 0.01 and t1 < 0:
                    c = COLOR_DEBT if t1_g < 0 else (COLOR_CREDIT if t1_g > 0 else (150,150,150))
                    draw.text((col_t1_trikot_x, y_pos + 14 * S), f"{t1_g:.2f} €", font=font_regular, fill=c)
                t1_f = player.fine_balance_team1
                if abs(t1_f) > 0.01 and t1 < 0:
                    c = COLOR_DEBT if t1_f < 0 else (COLOR_CREDIT if t1_f > 0 else (150,150,150))
                    draw.text((col_t1_fines_x, y_pos + 14 * S), f"{t1_f:.2f} €", font=font_regular, fill=c)
                t2 = player.balance_team2
                if abs(t2) > 0.01:
                    c = COLOR_DEBT if t2 < 0 else (COLOR_CREDIT if t2 > 0 else (150,150,150))
                    draw.text((col_t2_ges_x, y_pos + 14 * S), f"{t2:.2f} €", font=font_bold, fill=c)
                t2_g = player.general_balance_team2
                if abs(t2_g) > 0.01 and t2 < 0:
                    c = COLOR_DEBT if t2_g < 0 else (COLOR_CREDIT if t2_g > 0 else (150,150,150))
                    draw.text((col_t2_trikot_x, y_pos + 14 * S), f"{t2_g:.2f} €", font=font_regular, fill=c)
                t2_f = player.fine_balance_team2
                if abs(t2_f) > 0.01 and t2 < 0:
                    c = COLOR_DEBT if t2_f < 0 else (COLOR_CREDIT if t2_f > 0 else (150,150,150))
                    draw.text((col_t2_fines_x, y_pos + 14 * S), f"{t2_f:.2f} €", font=font_regular, fill=c)
                k = player.kistl_balance
                if k < 0:
                     pill_text = f"{abs(k)} x"
                     try: pw = font_bold.getlength(pill_text)
                     except: pw = 30 * S
                     pill_pad = 8 * S
                     pill_h = 22 * S
                     pill_y = y_pos + (current_row_height - pill_h) // 2
                     draw.rounded_rectangle([(col_kistl_x - pill_pad, pill_y), (col_kistl_x + pw + pill_pad, pill_y + pill_h)], radius=11 * S, fill=COLOR_WARNING)
                     draw.text((col_kistl_x, pill_y + 2 * S), pill_text, font=font_bold, fill=(255, 255, 255))

                # Vertical separators
                sep_x = (col_t1_fines_x + col_t2_ges_x) // 2 + 30 * S
                draw.line([(sep_x, y_pos + 6 * S), (sep_x, y_pos + current_row_height - 6 * S)], fill=(226, 232, 240), width=S)
                sep_x2 = (col_t2_fines_x + col_kistl_x) // 2 + 20 * S
                draw.line([(sep_x2, y_pos + 6 * S), (sep_x2, y_pos + current_row_height - 6 * S)], fill=(226, 232, 240), width=S)

            y_pos += current_row_height

        # --- PREMIUM FOOTER ---
        footer_y = y_pos + 8 * S
        draw.line([(padding_x, footer_y), (width - padding_x, footer_y)], fill=COLOR_LINE, width=S)
        footer_text = "* Kistl gelten für beide Mannschaften"
        draw.text((padding_x, footer_y + 6 * S), footer_text, font=font_small, fill=COLOR_TEXT_LIGHT)

        # --- ROUNDED CORNERS ---
        radius = 16 * S
        mask = Image.new('L', (width, total_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (width, total_height)], radius=radius, fill=255)
        border_draw = ImageDraw.Draw(img)
        border_draw.rounded_rectangle([(0, 0), (width - 1, total_height - 1)], radius=radius, outline=(203, 213, 225), width=S)
        output = Image.new('RGBA', (width, total_height), (0, 0, 0, 0))
        output.paste(img, mask=mask)

        im_io = io.BytesIO()
        output.save(im_io, 'PNG')
        return im_io.getvalue()
    except Exception as e:
        app.logger.error(f'Fehler in _generate_debt_image_bytes: {traceback.format_exc()}')
        return None

# Wiederhergestellte, Unicode-fähige Bildroute für die Schulden-Übersicht
@app.route('/schulden/image')
@login_required
def schulden_image():
    try:
        """Generiert ein PNG mit Schuldnerliste. 
        Parameter 'filter' kann 'team1' oder 'team2' sein. Default: Alle.
        Nutzt Cache um CPU zu sparen.
        """
        filter_mode = request.args.get('filter', 'all') 
        
        # 1. Cache prüfen
        global fines_image_cache
        if filter_mode in fines_image_cache and fines_image_cache[filter_mode]:
            im_io = BytesIO(fines_image_cache[filter_mode])
            im_io.seek(0)
            resp = make_response(send_file(im_io, mimetype='image/png', as_attachment=False, download_name='schulden_uebersicht.png'))
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp

        # 2. On-Demand Generierung (Fallback, falls Cache leer)
        img_bytes = _generate_debt_image_bytes(filter_mode)
        if not img_bytes:
             # Error Image
             img = Image.new('RGB', (600, 100), color=(255, 200, 200))
             d = ImageDraw.Draw(img)
             d.text((10, 40), "Fehler beim Erstellen des Bildes.", fill=(0,0,0))
             im_io = io.BytesIO()
             img.save(im_io, 'PNG') 
             resp = make_response(send_file(io.BytesIO(im_io.getvalue()), mimetype='image/png'))
             resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
             return resp

        # Cache update für nächstes Mal
        fines_image_cache[filter_mode] = img_bytes
        
        resp = make_response(send_file(io.BytesIO(img_bytes), mimetype='image/png'))
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
        
    except Exception as e:
        tb = traceback.format_exc()
        app.logger.error('Fehler in schulden_image: %s', tb)
        return f"Error generating image:\n{tb}", 500


@app.route('/strafenkatalog')
@app.route('/strafenkatalog/')
@login_required
def strafenkatalog():
    fines_team1 = Fine.query.filter(Fine.team == 'team1').order_by(Fine.type, Fine.description).all()
    fines_team2 = Fine.query.filter((Fine.team == 'team2') | (Fine.team == None)).order_by(Fine.type, Fine.description).all()
    return render_template('strafenkatalog.html', fines_team1=fines_team1, fines_team2=fines_team2)

@app.route('/geburtstage')
@login_required
@role_required(VALID_ROLES)
def geburtstage():
    players = Player.query.filter_by(is_active=True).all()
    today = date.today()
    birthday_list = []
    
    for p in players:
        if p.birthday:
            try:
                # Calculate next birthday
                try:
                    next_bday = p.birthday.replace(year=today.year)
                except ValueError: # Born on Feb 29
                    next_bday = p.birthday.replace(year=today.year, day=28) + timedelta(days=1)
                
                # If birthday has passed this year, it's next year
                if next_bday < today:
                    try:
                        next_bday = p.birthday.replace(year=today.year + 1)
                    except ValueError:
                         next_bday = p.birthday.replace(year=today.year + 1, day=28) + timedelta(days=1)
                
                days_until = (next_bday - today).days
                age = next_bday.year - p.birthday.year
                
                birthday_list.append({
                    'name': p.name,
                    'image_path': p.image_path,
                    'birthday': p.birthday,
                    'is_active': p.is_active,
                    'team1': p.team1,
                    'team2': p.team2,
                    'days_until': days_until,
                    'new_age': age,
                    'next_date': next_bday
                })
            except Exception as e:
                print(f"Error calculating birthday for {p.name}: {e}")
                continue
            
    # Sort by days until, then by name (lastname)
    birthday_list.sort(key=lambda x: (x['days_until'], get_lastname_sort_key(x['name'])))

    
    return render_template('geburtstage.html', birthdays=birthday_list)

# NEU: Eine Funktion, die den Cache-Update sofort und synchron ausführt
def force_update_fupa_cache(season_str):
    """Führt das Fupa-Scraping sofort aus und aktualisiert den globalen Cache."""
    fupa_logger.info("===== Starte manuelle Fupa-Daten-Aktualisierung =====")
    # Rufe die bestehende Scraping-Logik auf
    live_fupa_data = get_latest_fupa_game_data(season_str)
    
    if live_fupa_data and (live_fupa_data.get('team2_date') or live_fupa_data.get('team1_date')):
        new_ts = datetime.utcnow()
        
        # Merge mit vorherigem Cache, um leere Daten abzufangen
        old_data = fupa_cache.get("data")
        if not old_data: old_data, _ = load_fupa_cache()
            
        if old_data:
            if not live_fupa_data.get('team1_date') and old_data.get('team1_date'):
                live_fupa_data['team1_date'] = old_data.get('team1_date')
                live_fupa_data['team1_opponent'] = old_data.get('team1_opponent')
                live_fupa_data['team1_lineup'] = old_data.get('team1_lineup', set())
            if not live_fupa_data.get('team2_date') and old_data.get('team2_date'):
                live_fupa_data['team2_date'] = old_data.get('team2_date')
                live_fupa_data['team2_opponent'] = old_data.get('team2_opponent')
                live_fupa_data['team2_lineup'] = old_data.get('team2_lineup', set())
                
        fupa_cache["data"] = live_fupa_data
        fupa_cache["timestamp"] = new_ts
        save_fupa_cache_to_disk(live_fupa_data, new_ts)
        
        msg = f"T1: {live_fupa_data.get('team1_date')} ({live_fupa_data.get('team1_opponent')}) | T2: {live_fupa_data.get('team2_date')}"
        fupa_logger.info(f"Fupa Cache FORCED UPDATE. {msg}")
        return True, f"Daten aktualisiert: {msg}"
    else:
        fupa_logger.warning("Manuelle Aktualisierung: Weder Team 1 noch Team 2 Daten vollständig.")
        return False, "Konnte keine aktuellen Spieldaten von FuPa laden."

# NEU: Die Route für den manuellen Refresh-Button
@app.route('/admin/refresh-fupa', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2']) # Erweiterte Rechte
def refresh_fupa_data():
    try:
        success, message = force_update_fupa_cache(g.current_season_str)
        if success:
            log_audit("SYSTEM", "FUPA_REFRESH", "FuPa-Daten manuell aktualisiert.")
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        fupa_logger.error(f"Fehler bei manueller Fupa-Aktualisierung: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Ein interner Serverfehler ist aufgetreten.'}), 500

@app.route('/admin/audit-log')
@login_required
@role_required(['admin'])
def audit_log():
    log_audit("ACCESS", "AUDIT_LOG", "Audit-Log eingesehen.")
    show_all = request.args.get('show_all') == '1'
    
    # Falls Tabelle noch nicht exisiert (Schema Update), Fehler abfangen oder leer zurückgeben
    try:
        query = AuditLog.query.order_by(AuditLog.timestamp.desc())
        if not show_all:
            query = query.limit(200)
        logs = query.all()
    except:
        logs = []
        
    return render_template('admin_audit.html', logs=logs, show_all=show_all)

@app.route('/admin')
@app.route('/admin/')
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2', 'viewer']) # Explicit list: No 'guest', or 'player'
def admin():
    # Daten für die verschiedenen Tabs laden
    push_subscriptions = PushSubscription.query.order_by(PushSubscription.player_id).all()
    
    # Fupa-Daten im Hintergrund aktualisieren (diese Logik bleibt unverändert)
    cache_duration = timedelta(hours=4)
    now = datetime.utcnow()
    
    # RELOAD from disk first (Fix for multi-worker setup)
    # Wir nutzen die Disk-Daten als "Source of Truth", da diese aktuell sein sollten (z.B. nach Button-Klick)
    disk_data, disk_ts = load_fupa_cache()
    
    fupa_raw_data = None
    last_update_ts = None
    
    if disk_ts:
        fupa_raw_data = disk_data
        last_update_ts = disk_ts
        
        # In-Memory Cache syncen (optional, aber gut für andere Routen)
        if not fupa_cache.get("timestamp") or disk_ts > fupa_cache.get("timestamp"):
             fupa_cache["data"] = disk_data
             fupa_cache["timestamp"] = disk_ts
    else:
        # Fallback auf Memory, falls Disk-Read scheitert
        fupa_raw_data = fupa_cache.get("data")
        last_update_ts = fupa_cache.get("timestamp")

    # Check ob Update notwendig (wenn Daten veraltet oder nicht vorhanden)
    if not last_update_ts or (now - last_update_ts > cache_duration):
        thread = threading.Thread(target=update_fupa_cache_in_background, args=(g.current_season_str,))
        thread.daemon = True
        thread.start()
        
    if not fupa_raw_data:
        fupa_raw_data = {'team2_date': None, 'team2_opponent': None, 'team1_lineup': set(), 'team2_lineup': set()}

    latest_game_date = fupa_raw_data.get('team2_date')
    latest_game_opponent = fupa_raw_data.get('team2_opponent')
    
    # NEU: Auch Daten für Team 1 extrahieren
    latest_game_date_team1 = fupa_raw_data.get('team1_date')
    latest_game_opponent_team1 = fupa_raw_data.get('team1_opponent')
    
    # Check date difference for UI warning
    date_diff_warning = False
    try:
        if latest_game_date and latest_game_date_team1:
             d1 = datetime.strptime(latest_game_date_team1, '%Y-%m-%d').date()
             d2 = datetime.strptime(latest_game_date, '%Y-%m-%d').date()
             if abs((d1 - d2).days) > 2:
                 date_diff_warning = True
    except: pass
    
    # Standard-Daten laden
    users = User.query.all()
    users.sort(key=lambda u: u.username.lower()) # Username sorting
    settings_dict = {s.key: s.value for s in KasseSetting.query.all()}
    
    active_players = Player.query.filter_by(is_active=True).all()
    active_players.sort(key=get_lastname_sort_key)
    
    inactive_players = Player.query.filter_by(is_active=False).all()
    inactive_players.sort(key=get_lastname_sort_key)
    
    # --- PERFORMANCE OPTIMIERUNG: Balances vorladen (Bulk Load) ---
    # 1. Kistl Balances
    kistl_balances = db.session.query(KistlTransaction.player_id, func.sum(KistlTransaction.amount)).group_by(KistlTransaction.player_id).all()
    kistl_map = {pid: (bal or 0) for pid, bal in kistl_balances}
    
    # 2. Team 1 Balances
    team1_balances = db.session.query(Transaction.player_id, func.sum(Transaction.amount)).filter(Transaction.team == 'team1').group_by(Transaction.player_id).all()
    team1_map = {pid: (bal or 0.0) for pid, bal in team1_balances}
    
    # 3. Team 2 Balances
    team2_balances = db.session.query(Transaction.player_id, func.sum(Transaction.amount)).filter(Transaction.team == 'team2').group_by(Transaction.player_id).all()
    team2_map = {pid: (bal or 0.0) for pid, bal in team2_balances}

    # Cache an Spieler-Objekte hängen (verhindert N+1 Queries beim Zugriff auf Properties)
    for p in active_players:
        p._kistl_balance_cache = kistl_map.get(p.id, 0)
        p._balance_team1_cache = team1_map.get(p.id, 0.0)
        p._balance_team2_cache = team2_map.get(p.id, 0.0)
        p._balance_cache = p._balance_team1_cache + p._balance_team2_cache
    
    # Strafen getrennt laden
    fines_team1 = Fine.query.filter(Fine.team == 'team1').order_by(Fine.type, Fine.description).all()
    fines_team2 = Fine.query.filter((Fine.team == 'team2') | (Fine.team == None)).order_by(Fine.type, Fine.description).all() # Fallback

    # --- HISTORY: My Bookings Today ---
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    my_transactions_today = Transaction.query.filter(
        Transaction.created_by == current_user.username,
        Transaction.created_at >= today_start
    ).order_by(Transaction.created_at.desc()).all()

    my_kistl_today = KistlTransaction.query.filter(
        KistlTransaction.created_by == current_user.username,
        KistlTransaction.created_at >= today_start
    ).order_by(KistlTransaction.created_at.desc()).all()

    user_history_today = []
    # Normalize list
    for t in my_transactions_today:
        user_history_today.append({
            'id': t.id,
            'time': t.created_at,
            'description': t.description,
            'amount': t.amount,
            'player_name': t.player.name if t.player else 'Unbekannt',
            'type': 'money',
            'category': t.category # 'fine', 'general', 'custom'
        })
    for k in my_kistl_today:
         user_history_today.append({
            'id': k.id,
            'time': k.created_at,
            'description': k.description,
            'amount': k.amount, # Integer
            'player_name': k.player.name if k.player else 'Unbekannt',
            'type': 'kistl',
            'category': 'fine'
        })
    
    my_expenses_today = TeamExpense.query.filter(
        TeamExpense.created_by == current_user.username,
        TeamExpense.created_at >= today_start
    ).all()
    
    for e in my_expenses_today:
         user_history_today.append({
            'id': e.id,
            'time': e.created_at,
            'description': e.description,
            'amount': -e.amount,
            'player_name': f"Teamausgabe ({'Zweite' if e.team=='team2' else 'Erste'})",
            'type': 'expense',
            'category': 'expense'
        })

    # Sort combined log (most recent first)
    user_history_today.sort(key=lambda x: x['time'], reverse=True)

    kistl_debtors = [p for p in active_players if p.kistl_balance < 0]

    # --- LOAD PENDING REQUESTS DATA ---
    pending_t1 = PendingGameFee.query.filter_by(team='team1').first()
    pending_t2 = PendingGameFee.query.filter_by(team='team2').first()
    pending_info = {'t1': None, 't2': None}
    
    # Init ID sets (Current and Previous)
    pending_t1_ids = set()
    pending_t1_free_ids = set() # NEW: 0€ Players
    pending_t1_prev = set() 
    pending_t1_prev_free = set() # NEW

    pending_t2_ids = set()
    pending_t2_free_ids = set() # NEW
    pending_t2_prev = set() 
    pending_t2_prev_free = set() # NEW

    if pending_t1:
         try:
             raw_data = json.loads(pending_t1.player_ids_json)
             if isinstance(raw_data, dict):
                 pending_t1_ids = set(int(x) for x in raw_data.get('current', []))
                 pending_t1_free_ids = set(int(x) for x in raw_data.get('current_free', []))
                 pending_t1_prev = set(int(x) for x in raw_data.get('previous', []))
                 pending_t1_prev_free = set(int(x) for x in raw_data.get('previous_free', []))
             else:
                 # Legacy/Initial format (List)
                 pending_t1_ids = set(int(x) for x in raw_data)
                 # pending_t1_prev remains empty (No history yet)
             
             pending_info['t1'] = pending_t1
         except:
             pending_t1_ids = set()

    if pending_t2:
         try:
             raw_data = json.loads(pending_t2.player_ids_json)
             if isinstance(raw_data, dict):
                 pending_t2_ids = set(int(x) for x in raw_data.get('current', []))
                 pending_t2_free_ids = set(int(x) for x in raw_data.get('current_free', []))
                 pending_t2_prev = set(int(x) for x in raw_data.get('previous', []))
                 pending_t2_prev_free = set(int(x) for x in raw_data.get('previous_free', []))
             else:
                 pending_t2_ids = set(int(x) for x in raw_data)
             
             pending_info['t2'] = pending_t2
         except:
             pending_t2_ids = set()

    # --- KORREKTUR: NEUER LOGIK-BLOCK ZUR VERARBEITUNG DER FUPA-DATEN ---
    fupa_game_data = {} 
    
    # Holen der Namens-Sets aus den rohen Fupa-Daten
    team1_lineup_names = fupa_raw_data.get('team1_lineup', set())
    team2_lineup_names = fupa_raw_data.get('team2_lineup', set())

    # Allow all Trikot-Managers to see the auto-checked players for both teams
    auto_check_team1 = current_user.role in ['admin', 'trikot_manager_1', 'trikot_manager_2']
    auto_check_team2 = current_user.role in ['admin', 'trikot_manager_1', 'trikot_manager_2']

    for player in active_players:
        p_data = {
            'checked': False, # T2 Paid
            'checked_free': False, # T2 Free
            'is_team1': False, # T1 Paid
            'is_team1_free': False, # T1 Free
            
            'prev_checked': False, 
            'prev_checked_free': False,
            'prev_is_team1': False, 
            'prev_is_team1_free': False,
            
            'has_history_t1': bool(pending_t1_prev) or bool(pending_t1_prev_free),
            'has_history_t2': bool(pending_t2_prev) or bool(pending_t2_prev_free)
        }
        
        # --- LOGIK: Pending Request > FuPa Auto Detection ---
        
        # Team 1 Selection
        if pending_t1:
             if player.id in pending_t1_ids: p_data['is_team1'] = True
             if player.id in pending_t1_free_ids: p_data['is_team1_free'] = True
             
             if player.id in pending_t1_prev: p_data['prev_is_team1'] = True
             if player.id in pending_t1_prev_free: p_data['prev_is_team1_free'] = True
        else:
             if player.name in team1_lineup_names and auto_check_team1:
                 p_data['is_team1'] = True

        # Team 2 Selection
        if pending_t2:
             if player.id in pending_t2_ids: p_data['checked'] = True
             if player.id in pending_t2_free_ids: p_data['checked_free'] = True
             
             if player.id in pending_t2_prev: p_data['prev_checked'] = True
             if player.id in pending_t2_prev_free: p_data['prev_checked_free'] = True
        else:
             if player.name in team2_lineup_names and auto_check_team2:
                 p_data['checked'] = True
        
        fupa_game_data[player.id] = p_data
    # --- ENDE DES KORREKTUR-BLOCKS ---

    today = datetime.now(GERMAN_TZ).date()
    next_birthday_info = None
    if current_user.role == 'admin':
        players_with_bday = Player.query.filter(Player.birthday.isnot(None), Player.is_active==True).all()
        if players_with_bday:
            upcoming_birthdays = []
            for p in players_with_bday:
                bday_this_year = date(today.year, p.birthday.month, p.birthday.day)
                bday_next_year = date(today.year + 1, p.birthday.month, p.birthday.day)
                days_diff = (bday_next_year - today).days if bday_this_year < today else (bday_this_year - today).days
                upcoming_birthdays.append((days_diff, bday_next_year if bday_this_year < today else bday_this_year, p.name))
            if upcoming_birthdays:
                upcoming_birthdays.sort()
                days, bday_date, name = upcoming_birthdays[0]
                names = [n for d, dt, n in upcoming_birthdays if dt == bday_date]
                next_birthday_info = {"names": names, "date": bday_date, "days_left": days}
    
    # --- PERFORMANCE OPTIMIERUNG: Spielanzahl via Aggregation ---
    # Statt für jeden Spieler einzeln zu zählen (N+1 Queries), holen wir alle Zählungen auf einmal.
    game_counts = db.session.query(
        Transaction.player_id, 
        func.count(Transaction.id)
    ).filter(
        Transaction.date.between(g.start_date, g.end_date),
        Transaction.description.ilike('%gg.%')
    ).group_by(Transaction.player_id).all()
    
    game_count_map = {pid: count for pid, count in game_counts}

    players_for_game_fee = sorted(
        [{'player': p, 'game_count': game_count_map.get(p.id, 0)} for p in active_players],
        key=lambda x: x['game_count'], 
        reverse=True
    )
    
    # --- Log Items laden (optimiert oder vollständig) ---
    show_all_logs = request.args.get('show_all_logs') == '1'
    
    
    if show_all_logs:
        log_items = sorted(
            Transaction.query.filter(Transaction.date.between(g.start_date, g.end_date)).all() +
            KistlTransaction.query.filter(KistlTransaction.date.between(g.start_date, g.end_date)).all() +
            TeamExpense.query.filter(TeamExpense.date.between(g.start_date, g.end_date)).all(),
            key=lambda x: x.date, 
            reverse=True
        )
    else:
        # --- PERFORMANCE OPTIMIERUNG: Log Items limitieren ---
        # Wir laden nicht mehr ALLE Transaktionen der Saison, sondern nur die neuesten (z.B. 150 pro Typ),
        # kombinieren diese und nehmen dann die global neuesten 150.
        limit_per_type = 150
        
        tx_list = Transaction.query.filter(Transaction.date.between(g.start_date, g.end_date)).order_by(Transaction.date.desc()).limit(limit_per_type).all()
        kistl_list = KistlTransaction.query.filter(KistlTransaction.date.between(g.start_date, g.end_date)).order_by(KistlTransaction.date.desc()).limit(limit_per_type).all()
        expense_list = TeamExpense.query.filter(TeamExpense.date.between(g.start_date, g.end_date)).order_by(TeamExpense.date.desc()).limit(limit_per_type).all()
        
        log_items = sorted(
            tx_list + kistl_list + expense_list,
            key=lambda x: x.date, 
            reverse=True
        )[:limit_per_type]
    
    start_balance_setting = KasseSetting.query.filter_by(key='start_balance').first()
    start_balance_team1_setting = KasseSetting.query.filter_by(key='start_balance_team1').first()
    start_balance_team2_setting = KasseSetting.query.filter_by(key='start_balance_team2').first()

    # --- CHECK IF LATEST GAME IS ALREADY BOOKED OR PENDING ---
    game_already_booked_t1 = False
    if latest_game_opponent_team1:
        opp_str_t1 = latest_game_opponent_team1
        if not opp_str_t1.startswith("gg."): opp_str_t1 = f"gg. {opp_str_t1}"
        if pending_t1 and pending_t1.opponent == opp_str_t1:
            game_already_booked_t1 = True
        else:
            q1 = Transaction.query.filter_by(team='team1', description=opp_str_t1)
            try:
                if latest_game_date_team1:
                    g_date = datetime.strptime(latest_game_date_team1, '%Y-%m-%d').date()
                    q1 = q1.filter_by(date=g_date)
            except: pass
            if q1.first(): game_already_booked_t1 = True

    game_already_booked_t2 = False
    if latest_game_opponent:
        opp_str_t2 = latest_game_opponent
        if not opp_str_t2.startswith("gg."): opp_str_t2 = f"gg. {opp_str_t2}"
        if pending_t2 and pending_t2.opponent == opp_str_t2:
            game_already_booked_t2 = True
        else:
            q2 = Transaction.query.filter_by(team='team2', description=opp_str_t2)
            try:
                if latest_game_date:
                    g_date = datetime.strptime(latest_game_date, '%Y-%m-%d').date()
                    q2 = q2.filter_by(date=g_date)
            except: pass
            if q2.first(): game_already_booked_t2 = True

    # CHECK PUSH STATUS FOR CURRENT USER
    current_user_push_active = False
    if current_user.player_id:
        if PushSubscription.query.filter_by(player_id=current_user.player_id).count() > 0:
            current_user_push_active = True

    # --- MANAGER DASHBOARD RENDER LOGIC ---
    if current_user.role in ['strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2']:
        is_strafen_manager = current_user.role.startswith('strafen_')
        target_team_value = 'team1' if current_user.role.endswith('_1') else 'team2'
        target_team_name = 'Erste Mannschaft' if target_team_value == 'team1' else 'Zweite Mannschaft'
        
        return render_template(
            'manager_dashboard.html',
            is_strafen_manager=is_strafen_manager,
            target_team_value=target_team_value,
            target_team_name=target_team_name,
            latest_game_date=latest_game_date_team1 if target_team_value == 'team1' else latest_game_date,
            latest_game_opponent=latest_game_opponent_team1 if target_team_value == 'team1' else latest_game_opponent,
            active_players=active_players,
            fines=fines_team1 if target_team_value == 'team1' else fines_team2,
            players_for_game_fee=players_for_game_fee,
            fupa_game_data=fupa_game_data,
            settings=settings_dict,
            date_diff_warning=date_diff_warning,
            user_history_today=user_history_today,
            current_user_push_active=current_user_push_active,
            selected_season=g.current_season_str,
            today=today,
            now=datetime.utcnow(),
            pending_info=pending_info,
            game_already_booked_t1=game_already_booked_t1,
            game_already_booked_t2=game_already_booked_t2,
            latest_game_date_team1=latest_game_date_team1,
            latest_game_opponent_team1=latest_game_opponent_team1,
            transaction_log=log_items,
            show_all_logs=show_all_logs,
            kistl_debtors=kistl_debtors,
            push_logs=PushLog.query.order_by(PushLog.sent_at.desc()).limit(100).all()
        )
    
    # Alle Daten an das Template übergeben (Admin/Viewer Default)
    return render_template(
        'admin.html',
        active_players=active_players,
        inactive_players=inactive_players,
        current_user_push_active=current_user_push_active,
        fines=fines_team1 + fines_team2, # Combined list for catalog dropdown
        fines_team1=fines_team1,
        fines_team2=fines_team2,
        kistl_debtors=kistl_debtors,
        transaction_log=log_items,
        start_balance=start_balance_setting.value if start_balance_setting else "",
        start_balance_team1=start_balance_team1_setting.value if start_balance_team1_setting else "",
        start_balance_team2=start_balance_team2_setting.value if start_balance_team2_setting else "",
        today=today,
        now=datetime.utcnow(),
        players_for_game_fee=players_for_game_fee,
        latest_game_date=latest_game_date,
        latest_game_opponent=latest_game_opponent,
        latest_game_date_team1=latest_game_date_team1,
        latest_game_opponent_team1=latest_game_opponent_team1,
        # KORREKTUR: Wir übergeben jetzt die verarbeiteten Daten an das Template
        fupa_game_data=fupa_game_data, 
        next_birthday_info=next_birthday_info,
        users=users,
        valid_roles=VALID_ROLES,
        settings=settings_dict,
        push_subscriptions=push_subscriptions,
        webauthn_credentials_all=WebAuthnCredential.query.all(),
        # NEU: Pending Data
        pending_info=pending_info,
        game_already_booked_t1=game_already_booked_t1,
        game_already_booked_t2=game_already_booked_t2,
        show_all_logs=show_all_logs,
        date_diff_warning=date_diff_warning,
        user_history_today=user_history_today,
        push_logs=PushLog.query.order_by(PushLog.sent_at.desc()).limit(100).all()
    )


@app.route('/admin/settle-kistl/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2']) # Kistl for everyone
def settle_kistl(player_id):
    success = False
    response_data = {}
    try:
        player = Player.query.get_or_404(player_id)
        date_val = get_date_from_form(request.form)
        
        new_tx = KistlTransaction(player_id=player_id, description="Kistl bezahlt/beglichen", amount=1, date=date_val, created_by=current_user.username)
        db.session.add(new_tx)
        
        current_kistl_balance = player.kistl_balance
        new_kistl_balance = current_kistl_balance + 1
        remaining_kistl_debt = new_kistl_balance * -1 if new_kistl_balance < 0 else 0

        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        # AUDIT LOG
        log_audit("CREATE", "KISTL_SETTLEMENT", f"Kistl für {player.name} beglichen.")

        # --- PUSH NOTIFICATION: KISTL SETTLED ---
        try:
             url_to_open = url_for('player_detail', player_id=player_id, _external=True)
             send_push_notification(player_id, "Kistl beglichen 🍺", "Eine Kistl-Schuld wurde als 'bezahlt' markiert.", url_to_open)
        except Exception:
             pass

        message = f'Ein Kistl für {player.name} wurde als beglichen markiert.'
        success = True

        response_data = {
            'success': True, 
            'message': message,
            'updateElement': {
                'selector': f'#kistl-item-{player_id}',
                'remaining': remaining_kistl_debt
            }
        }
        if remaining_kistl_debt <= 0:
            response_data['removeElement'] = f'#kistl-item-{player_id}'
            if 'updateElement' in response_data:
                del response_data['updateElement']
    except Exception as e:
        db.session.rollback()
        message = f'Fehler: {e}'
        print(f"Fehler in settle_kistl: {e}")
        response_data = {'success': False, 'message': message}
    
    return jsonify(response_data)

# --- AJAX-fähige Admin-Routen ---
@app.route('/admin/add-custom-fine', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def add_custom_fine():
    try:
        player_id = int(request.form['player_id']); description = request.form.get('description', '').strip()
        amount_str = request.form['amount']; fine_type = request.form['type']
        target_team = request.form.get('team', 'team2') # Default to team2 (legacy)

        # Permission Check
        if target_team == 'team1' and current_user.role not in ['admin', 'strafen_manager_1', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if target_team == 'team2' and current_user.role not in ['admin', 'strafen_manager_2', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        if not all([player_id, description, amount_str, fine_type]): raise ValueError("Alle Felder sind erforderlich.")
        
        player = Player.query.get_or_404(player_id)
        old_balance, date_val = player.balance, get_date_from_form(request.form)
        
        if fine_type == 'money':
            amount = float(amount_str)
            final_amt = abs(amount)
            
            # Auto-Settle Logic
            current_balance = player.get_balance(target_team)
            initial_settled = 0.0
            if current_balance > 0:
                initial_settled = min(current_balance, final_amt)

            team_label = "1. Mannschaft" if target_team == 'team1' else "2. Mannschaft"

            db.session.add(Transaction(
                player_id=player.id, 
                description=f"{description} ({team_label})", 
                amount=-final_amt, 
                date=date_val, 
                team=target_team, 
                created_by=current_user.username,
                category='custom', # Mark as custom fine
                amount_settled=initial_settled
            ))
            message = f"Individuelle Geldstrafe ({team_label}) verbucht."
        else: # fine_type == 'kistl'
            # Kistl is typically Team 2? Allow both? Assuming Kistl is tied to team account logic if needed.
            # Currently KistlTransaction has no team column. 
            db.session.add(KistlTransaction(player_id=player.id, description=description, amount=-abs(int(amount_str)), date=date_val, created_by=current_user.username))
            message = "Individuelle Kistl-Strafe verbucht."
        
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        new_balance = player.balance
        
        # AUDIT LOG
        if fine_type == 'money':
            log_audit("CREATE", "CUSTOM_TRANSACTION", f"Individuelle Strafe '{description}' ({team_label}) (-{amount}€) für {player.name} erstellt.")
        else:
            log_audit("CREATE", "CUSTOM_KISTL", f"Individuelle Kistl-Strafe '{description}' (-{amount_str}) für {player.name} erstellt.")
        
        if fine_type == 'money':
            url_to_open = url_for('player_detail', player_id=player_id, _external=True)
            send_push_notification(player.id, "Neue individuelle Strafe!", f"Für dich wurde verbucht: '{description}'.", url_to_open)
            DEBT_LIMIT = -9.00
            if new_balance <= DEBT_LIMIT and old_balance > DEBT_LIMIT:
                send_push_notification(player.id, "Hoher Schuldenstand!", f"Dein Kontostand hat {new_balance:.2f} € erreicht. Bitte begleiche deine Schulden.", url_to_open)
        
        return jsonify({'success': True, 'message': message})
    except (ValueError, TypeError) as e:
        db.session.rollback(); return jsonify({'success': False, 'message': f'Ungültige Eingabe: {e}'})
    except Exception as e:
        db.session.rollback(); return jsonify({'success': False, 'message': f'Unerwarteter Fehler: {e}'})

@app.route('/admin/api/check_duplicate', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def check_duplicate():
    """
    Checks if a similar transaction already exists on the given date for a player.
    Expects JSON data: player_id, date, type, fine_id, description, amount.
    """
    data = request.get_json()
    if not data:
        return jsonify({"exists": False})

    player_id = data.get('player_id')
    date_val = data.get('date')
    tx_type = data.get('type')
    amount = data.get('amount')
    
    if not player_id or not date_val or not tx_type:
        return jsonify({"exists": False})

    query = Transaction.query.filter(
        Transaction.player_id == player_id,
        Transaction.date == date_val
    )

    try:
        if tx_type == 'fine':
            fine_id = data.get('fine_id')
            if not fine_id:
                return jsonify({"exists": False})
            fine = Fine.query.get(fine_id)
            if not fine:
                return jsonify({"exists": False})
            query = query.filter(Transaction.description.like(f"%{fine.description}%"))
            if amount:
                query = query.filter(Transaction.amount == -abs(float(amount)))

        elif tx_type == 'custom_fine':
            desc = data.get('description', '')
            query = query.filter(Transaction.description.like(f"%{desc}%"))
            if amount:
                query = query.filter(Transaction.amount == -abs(float(amount)))

        elif tx_type == 'payment':
            query = query.filter(Transaction.amount > 0)
            if amount:
                query = query.filter(Transaction.amount == abs(float(amount)))

        elif tx_type == 'payout':
            query = query.filter(Transaction.amount < 0)
            if amount:
                query = query.filter(Transaction.amount == -abs(float(amount)))

        duplicate = query.first()
        return jsonify({"exists": duplicate is not None})
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})

@app.route('/admin/add-transaction', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def add_transaction():
    try:
        player_id = int(request.form['player_id']); fine_id = int(request.form['fine_id'])
        player, fine = Player.query.get_or_404(player_id), Fine.query.get_or_404(fine_id)
        date_val, old_balance = get_date_from_form(request.form), player.balance
        target_team = request.form.get('team', 'team2') # Default to team2

        # Permission Check
        if target_team == 'team1' and current_user.role not in ['admin', 'strafen_manager_1', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if target_team == 'team2' and current_user.role not in ['admin', 'strafen_manager_2', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        # Multiplier Logic (falls "pro" im Namen)
        try:
            multiplier = int(request.form.get('multiplier', '1'))
            if multiplier < 1: multiplier = 1
        except:
            multiplier = 1
        
        final_amount = fine.amount * multiplier

        # Determine logical Category Label for Log
        cat_labels = {'game': 'Spiel', 'training': 'Training', 'general': 'Allg.'}
        cat_label = cat_labels.get(fine.category, 'Allg.')
        
        if multiplier > 1:
            if 'minute' in fine.description.lower():
                tx_description = f"Strafe [{cat_label}]: {multiplier} Minuten {fine.description}"
            elif 'tag' in fine.description.lower():
                tx_description = f"Strafe [{cat_label}]: {multiplier} Tage {fine.description}"
            elif 'monat' in fine.description.lower():
                 tx_description = f"Strafe [{cat_label}]: {multiplier} Monate {fine.description}"
            else:
                tx_description = f"Strafe [{cat_label}]: {multiplier}x {fine.description}"
        else:
            tx_description = f"Strafe [{cat_label}]: {fine.description}"

        team_label = "1. Mannschaft" if target_team == 'team1' else "2. Mannschaft"
        tx_description = f"{tx_description} ({team_label})"

        if fine.type == 'money':
            # Check existing balance for Auto-Settle
            # If player has positive balance, we can use it to effectively "settle" this fine immediately 
            # (conceptually, the money is already in the pot).
            current_balance = player.get_balance(target_team)
            initial_settled = 0.0
            if current_balance > 0:
                initial_settled = min(current_balance, final_amount)

            # NEW: Set category to 'fine' for money fines
            tx = Transaction(
                player_id=player.id, 
                description=tx_description, 
                amount=-final_amount, 
                date=date_val, 
                team=target_team, 
                created_by=current_user.username,
                category='fine',
                amount_settled=initial_settled
            )
            db.session.add(tx)
            
            # --- Recalculate just in case old math was fuzzy ---
            # But here we are pre-commit and we just did the math. 
            # Recalculate needs commmitted data usually for queries. 
            # So rely on initial_settled above.
            
            log_audit("CREATE", "TRANSACTION", f"Strafe '{fine.description}' ({team_label}) (-{final_amount}€, {multiplier}x) für {player.name} erstellt.")
            
            # --- PUSH NOTIFICATION ---
            try:
                # Direct URL: player sees their own detail page
                url_to_open = url_for('player_detail', player_id=player.id, _external=True)
                send_push_notification(player.id, "Neue Strafe erhalten! 😓", f"{tx_description} ({final_amount}€)", url_to_open)
                
                # Check Debt Limit
                DEBT_LIMIT = -50.00
                new_balance = player.balance # Recalculated after commit usually, but here optimistic is fine or re-fetch
                # Since we haven't committed yet, player.balance doesn't reflect this tx? 
                # Actually player.balance is a property summing transactions. 
                # Without commit, query won't see new tx?
                # Correct: need commit first.
            except Exception as e: push_logger.error(f"Push Error (Fine): {e}")

        else:
            db.session.add(KistlTransaction(player_id=player.id, description=tx_description, amount=-int(final_amount), date=date_val, created_by=current_user.username))
        
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        # Post-Commit Checks (Balance)
        if fine.type == 'money':
             # Re-fetch for correct balance
             # ... (existing logic somewhat flawed in placement, let's fix)
             pass 
        
        new_balance = player.balance
        
        # Existing logic had send_push INSIDE the if fine.type block BEFORE commit? 
        # But player.balance wouldn't update.
        # Let's clean up.
        
        return jsonify({'success': True, 'message': 'Strafe erfolgreich hinzugefügt.'})
    except Exception as e:
        db.session.rollback(); return jsonify({'success': False, 'message': f'Fehler: {e}'})

@app.route('/admin/add-mass-transaction', methods=['POST'])
@login_required
@role_required(['admin'])
def add_mass_transaction():
    try:
        description = request.form.get('description')
        amount_str = request.form.get('amount')
        target_team = request.form.get('team')
        date_str = request.form.get('date')
        
        if not description or not amount_str or not target_team or not date_str:
            return jsonify({'success': False, 'message': 'Bitte alle Felder ausfüllen.'})

        # Permission Check
        if target_team == 'team1' and current_user.role != 'admin':
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if target_team == 'team2' and current_user.role != 'admin':
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        try:
            amount = float(amount_str.replace(',', '.'))
        except:
             return jsonify({'success': False, 'message': 'Ungültiger Betrag.'})

        team_label = "1. Mannschaft" if target_team == 'team1' else "2. Mannschaft"
        mass_desc = f"{description} ({team_label})"

        date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
        player_ids = request.form.getlist('player_ids')

        if not player_ids:
            return jsonify({'success': False, 'message': 'Keine Spieler ausgewählt.'})

        count = 0
        for pid in player_ids:
            try:
                p = Player.query.get(int(pid))
                if not p: continue

                # Auto-Settle Check
                current_balance = p.get_balance(target_team)
                final_amount_mass = amount if amount > 0 else -amount
                initial_settled = 0.0
                if current_balance > 0:
                    initial_settled = min(current_balance, final_amount_mass)

                db.session.add(Transaction(
                    player_id=int(pid),
                    description=mass_desc,
                    amount=-final_amount_mass,
                    date=date_val,
                    team=target_team,
                    created_by=current_user.username,
                    category='custom',
                    amount_settled=initial_settled
                ))
                count += 1
            except: pass
        
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        log_audit("CREATE", "MASS_TRANSACTION", f"Massenbuchung '{description}' ({team_label}) (-{amount}€) für {count} Spieler erstellt.")
        
        return jsonify({'success': True, 'message': f'Buchung erfolgreich für {count} Spieler erstellt.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Fehler: {e}'})

@app.route('/admin/add-payment', methods=['POST'])
@login_required
# Updated roles to exclude strafen_manager
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2'])
def add_payment():
    success = False
    message = "Ein unbekannter Fehler ist aufgetreten."
    try:
        player_id = int(request.form['player_id'])
        amount = float(request.form['amount'])
        date_val = get_date_from_form(request.form)
        target_team = request.form.get('team', 'team2') # Default to team2

        # Permission Check (Extended)
        allowed_t1 = ['admin', 'trikot_manager_1']
        allowed_t2 = ['admin', 'trikot_manager_2']
        
        if target_team == 'team1' and current_user.role not in allowed_t1:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if target_team == 'team2' and current_user.role not in allowed_t2:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        if amount <= 0:
            raise ValueError("Der Betrag muss positiv sein.")

        team_label = "1. Mannschaft" if target_team == 'team1' else "2. Mannschaft"
            
        custom_category = request.form.get('payment_category', 'standard')
        base_desc = f"Einzahlung ({team_label})"
        if custom_category == 'game_fee': 
            base_desc = f"Einzahlung (Trikotgeld, {team_label})"
        
        player = Player.query.get(player_id)
        if not player:
            raise ValueError("Spieler nicht gefunden.")

        # --- "Zwei Töpfe" Logic: Pay off fines first ---
        amount_remaining = amount
        amount_used_for_fines = 0.0

        # Find unpaid fines for this player and team, ordered by date (Oldest first - FIFO)
        # We look for transactions with negative amount, category 'fine', and where amount_settled < abs(amount)
        # We manually check the condition in Python to be safe with Float comparisons or use specific logic
        unpaid_fines = Transaction.query.filter_by(
            player_id=player_id, 
            team=target_team, 
            category='fine'
        ).filter(Transaction.amount < 0).order_by(Transaction.date.asc()).all()
        
        # Filter for those not fully settled (in Python to avoid complex SQLAlchemy float math issues if possible, though SQL is better)
        # Also, check if amount settled is None (for old data)
        valid_unpaid_fines = []
        for f in unpaid_fines:
            settled = f.amount_settled if f.amount_settled is not None else 0.0
            if settled < abs(f.amount) - 0.01: # Epsilon for float comparison
                valid_unpaid_fines.append(f)

        for fine in valid_unpaid_fines:
            if amount_remaining <= 0:
                break
            
            settled = fine.amount_settled if fine.amount_settled is not None else 0.0
            open_amount = abs(fine.amount) - settled
            
            payment_for_this = min(amount_remaining, open_amount)
            
            # Update the fine
            fine.amount_settled = settled + payment_for_this
            
            amount_remaining -= payment_for_this
            amount_used_for_fines += payment_for_this

        # Create Transactions
        # 1. Payment part for fines (if any)
        if amount_used_for_fines > 0.001:
            db.session.add(Transaction(
                player_id=player_id, 
                description=f"Einzahlung (Strafen, {team_label})", 
                amount=amount_used_for_fines, 
                date=date_val, 
                team=target_team, 
                category='fine',
                created_by=current_user.username
            ))

        # 2. Remaining amount (General pot)
        if amount_remaining > 0.001:
             db.session.add(Transaction(
                player_id=player_id, 
                description=base_desc, 
                amount=amount_remaining, 
                date=date_val, 
                team=target_team, 
                category='general',
                created_by=current_user.username
            ))

        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        # AUDIT LOG
        log_audit("CREATE", "PAYMENT", f"Einzahlung von {amount:.2f}€ ({team_label}) (Strafen: {amount_used_for_fines:.2f}€, Rest: {amount_remaining:.2f}€) für {player.name} gebucht.")

        message = f'Einzahlung von {amount:.2f}€ für {player.name} ({target_team}) verbucht.'
        if amount_used_for_fines > 0:
            message += f' Davon {amount_used_for_fines:.2f}€ zur Strafentilgung.'
        success = True

        # --- PUSH-BENACHRICHTIGUNG AN DEN SPIELER ---
        try:
            # Refresh player to get new balance
            db.session.refresh(player)
            # Use specific team balance if possible, otherwise total
            if target_team == 'team1':
                 new_balance = player.balance_team1 
            else:
                 new_balance = player.balance_team2
                 
            url_to_open = url_for('player_detail', player_id=player.id, _external=True)
            send_push_notification(
                player_id=player.id,
                title="✅ Zahlung bestätigt",
                body=f"Dein Guthaben ({'1.' if target_team=='team1' else '2.'}) beträgt jetzt {new_balance:.2f} € (+{amount:.0f}€).",
                url=url_to_open
            )
        except Exception as e:
            # Wenn das Senden fehlschlägt, soll die App nicht abstürzen.
            # Der Fehler wird nur auf dem Server geloggt.
            print(f"Fehler beim Senden der Zahlungsbestätigung per Push: {e}")
        # --- ENDE SPIELER-BENACHRICHTIGUNG ---

    except (ValueError, TypeError) as e:
        db.session.rollback()
        message = str(e)
    except Exception as e:
        db.session.rollback()
        message = f'Ein Serverfehler ist aufgetreten.'
        print(f"Fehler in add_payment: {e}")
    
    if is_ajax():
        return jsonify({'success': success, 'message': message})
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin', season=request.args.get('season')))

@app.route('/admin/add-payout', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2'])
def add_payout():
    try:
        player_id = int(request.form['player_id'])
        amount = float(request.form['amount'])
        target_team = request.form.get('team', 'team2')
        date_val = get_date_from_form(request.form)

        # Permission Check
        if target_team == 'team1' and current_user.role not in ['admin', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if target_team == 'team2' and current_user.role not in ['admin', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        if amount <= 0:
            return jsonify({'success': False, 'message': "Der Betrag muss positiv sein."})
        
        player = Player.query.get_or_404(player_id)
        current_balance = player.get_balance(target_team)
        
        # Check validation
        if amount > current_balance:
             return jsonify({'success': False, 'message': f"Auszahlung nicht möglich. Maximal auszahlbar: {current_balance:.2f}€"})

        team_label = "1. Mannschaft" if target_team == 'team1' else "2. Mannschaft"
        db.session.add(Transaction(player_id=player_id, description=f"Auszahlung ({current_user.username}, {team_label})", amount=-amount, date=date_val, team=target_team, created_by=current_user.username))
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        log_audit("CREATE", "PAYOUT", f"Auszahlung von {amount:.2f}€ für {player.name} ({team_label}) verbucht.")

        # --- PUSH NOTIFICATION: PAYOUT ---
        try:
            url_to_open = url_for('player_detail', player_id=player_id, _external=True)
            send_push_notification(player_id, "Auszahlung erhalten 💸", f"Eine Auszahlung von {amount:.2f}€ wurde für dich verbucht.", url_to_open)
        except Exception as e:
            pass

        return jsonify({'success': True, 'message': f'Auszahlung von {amount:.2f}€ für {player.name} ({target_team}) verbucht.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Fehler: {e}'})

@app.route('/admin/add-team-expense', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2'])
def add_team_expense():
    success = False
    try:
        amount=float(request.form['amount']); description=request.form.get('description')
        team = request.form.get('team', 'team2')

        # Permission Check
        if team == 'team1' and current_user.role not in ['admin', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if team == 'team2' and current_user.role not in ['admin', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        team_label = "1. Mannschaft" if team == 'team1' else "2. Mannschaft"
        date_val = get_date_from_form(request.form)
        db.session.add(TeamExpense(description=f"{description} ({team_label})", amount=amount, date=date_val, team=team, created_by=current_user.username))
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        log_audit("CREATE", "EXPENSE", f"Ausgabe '{description}' ({team_label}) ({amount}€) für {team} verbucht.")
        
        message = f'Teamausgabe für {team} verbucht.'
        success = True
    except Exception as e:
        db.session.rollback(); message = f'Fehler: {e}'

    if is_ajax(): return jsonify({'success': success, 'message': message})
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin', season=request.args.get('season')))

@app.route('/add_player', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2', 'strafen_manager_1', 'strafen_manager_2'])
def add_player():
    name = (request.form.get('player_name') or request.form.get('name', '')).strip()
    success = False
    html = None
    if not name: 
        message = 'Spielername darf nicht leer sein!'
    elif Player.query.filter(func.lower(Player.name) == func.lower(name)).first():
        log_audit("UPDATE", "PLAYER_CREATE_FAILED", f"Spieleranlage gescheitert: Name '{name}' bereits vergeben.")
        message = f'Ein Spieler mit dem Namen "{name}" existiert bereits!'
    else:
        new_player = Player(name=name)
        db.session.add(new_player)
        log_audit("CREATE", "PLAYER", f"Spieler '{name}' erstellt.")
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        message = f'Spieler "{name}" wurde erfolgreich hinzugefügt.'
        success = True
        html = render_template('_player_item.html', player=new_player)
        
    if is_ajax():
        if success:
            return jsonify({'success': True, 'message': message, 'html': html, 'prependTo': '#active-players-list'})
        else:
            return jsonify({'success': False, 'message': message})
            
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin', season=request.args.get('season')))

@app.route('/admin/edit-player/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2', 'strafen_manager_1', 'strafen_manager_2'])
def edit_player(player_id):
    # Standardwerte für die Antwort definieren
    success = False
    message = "Ein unbekannter Fehler ist aufgetreten."
    
    try:
        player = Player.query.get_or_404(player_id)
        new_name = request.form.get('player_name', '').strip()
        
        # Validierung durchführen
        if not new_name:
            message = 'Spielername darf nicht leer sein.'
        elif Player.query.filter(func.lower(Player.name) == func.lower(new_name), Player.id != player_id).first():
            message = f'Der Name "{new_name}" wird bereits von einem anderen Spieler verwendet.'
        else:
            # Wenn die Validierung erfolgreich war, Daten aktualisieren
            player.name = new_name
            player.phone_number = request.form.get('phone_number', '').strip()
            birthday_str = request.form.get('birthday', '').strip()

            if birthday_str:
                player.birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            else:
                player.birthday = None
            
            log_audit("UPDATE", "PLAYER", f"Spieler '{player.name}' bearbeitet (Name/Nr/Geb).")
            db.session.commit()
            trigger_image_regeneration()  # Update Cache
            
            # Erfolgsmeldung setzen
            success = True
            message = f'Daten für {player.name} erfolgreich aktualisiert.'

    except ValueError:
        # Fehler bei der Datumsumwandlung
        db.session.rollback()
        message = 'Ungültiges Geburtstagsformat. Bitte YYYY-MM-DD verwenden.'
    except Exception as e:
        # Alle anderen Fehler abfangen
        db.session.rollback()
        print(f"Ein Fehler ist in edit_player aufgetreten: {e}")
        message = "Ein interner Serverfehler ist aufgetreten."

    if is_ajax():
        return jsonify({'success': success, 'message': message})
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin', season=request.args.get('season')))

@app.route('/admin/player/upload-image/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def upload_player_image(player_id):
    player = Player.query.get_or_404(player_id)
    
    print(f"DEBUG: Starte Upload für Player {player.id}")

    if 'image' not in request.files:
        print("DEBUG: Keine 'image' Datei im Request")
        return jsonify({'success': False, 'message': 'Kein Bild übertragen.'})
        
    file = request.files['image']
    if not file or file.filename == '':
        print("DEBUG: Dateiname leer")
        return jsonify({'success': False, 'message': 'Keine Datei ausgewählt.'})

    try:
        # Ordner erstellen falls nicht vorhanden
        save_dir = os.path.join(basedir, 'static', 'app', 'player_images')
        print(f"DEBUG: Speicherort Ziel: {save_dir}")
        
        if not os.path.exists(save_dir):
            print(f"DEBUG: Ordner existiert nicht, erstelle {save_dir}")
            os.makedirs(save_dir)
        
        # Schreibrechte prüfen
        if not os.access(save_dir, os.W_OK):
             print(f"ERROR: Keine Schreibrechte in {save_dir}")
             return jsonify({'success': False, 'message': 'Server-Fehler: Keine Schreibrechte.'})

        # Dateinamen sichern
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        if ext not in ['jpg', 'jpeg', 'png', 'webp']:
             return jsonify({'success': False, 'message': 'Nur JPG, PNG oder WEBP erlaubt.'})
             
        filename = secure_filename(f"player_{player.id}_{int(time.time())}.{ext}")
        file_path = os.path.join(save_dir, filename)
        print(f"DEBUG: Ziel-Dateipfad: {file_path}")

        # Bild verarbeiten (Resize)
        if Image:
            try:
                img = Image.open(file)
                if img.mode in ("RGBA", "P"): 
                    img = img.convert("RGB")
                    
                width, height = img.size
                new_size = min(width, height)
                left = (width - new_size)/2
                top = (height - new_size)/2
                right = (width + new_size)/2
                bottom = (height + new_size)/2
                img = img.crop((left, top, right, bottom))
                
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                img.save(file_path, quality=85, optimize=True)
                print("DEBUG: Bild mit PIL gespeichert.")
            except Exception as e:
                print(f"PIL Error: {e}")
                file.seek(0) # Reset Pointer falls PIL gelesen hat
                file.save(file_path)
                print("DEBUG: Bild roh gespeichert (Fallback).")
        else:
            file.save(file_path)
            print("DEBUG: Bild gespeichert (Kein PIL).")

        # Altes Bild löschen
        if player.image_path:
            try:
                old_rel = player.image_path
                full_old_path = os.path.join(basedir, *old_rel.split('/'))
                if os.path.exists(full_old_path) and 'player_images' in full_old_path:
                    os.remove(full_old_path)
                    print(f"DEBUG: Altes Bild gelöscht: {full_old_path}")
            except Exception as e:
                print(f"Fehler beim Löschen des alten Bildes: {e}")

        # Pfad in DB speichern
        player.image_path = f"static/app/player_images/{filename}"
        db.session.commit()
        
        log_audit("UPDATE", "PLAYER_IMAGE", f"Profilbild für Spieler '{player.name}' hochgeladen.")
        
        trigger_image_regeneration()  # Update Cache
        print(f"DEBUG: DB Update erfolgreich.")
        
        return jsonify({
            'success': True, 
            'message': 'Profilbild hochgeladen.',
            'image_url': url_for('static', filename=f'app/player_images/{filename}'),
            'debug_path': file_path
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR Upload Exception: {e}")
        # Traceback für genauere Analyse
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Fehler: {e}'})

@app.route('/delete_player/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def delete_player(player_id):
    player = Player.query.get_or_404(player_id)
    name = player.name
    db.session.delete(player)
    log_audit("DELETE", "PLAYER", f"Spieler '{name}' gelöscht.")
    db.session.commit()
    trigger_image_regeneration()  # Update Cache
    message = f'Spieler "{name}" und alle seine Transaktionen wurden endgültig gelöscht.'
    
    if is_ajax():
        return jsonify({'success': True, 'message': message, 'removeElement': f'#backlog-player-item-{player_id}'})
    
    flash(message, 'success')
    return redirect(url_for('admin', season=request.args.get('season')))

@app.route('/admin/player/deactivate/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def deactivate_player(player_id):
    player = Player.query.get_or_404(player_id)
    player.is_active = False
    log_audit("ARCHIVE", "PLAYER", f"Spieler '{player.name}' archiviert.")
    db.session.commit()
    trigger_image_regeneration()  # Update Cache
    message = f'Spieler "{player.name}" wurde archiviert.'
    
    html_for_inactive_list = f'''
    <li class="list-group-item d-flex justify-content-between align-items-center" id="backlog-player-item-{player.id}">
        <a href="{url_for('player_detail', player_id=player.id)}">{player.name}</a>
        <div>
            <form action="{url_for('reactivate_player', player_id=player.id)}" method="POST" class="d-inline-block me-2 ajax-form"><button type="submit" class="btn btn-sm btn-outline-success">Reaktivieren</button></form>
            <form action="{url_for('delete_player', player_id=player.id)}" method="POST" class="d-inline-block ajax-form"><button type="submit" class="btn btn-sm btn-outline-danger" data-confirm="Soll {player.name} wirklich ENDGÜLTIG gelöscht werden? Alle Daten gehen verloren!">Löschen</button></form>
        </div>
    </li>
    '''
    return jsonify({
        'success': True, 
        'message': message, 
        'moveElement': {
            'source': f'#player-item-{player.id}',
            'destination': '#inactive-players-list',
            'html': html_for_inactive_list
        }
    })

@app.route('/admin/player/reactivate/<int:player_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def reactivate_player(player_id):
    player = Player.query.get_or_404(player_id)
    player.is_active = True
    log_audit("REACTIVATE", "PLAYER", f"Spieler '{player.name}' reaktiviert.")
    db.session.commit()
    trigger_image_regeneration()  # Update Cache
    message = f'Spieler "{player.name}" wurde reaktiviert.'
    html = render_template('_player_item.html', player=player)
    return jsonify({
        'success': True,
        'message': message,
        'moveElement': {
            'source': f'#backlog-player-item-{player_id}',
            'destination': '#active-players-list',
            'html': html
        }
    })

@app.route('/admin/add-fine', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def add_fine():
    description = request.form.get('description', '').strip()
    amount_str = request.form.get('amount'); fine_type = request.form.get('type')
    team = request.form.get('team', 'team2')
    category = request.form.get('category', 'general')

    # Permission Check
    if team == 'team1' and current_user.role not in ['admin', 'strafen_manager_1', 'trikot_manager_1']:
            return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
    if team == 'team2' and current_user.role not in ['admin', 'strafen_manager_2', 'trikot_manager_2']:
            return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

    success = False
    html = None
    if not all([description, amount_str, fine_type]):
        message = 'Alle Felder müssen ausgefüllt sein.'
    # Corrected filter: check description AND team AND type
    elif Fine.query.filter_by(description=description, team=team, type=fine_type).first():
        message = 'Eine Strafe mit dieser Beschreibung und diesem Typ existiert bereits für dieses Team.'
    else:
        try:
            amount = float(amount_str); new_fine = Fine(description=description, amount=amount, type=fine_type, team=team, category=category)
            db.session.add(new_fine)
            log_audit("CREATE", "CATALOG_FINE", f"Katalog-Strafe '{description}' ({amount}, {category}) für {team} erstellt.")
            db.session.commit()
            message = f'Neue Strafe "{description}" für {team} wurde hinzugefügt.'
            success = True
            html = render_template('_fine_item.html', fine=new_fine)
        except ValueError:
            message = 'Ungültiger Betrag.'
    
    if is_ajax():
        if success:
            target_list = f'#fines-catalog-list-{team}'
            return jsonify({'success': True, 'message': message, 'html': html, 'appendTo': target_list})
        else:
            return jsonify({'success': False, 'message': message})
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin', season=request.args.get('season')))



@app.route('/admin/edit-fine/<int:fine_id>', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def edit_fine(fine_id):
    try:
        fine = Fine.query.get_or_404(fine_id)
        description = request.form.get('description', '').strip()
        amount_str = request.form.get('amount')
        fine_type = request.form.get('type')
        category = request.form.get('category', 'general')
        
        # Permission Check
        if fine.team == 'team1' and current_user.role not in ['admin', 'strafen_manager_1', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if (fine.team == 'team2' or fine.team is None) and current_user.role not in ['admin', 'strafen_manager_2', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        if not all([description, amount_str, fine_type]):
             return jsonify({'success': False, 'message': 'Alle Felder müssen ausgefüllt sein.'})

        amount = float(amount_str)
        
        # Change Detection
        if fine.description != description or abs(fine.amount - amount) > 0.001 or fine.type != fine_type or fine.category != category:
            log_audit("UPDATE", "CATALOG_FINE", f"Katalog-Strafe ID {fine.id} aktualisiert: {fine.description}->{description}, {fine.amount}->{amount}, {fine.category}->{category}")
            
            fine.description = description
            fine.amount = amount
            fine.type = fine_type
            fine.category = category
            db.session.commit()
            
        html = render_template('_fine_item.html', fine=fine)
        return jsonify({
            'success': True, 
            'message': f'Strafe "{description}" aktualisiert.', 
            'updateElement': {'selector': f'#fine-item-{fine.id}', 'html': html, 'outerHTML': True}
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Fehler: {e}'})

@app.route('/admin/delete-fine/<int:fine_id>', methods=['POST'])
@login_required
@role_required(['admin', 'strafen_manager_1', 'strafen_manager_2', 'trikot_manager_1', 'trikot_manager_2'])
def delete_fine(fine_id):
    try:
        fine = Fine.query.get_or_404(fine_id)
        
        # Permission Check
        if fine.team == 'team1' and current_user.role not in ['admin', 'strafen_manager_1', 'trikot_manager_1']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 1.'})
        if (fine.team == 'team2' or fine.team is None) and current_user.role not in ['admin', 'strafen_manager_2', 'trikot_manager_2']:
             return jsonify({'success': False, 'message': 'Keine Berechtigung für Team 2.'})

        description = fine.description
        db.session.delete(fine)
        log_audit("DELETE", "CATALOG_FINE", f"Katalog-Strafe '{description}' gelöscht.")
        db.session.commit()
        message = f'Strafe "{description}" wurde gelöscht.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message, 'removeElement': f'#fine-item-{fine_id}'})
        
        flash(message, 'success')
        return redirect(url_for('admin'))
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Fehler: {e}'})
        
        flash(f'Fehler beim Löschen der Strafe: {e}', 'danger')
        return redirect(url_for('admin'))

# --- Log Deletion (mit Seiten-Reload) ---
@app.route('/admin/delete/transaction/<int:tx_id>', methods=['POST'])
@login_required
def delete_transaction(tx_id):
    try:
        tx = Transaction.query.get_or_404(tx_id)

        # Permission Check
        allowed = False
        # 1. Admin darf alles
        if current_user.role == 'admin':
            allowed = True
            
        # 2. Ersteller darf eigene Transaktion innerhalb von 30 Tagen löschen (Hauptregel für Manager)
        elif tx.created_by == current_user.username:
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(days=30):
                allowed = True
                
        # 3. Ausnahme: Verzugszuschlag darf IMMER von Strafenmanagern/Trikotmanagern gelöscht werden
        elif 'Verzugszuschlag' in tx.description:
            if tx.team == 'team1' and current_user.role in ['strafen_manager_1', 'trikot_manager_1']: allowed = True
            if tx.team == 'team2' and current_user.role in ['strafen_manager_2', 'trikot_manager_2']: allowed = True

        if not allowed:
             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                 return jsonify({'success': False, 'message': 'Keine Berechtigung zum Löschen dieser Transaktion.'})
             flash('Keine Berechtigung.', 'danger'); return redirect(url_for('admin'))

        db.session.delete(tx)
        log_audit("DELETE", "TRANSACTION", f"Transaktion '{tx.description}' ({tx.amount}€) von {tx.player.name} gelöscht.")
        
        # --- NEW: Recalculate Settlements ---
        if tx.category == 'fine' or tx.amount > 0:
             # Only relevant if we deleted a Fine or a Payment
             recalculate_settlements(tx.player_id, tx.team)
        
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        message = 'Geld-Transaktion erfolgreich gelöscht.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message, 'reload': True})
        
        flash(message, 'success')
        return redirect(url_for('admin'))
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Fehler: {e}'})
        
        flash(f'Fehler beim Löschen der Transaktion: {e}', 'danger')
        return redirect(url_for('admin'))

@app.route('/admin/delete/transaction-bulk/<int:tx_id>', methods=['POST'])
@login_required
def delete_transaction_bulk(tx_id):
    try:
        tx = Transaction.query.get_or_404(tx_id)

        # 1. PERMISSION CHECK (Copy of delete_transaction logic)
        allowed = False
        # 1. Admin darf alles
        if current_user.role == 'admin':
            allowed = True
            
        # 2. Ersteller darf eigene Transaktion innerhalb von 30 Tagen löschen (Hauptregel für Manager)
        elif tx.created_by == current_user.username:
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(days=30):
                allowed = True
                
        # 3. Ausnahme: Verzugszuschlag darf IMMER von Strafenmanagern/Trikotmanagern gelöscht werden
        elif 'Verzugszuschlag' in tx.description:
            if tx.team == 'team1' and current_user.role in ['strafen_manager_1', 'trikot_manager_1']: allowed = True
            if tx.team == 'team2' and current_user.role in ['strafen_manager_2', 'trikot_manager_2']: allowed = True
        
        if not allowed:
            return jsonify({'success': False, 'message': 'Keine Berechtigung zum Löschen dieses Eintrags.'}), 403

        # 2. FIND GROUP (Trikotgeld = Negative Amount, Same Description, Same Date, Same Team, Same Creator)
        # We also check created_at proximity to avoid deleting identical bookings from different times (though rare)
        # But users request "Combine Delete", so they likely mean the logical group.
        
        siblings = Transaction.query.filter(
            Transaction.id != tx.id,
            Transaction.team == tx.team,
            Transaction.date == tx.date,
            Transaction.description == tx.description,
            Transaction.created_by == tx.created_by
        ).all()
        
        group_to_delete = [tx] + siblings
        count = len(group_to_delete)
        
        for item in group_to_delete:
            db.session.delete(item)
            
        log_audit("DELETE", "TRANSACTION_BULK", f"{count} Transaktionen '{tx.description}' von {tx.created_by} gelöscht.")
        
        # --- NEW: Recalculate Settlements ---
        # Since all items in group have same TEAM and functionally same context,
        # we can just take the first item's team. But they might be different players.
        # We need to recalc for EACH unique player involved.
        affected_players = set(item.player_id for item in group_to_delete)
        for pid in affected_players:
            recalculate_settlements(pid, tx.team)

        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        return jsonify({'success': True, 'reload': True, 'message': f'{count} Buchungen wurden gelöscht.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Fehler: {str(e)}'}), 500

@app.route('/admin/delete/kistl-transaction/<int:tx_id>', methods=['POST'])
@login_required
def delete_kistl_transaction(tx_id):
    try:
        tx = KistlTransaction.query.get_or_404(tx_id)
        
        # Permission Check
        allowed = False
        if current_user.role == 'admin': 
            allowed = True
        elif tx.created_by == current_user.username:
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(hours=24):
                allowed = True
        
        if not allowed:
             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                 return jsonify({'success': False, 'message': 'Keine Berechtigung.'})
             flash('Keine Berechtigung.', 'danger'); return redirect(url_for('admin'))

        db.session.delete(tx)
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        log_audit("DELETE", "KISTL_TRANSACTION", f"Kistl-Transaktion '{tx.description}' ({tx.amount}) von {tx.player.name} gelöscht.")

        message = 'Kistl-Transaktion erfolgreich gelöscht.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message, 'reload': True})
        
        flash(message, 'success')
        return redirect(url_for('admin'))
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Fehler: {e}'})

        flash(f'Fehler beim Löschen der Kistl-Transaktion: {e}', 'danger')
        return redirect(url_for('admin'))

@app.route('/admin/delete/team-expense/<int:tx_id>', methods=['POST'])
@login_required
def delete_team_expense(tx_id):
    try:
        tx = TeamExpense.query.get_or_404(tx_id)

        # Permission Check
        allowed = False
        if current_user.role == 'admin': 
            allowed = True
        elif tx.team == 'team1' and current_user.role in ['trikot_manager_1', 'strafen_manager_1']: 
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(hours=24):
                allowed = True
        elif tx.team == 'team2' and current_user.role in ['trikot_manager_2', 'strafen_manager_2']: 
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(hours=24):
                allowed = True
        elif tx.created_by == current_user.username:
            if tx.created_at and tx.created_at > datetime.utcnow() - timedelta(hours=24):
                allowed = True

        if not allowed:
             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                 return jsonify({'success': False, 'message': 'Keine Berechtigung.'});
             return redirect(url_for('admin'))
             
        db.session.delete(tx)
        db.session.commit()
        trigger_image_regeneration()  # Update Cache
        
        log_audit("DELETE", "EXPENSE", f"Teamausgabe '{tx.description}' ({tx.amount}€, {tx.team}) gelöscht.")

        message = 'Teamausgabe erfolgreich gelöscht.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message, 'reload': True})
        
        flash(message, 'success')
        return redirect(url_for('admin'))
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Fehler: {e}'})

        flash(f'Fehler beim Löschen der Teamausgabe: {e}', 'danger')
        return redirect(url_for('admin'))

# app.py


@app.route('/admin/approve-game-fee/<int:request_id>', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2'])
def approve_game_fee(request_id):
    req = PendingGameFee.query.get_or_404(request_id)
    
    # Check permissions for approval
    # Team 1 req -> Admin or Trikot1
    # Check permissions for approval
    # Vier-Augen-Prinzip: EIGENE Requests dürfen NIE selbst genehmigt werden (außer Admin evtl, aber selbst da macht es Sinn es zu trennen, 
    # aber Admin ist Admin. User Anforderung: "Bestätigung des ANDEREN").
    # Also: Wenn ich Creator bin, darf ich NICHT approven.
    
    is_creator = (req.created_by == current_user.username)
    if is_creator and current_user.role != 'admin': # Admin darf alles (Notfall)
         flash('Eigene Anträge können nicht selbst freigegeben werden.', 'danger')
         return redirect(url_for('admin'))

    if req.team == 'team1' and current_user.role not in ['admin', 'trikot_manager_1', 'trikot_manager_2']: # TM2 darf T1 genehmigen (Cross-Check)
         # Wait, user said "Bestätigung des ANDEREN Trikotgeldmanagers".
         # So TM2 approves TM1.
         # Current Logic allowed T1/Admin. Now allowing TM2 too?
         pass
         
    # RE-EVALUATING PERMISSION LOGIC FOR CROSS-APPROVAL
    # Can allow:
    # 1. Admin (always)
    # 2. Opposite Manager (to REVIEW/RETURN)
    # 3. Team Manager (to BOOK, if not creator)
    
    can_approve = False
    action_type = "BOOK" # or "RETURN"
    
    if current_user.role == 'admin': 
        can_approve = True
        action_type = "BOOK"

    # Team 1 Logic
    if req.team == 'team1':
        # TM2 can approve (Review Step) -> Triggers RETURN
        if current_user.role == 'trikot_manager_2': 
            can_approve = True
            action_type = "RETURN"
            
        # TM1 can approve (Final Step) -> Triggers BOOK
        # Only if he is NOT the current creator (meaning TM2 sent it back)
        if current_user.role == 'trikot_manager_1' and not is_creator:
            can_approve = True
            action_type = "BOOK"

    # Team 2 Logic
    if req.team == 'team2':
        # TM1 can approve (Review Step) -> Triggers RETURN
        if current_user.role == 'trikot_manager_1': 
            can_approve = True
            action_type = "RETURN"
            
        # TM2 can approve (Final Step) -> Triggers BOOK
        # Only if he is NOT the current creator (meaning TM1 sent it back)
        if current_user.role == 'trikot_manager_2' and not is_creator:
            can_approve = True
            action_type = "BOOK"

    if not can_approve:
         flash('Keine Berechtigung zur Freigabe (Vier-Augen-Prinzip) oder falscher Workflow-Schritt.', 'danger')
         return redirect(url_for('admin'))

    try:
        # Check Form Data Override (User edited the list)
        new_player_ids = []
        if 'player_ids' in request.form:
             new_player_ids = request.form.getlist('player_ids') # Returns strings
             new_player_ids = [int(pid) for pid in new_player_ids]
             new_player_ids.sort()
        else:
             try:
                 # Fallback if somehow empty or different form (should not happen with modal)
                 raw = json.loads(req.player_ids_json)
                 if isinstance(raw, dict):
                     new_player_ids = raw.get('current', [])
                 else:
                     new_player_ids = raw
             except: new_player_ids = []
             
        try:
             raw = json.loads(req.player_ids_json)
             if isinstance(raw, dict):
                 old_player_ids = [int(pid) for pid in raw.get('current', [])]
             else:
                 old_player_ids = [int(pid) for pid in raw]
        except: old_player_ids = []
        old_player_ids.sort()
        
        has_changes = (new_player_ids != old_player_ids)
        
        # Override action type based on changes
        if action_type == "RETURN" and not has_changes:
            # If reviewer made NO changes, we can approve directly (User requirement)
            action_type = "BOOK"
            
        if action_type == "BOOK" and has_changes and current_user.role != 'admin':
            # If owner/finalizer made changes, it must go back to the other manager for review
            action_type = "RETURN"
        
        # --- RETURN LOGIC (Ping Pong) ---
        if action_type == "RETURN":
            # Update the request instead of booking
            req.player_ids_json = json.dumps(new_player_ids)
            req.created_by = current_user.username # Flip ownership
            
            db.session.commit()
            
            flash(f'Antrag aktualisiert und zur erneuten Prüfung zurückgegeben (Änderungen erkannt).', 'info')
            
            # Optional: Notify original sender via Push
            return redirect(url_for('admin'))
            
        # --- BOOK LOGIC (Finalize) ---     
        # Use new_player_ids for booking
        player_ids = [str(pid) for pid in new_player_ids] 
        
        settings_query = KasseSetting.query.all()
        settings = {s.key: s.value for s in settings_query}
        game_fee = float(settings.get('game_fee', '3.00'))
        
        base_desc = f"gg. {req.opponent}" if not req.opponent.startswith("gg.") else req.opponent
        
        # Check for existing game (Rückrunde logic)
        existing = Transaction.query.filter(
            Transaction.description.like(f"{base_desc}%"),
            Transaction.date.between(g.start_date, g.end_date),
            Transaction.team == req.team
        ).first()
        desc = f"{base_desc} (Rück)" if existing else base_desc

        team_label = "1. Mannschaft" if req.team == 'team1' else "2. Mannschaft"
        desc_with_team = f"{desc} ({team_label})"
        
        count = 0
        skipped_info = []
        
        for p_id_str in player_ids:
            p_id = int(p_id_str)
            # Check for double booking (Same weekend +/- 2 days)
            # Prevent paying twice for games close to each other
            start_check = req.date - timedelta(days=2)
            end_check = req.date + timedelta(days=2)
            
            dup = Transaction.query.filter(
                Transaction.player_id == p_id,
                Transaction.date.between(start_check, end_check),
                Transaction.description.ilike('%gg.%')
            ).first()
            
            if dup:
                p_obj = Player.query.get(p_id)
                p_name = p_obj.name if p_obj else str(p_id)
                skipped_info.append(p_name)
                continue

            tx = Transaction(
                player_id=p_id,
                description=desc_with_team,
                amount=-game_fee,
                date=req.date,
                team=req.team,
                created_by=f"{current_user.username} (Approved {req.created_by})"
            )
            db.session.add(tx)
            count += 1
            
        db.session.delete(req)
        db.session.commit()
        
        log_audit("CREATE", "GAME_FEE", f"Trikotgeld ({team_label}) für {count} Spieler verbucht (Gegner: {req.opponent}).")

        msg = f'Trikotgeld ({req.team}) für {count} Spieler erfolgreich verbucht.'
        if skipped_info:
            msg += f" (Übersprungen da bereits gebucht: {', '.join(skipped_info)})"
            
        flash(msg, 'success' if count > 0 else 'warning')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler bei der Freigabe: {e}', 'danger')

        
    return redirect(url_for('admin'))

@app.route('/admin/reject-game-fee/<int:request_id>', methods=['POST'])
@login_required
def reject_game_fee(request_id):
    req = PendingGameFee.query.get_or_404(request_id)
    
    # Check permissions: Admin, Target Manager, OR Creator
    is_creator = (req.created_by == current_user.username)
    has_permission = False
    
    if req.team == 'team1' and current_user.role in ['admin', 'trikot_manager_1']:
        has_permission = True
    if req.team == 'team2' and current_user.role in ['admin', 'trikot_manager_2']:
        has_permission = True
        
    if not (has_permission or is_creator):
        flash('Keine Berechtigung diesen Antrag zu löschen.', 'danger')
        return redirect(url_for('admin'))

    db.session.delete(req)
    db.session.commit()
    log_audit("DELETE", "GAME_FEE_REQUEST", f"Trikotgeld-Antrag {req.team} gg. {req.opponent} abgelehnt/gelöscht.")
    
    if is_creator and not has_permission:
        flash('Antrag erfolgreich zurückgezogen.', 'info')
    else:
        flash('Antrag abgelehnt/gelöscht.', 'info')
        
    return redirect(url_for('admin'))


@app.route('/admin/add-game-fee', methods=['POST'])
@login_required
@role_required(['admin', 'trikot_manager_1', 'trikot_manager_2'])
def add_game_fee():
    season = request.args.get('season')
    try:
        settings_query = KasseSetting.query.all()
        settings = {s.key: s.value for s in settings_query}
        game_fee = float(settings.get('game_fee', '3.00'))
        
        def parse_d(d_str):
                if not d_str: return datetime.utcnow().date()
                return datetime.strptime(d_str, '%Y-%m-%d').date()

        team1_player_ids = set(request.form.getlist('team1_player_ids'))
        team1_free_ids = set(request.form.getlist('team1_free_ids'))
        date_team1 = parse_d(request.form.get('date_team1'))
        opp_team1 = request.form.get('opponent_team1', '').strip()
        spielfrei_team1 = request.form.get('spielfrei_team1') == '1'
        
        team2_player_ids = set(request.form.getlist('team2_player_ids'))
        team2_free_ids = set(request.form.getlist('team2_free_ids'))
        date_team2 = parse_d(request.form.get('date_team2'))
        opp_team2 = request.form.get('opponent_team2', '').strip()
        spielfrei_team2 = request.form.get('spielfrei_team2') == '1'


        def process_team(team_str, p_ids, free_ids, date_val, opp_val, can_direct_book, reviewer_role, is_spielfrei=False):
            


            if is_spielfrei:
                # User explitzit checked "Spielfrei".
                # If there is a pending request, delete/withdraw it.
                pending = PendingGameFee.query.filter_by(team=team_str).first()
                if pending:
                    db.session.delete(pending)
                    db.session.commit()
                    flash(f'{team_str}: Als Spielfrei markiert. Vorhandener Antrag wurde gelöscht.', 'info')
                return

            if not p_ids and not free_ids and not opp_val: return

            if (p_ids or free_ids) and not opp_val:
                flash(f'Bitte Gegner für {team_str} eingeben.', 'warning')
                return
            
            # Direkt die übermittelten IDs verwenden — der Mensch entscheidet, wer gebucht wird
            current_ids_set = set(int(x) for x in p_ids)
            current_free_ids_set = set(int(x) for x in free_ids)
            if not current_ids_set and not current_free_ids_set: return

            pending = PendingGameFee.query.filter_by(team=team_str).first()
            
            if pending:
                try: 
                    raw = json.loads(pending.player_ids_json)
                    if isinstance(raw, dict):
                        old_ids = set(int(x) for x in raw.get('current', []))
                        old_free_ids = set(int(x) for x in raw.get('current_free', []))
                    else:
                        old_ids = set(int(x) for x in raw)
                        old_free_ids = set()
                except: old_ids = set(); old_free_ids = set()
                old_date = pending.date
                old_opp = pending.opponent
                
                has_changes = (old_ids != current_ids_set) or (old_free_ids != current_free_ids_set) or (old_date != date_val) or (old_opp != opp_val)
                # Rollenbasiert: nur der andere Manager (reviewer_role) oder Admin kann bestätigen/buchen
                can_book = current_user.role in ['admin', reviewer_role]
                
                if has_changes:
                    # Save with History (Old IDs become 'previous')
                    # FIX: Save current IDs as Integers explicitly
                    pending.player_ids_json = json.dumps({
                        'current': list(current_ids_set),
                        'current_free': list(current_free_ids_set),
                        'previous': list(old_ids),
                        'previous_free': list(old_free_ids) 
                    })
                    pending.date = date_val
                    pending.opponent = opp_val
                    pending.created_by = current_user.username
                    pending.created_at = datetime.utcnow()
                    db.session.commit()
                    
                    if can_book: flash(f'Antrag für {team_str} wurde aktualisiert (und zurückgegeben).', 'info')
                    else: flash(f'Antrag für {team_str} wurde aktualisiert.', 'info')
                    
                    # Update Notification
                    try:
                        recipients = User.query.filter(User.role.in_(['admin', 'trikot_manager_1', 'trikot_manager_2'])).all()
                        for u in recipients:
                            if u.player_id and u.username != current_user.username:
                                send_push_notification(player_id=u.player_id, title=f"Update: Trikotgeld {team_str}", body=f"{current_user.username} hat den Antrag aktualisiert.", url=url_for('admin', season=season, _external=True))
                    except Exception as e: 
                        push_logger.error(f"Push Error (Update): {e}")

                else:
                    if can_book:
                        base_desc = f"gg. {opp_val}" if not opp_val.startswith("gg.") else opp_val
                        team_label = "1. Mannschaft" if team_str == 'team1' else "2. Mannschaft"
                        desc_with_team = f"{base_desc} ({team_label})"
                        count = 0
                        # PAID
                        for pid in current_ids_set:
                             db.session.add(Transaction(
                                 player_id=int(pid), description=desc_with_team, amount=-game_fee, 
                                 date=date_val, team=team_str, created_by=current_user.username
                             ))
                             count += 1
                        # FREE
                        for pid in current_free_ids_set:
                             db.session.add(Transaction(
                                 player_id=int(pid), description=desc_with_team, amount=0, 
                                 date=date_val, team=team_str, created_by=current_user.username
                             ))
                             count += 1
                        
                        db.session.delete(pending)
                        db.session.commit()
                        trigger_image_regeneration()
                        log_audit("CREATE", "GAME_FEE", f"Trikotgeld {team_label} ({count} Spieler) genehmigt und verbucht.")
                        flash(f'Trikotgeld {team_label} erfolgreich verbucht ({count} Spieler).', 'success')
                        
                        # Booking Notification
                        try:
                            recipients = User.query.filter(User.role.in_(['admin', 'trikot_manager_1', 'trikot_manager_2'])).all()
                            for u in recipients:
                                if u.player_id and u.username != current_user.username:
                                     send_push_notification(player_id=u.player_id, title=f"Gebucht: Trikotgeld {team_str}", body=f"Durch {current_user.username} genehmigt und verbucht.", url=url_for('kasse', team=team_str, season=season, _external=True))
                        except Exception as e:
                             push_logger.error(f"Push Error (Booking): {e}")

                    else:
                        flash(f'Antrag für {team_str} ist bereits eingereicht und wartet auf Prüfung.', 'info')
            else:
                if can_direct_book:
                    base_desc = f"gg. {opp_val}" if not opp_val.startswith("gg.") else opp_val
                    team_label = "1. Mannschaft" if team_str == 'team1' else "2. Mannschaft"
                    desc_with_team = f"{base_desc} ({team_label})"
                    count = 0
                    for pid in current_ids_set:
                             db.session.add(Transaction(
                                 player_id=int(pid), description=desc_with_team, amount=-game_fee, 
                                 date=date_val, team=team_str, created_by=current_user.username
                             ))
                             count += 1
                    for pid in current_free_ids_set:
                             db.session.add(Transaction(
                                 player_id=int(pid), description=desc_with_team, amount=0, 
                                 date=date_val, team=team_str, created_by=current_user.username
                             ))
                             count += 1
                    db.session.commit()
                    trigger_image_regeneration()
                    log_audit("CREATE", "GAME_FEE", f"Trikotgeld {team_label} ({count} Spieler) direkt verbucht.")
                    flash(f'Trikotgeld {team_label} direkt verbucht ({count} Spieler).', 'success')
                else:
                    # FIX: Save as dict with free ids
                    req_data = {
                        "current": list(current_ids_set),
                        "current_free": list(current_free_ids_set)
                    }
                    req = PendingGameFee(
                        team=team_str, date=date_val, opponent=opp_val,
                        player_ids_json=json.dumps(req_data), created_by=current_user.username
                    )
                    db.session.add(req)
                    db.session.commit()
                    log_audit("CREATE", "GAME_FEE_REQUEST", f"Trikotgeld-Antrag {team_str} erstellt.")
                    flash(f"Antrag für {team_str} erstellt.", "info")
                    try:
                        recipients = User.query.filter(User.role.in_(['admin', reviewer_role])).all()
                        for u in recipients:
                            if u.player_id and u.username != current_user.username:
                                send_push_notification(player_id=u.player_id, title=f"Freigabe: Trikotgeld {team_str}", body=f"{current_user.username} beantragt Buchung gg. {opp_val}", url=url_for('admin', season=season, _external=True))
                    except Exception as e:
                        push_logger.error(f"Push Error (Create): {e}")

        # Wenn das andere Team Spielfrei hat, kann das eigene Team direkt buchen (kein Antrag nötig)
        can_book_t1_direct = (current_user.role == 'admin') or spielfrei_team2
        can_book_t2_direct = (current_user.role == 'admin') or spielfrei_team1

        process_team('team1', team1_player_ids, team1_free_ids, date_team1, opp_team1, can_book_t1_direct, 'trikot_manager_2', spielfrei_team1)
        process_team('team2', team2_player_ids, team2_free_ids, date_team2, opp_team2, can_book_t2_direct, 'trikot_manager_1', spielfrei_team2)
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Speichern: {e}', 'danger')

    return redirect(url_for('admin', season=season))

@app.route('/api/check-game-date', methods=['POST'])
@login_required
@role_required(['admin'])
def check_game_date():
    date_str = request.form.get('date')
    if not date_str:
        return jsonify({'exists': False}) # Keine Daten, also kann nichts existieren

    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        game_on_same_day = Transaction.query.filter(
            Transaction.date == check_date,
            Transaction.description.ilike('%gg.%')
        ).first()

        if game_on_same_day:
            return jsonify({
                'exists': True,
                'description': game_on_same_day.description
            })
        else:
            return jsonify({'exists': False})

    except (ValueError, TypeError):
        # Bei ungültigem Datum einfach weitermachen, die Hauptroute fängt das ab
        return jsonify({'exists': False})

@app.route('/spieltag-log')
@login_required
@role_required(['admin', 'viewer', 'trikot_manager_1', 'trikot_manager_2'])
def spieltag_log():
    log_audit("ACCESS", "GAME_LOG", "Spieltag-Log Übersicht eingesehen.")
    # Wir holen alle Transaktionen, die wie ein Spiel aussehen (enthalten "gg.")
    # Wir gruppieren jetzt in Python, um gespielt vs nicht gespielt zu trennen.
    transactions = db.session.query(
        Transaction.date,
        Transaction.description,
        Transaction.team,
        Transaction.amount
    ).filter(
        Transaction.description.ilike('%gg.%')
    ).all()

    games_dict = {}
    for date, desc, team, amount in transactions:
        key = (date, desc, team)
        if key not in games_dict:
            games_dict[key] = {
                'date': date,
                'game_desc': desc,
                'team': team,
                'participants': 0,
                'active_count': 0,
                'zero_count': 0
            }
        
        games_dict[key]['participants'] += 1
        if amount < 0:
            games_dict[key]['active_count'] += 1
        elif amount == 0:
            games_dict[key]['zero_count'] += 1

    # Filtere Dummy-Spiele heraus, bei denen niemand aktiv gespielt hat (z.B. alte 1. Mannschaft Einträge)
    valid_games = [g for g in games_dict.values() if g['active_count'] > 0]

    # Sortieren nach Datum absteigend
    games = sorted(valid_games, key=lambda x: x['date'], reverse=True)

    return render_template('spieltag_log.html', games=games)

@app.route('/spieltag-log/<game_date_str>/<game_description_encoded>')
@login_required
@role_required(['admin', 'viewer', 'trikot_manager_1', 'trikot_manager_2'])
def spieltag_detail(game_date_str, game_description_encoded):
    try:
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        game_description = unquote_plus(game_description_encoded)
        filter_team = request.args.get('team')
        log_audit("ACCESS", "GAME_LOG_DETAIL", f"Spieltag-Details eingesehen: {game_date} ({game_description}, Team: {filter_team})")
    except ValueError:
        flash("Ungültiges Datum im Link.", "danger")
        return redirect(url_for('spieltag_log'))

    # Query aufbauen
    query = Transaction.query.filter(
        Transaction.date == game_date,
        Transaction.description == game_description
    )
    
    if filter_team:
        query = query.filter(Transaction.team == filter_team)
        
    all_tx_for_game = query.all()
    
    # Gesamtsumme berechnen
    total_amount = sum(abs(tx.amount) for tx in all_tx_for_game)

    # Teile die Spieler in Listen auf
    paid_players_tx = [tx for tx in all_tx_for_game if tx.amount < 0]
    zero_amount_players_tx = [tx for tx in all_tx_for_game if tx.amount == 0]
    
    return render_template('spieltag_detail.html',
                           game_date=game_date,
                           game_description=game_description,
                           paid_players_tx=paid_players_tx,
                           zero_amount_players_tx=zero_amount_players_tx,
                           total_amount=total_amount,
                           team=filter_team)

@app.route('/admin/app/add-user', methods=['POST'])
@login_required
@role_required(['admin'])
def add_user():
    player_id = request.form.get('player_id')
    password = request.form.get('password')
    role = request.form.get('role')

    if not all([player_id, password, role]):
        flash("Bitte Spieler, Passwort und Rolle wählen.", 'danger')
        return redirect(url_for('admin'))

    # Spieler laden
    player = Player.query.get(player_id)
    if not player:
        flash("Ungültiger Spieler ausgewählt.", 'danger')
        return redirect(url_for('admin'))

    # Username ist automatisch der Spielername
    username = player.name

    # Check 1: Gibt es schon einen User mit diesem Namen?
    if User.query.filter_by(username=username).first():
        log_audit("SECURITY", "USER_CREATE_FAILED", f"Benutzeranlage gescheitert: Name '{username}' bereits vergeben.")
        flash(f"Ein Benutzer mit dem Namen '{username}' existiert bereits.", 'warning')
        return redirect(url_for('admin'))

    # Check 2: Hat dieser Spieler schon IRGENDEINEN User verknüpft?
    if User.query.filter_by(player_id=player.id).first():
        log_audit("SECURITY", "USER_CREATE_FAILED", f"Benutzeranlage gescheitert: Spieler '{player.name}' hat bereits einen Account.")
        flash(f"Der Spieler '{player.name}' hat bereits einen verknüpften Account.", 'warning')
        return redirect(url_for('admin'))

    if role not in VALID_ROLES:
        flash("Ungültige Rolle ausgewählt.", "danger")
        return redirect(url_for('admin'))

    new_user = User(username=username, role=role, player_id=player.id)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    log_audit("CREATE", "USER", f"Benutzer '{username}' mit Rolle '{role}' angelegt.")
    flash(f"Benutzer '{username}' wurde erfolgreich angelegt und verknüpft.", "success")
    return redirect(url_for('admin'))

@app.route('/admin/app/edit-user/<int:user_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Du kannst deinen eigenen Account nicht bearbeiten.", "warning")
        return redirect(url_for('admin'))
    new_password = request.form.get('password')
    new_role = request.form.get('role')
    if new_role not in VALID_ROLES:
        flash("Ungültige Rolle ausgewählt.", "danger")
        return redirect(url_for('admin'))
    
    # Handle secondary role
    secondary_role = request.form.get('secondary_role')
    if secondary_role:
        if secondary_role == 'none':
            user.secondary_role = None
        elif secondary_role in VALID_ROLES:
            user.secondary_role = secondary_role
        else:
            flash("Ungültige Sekundärrolle ausgewählt.", "warning")

    user.role = new_role
    if new_password:
        user.set_password(new_password)
        flash(f"Rolle und Passwort für '{user.username}' aktualisiert.", "success")
    else:
        flash(f"Rolle für '{user.username}' aktualisiert.", "success")
    
    db.session.commit()
    log_audit("UPDATE", "USER", f"Benutzer '{user.username}' aktualisiert (Rolle: {new_role}, Passwort geändert: {bool(new_password)}).")
    return redirect(url_for('admin'))

@app.route('/admin/app/delete-user/<int:user_id>')
@login_required
@role_required(['admin'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Du kannst deinen eigenen Account nicht löschen.", "danger")
        return redirect(url_for('admin'))
    db.session.delete(user)
    db.session.commit()
    log_audit("DELETE", "USER", f"Benutzer '{user.username}' gelöscht.")
    flash(f"Benutzer '{user.username}' wurde gelöscht.", "success")
    return redirect(url_for('admin'))

@app.route('/admin/app/save-settings', methods=['POST'])
@login_required
@role_required(['admin'])
def save_settings():
    # Helper to handle checkboxes (if present='1', else '0')
    doubling_t1 = '1' if request.form.get('doubling_active_team1') else '0'
    doubling_t2 = '1' if request.form.get('doubling_active_team2') else '0'

    settings_to_save = {
        'paypal_link_team1_general': request.form.get('paypal_link_team1_general'),
        'paypal_link_team1_fine': request.form.get('paypal_link_team1_fine'),
        'paypal_link_team2_general': request.form.get('paypal_link_team2_general'),
        'paypal_link_team2_fine': request.form.get('paypal_link_team2_fine'),
        'paypal_email_team1_general': request.form.get('paypal_email_team1_general'),
        'paypal_email_team1_fine': request.form.get('paypal_email_team1_fine'),
        'paypal_email_team2_general': request.form.get('paypal_email_team2_general'),
        'paypal_email_team2_fine': request.form.get('paypal_email_team2_fine'),
        'game_fee': request.form.get('game_fee'),
        'session_lifetime_days': request.form.get('session_lifetime_days'),
        'doubling_active_team1': doubling_t1,
        'doubling_active_team2': doubling_t2
    }
    for key, value in settings_to_save.items():
        if value is None: continue # Skip if not in form
        setting = KasseSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            db.session.add(KasseSetting(key=key, value=value))
    db.session.commit()
    log_audit("UPDATE", "SETTINGS", "Globale Einstellungen wurden aktualisiert.")
    flash("Globale Einstellungen wurden gespeichert.", "success")
    return redirect(url_for('admin'))

@app.route('/admin/setup/balances', methods=['POST'])
@login_required
@role_required(['admin'])
def setup_balances():
    try:
        # 1. Update Global Team Balances
        balance_t1 = request.form.get('team_balance_team1')
        if balance_t1:
            setting = KasseSetting.query.filter_by(key='start_balance_team1').first()
            if setting: setting.value = balance_t1
            else: db.session.add(KasseSetting(key='start_balance_team1', value=balance_t1))
            
        balance_t2 = request.form.get('team_balance_team2')
        if balance_t2:
            setting = KasseSetting.query.filter_by(key='start_balance_team2').first()
            if setting: setting.value = balance_t2
            else: db.session.add(KasseSetting(key='start_balance_team2', value=balance_t2))
            
            # Legacy/Fallback: auch 'start_balance' updaten, falls Logik darauf zurückgreift
            setting_legacy = KasseSetting.query.filter_by(key='start_balance').first()
            if setting_legacy: setting_legacy.value = balance_t2
            else: db.session.add(KasseSetting(key='start_balance', value=balance_t2))

        # 2. Update Player Balances for Team 1 & Team 2
        for key, value in request.form.items():
            if not value: continue
            
            # Format: player_{id}_team{1|2}
            if key.startswith('player_') and '_team' in key:
                parts = key.split('_')
                # parts[0]="player", parts[1]=id, parts[2]="team1"/"team2"
                if len(parts) >= 3:
                    player_id = int(parts[1])
                    team_str = parts[2] # "team1" or "team2"
                    team_label = "1. Mannschaft" if team_str == 'team1' else "2. Mannschaft"
                    desc_with_team = f"Startguthaben ({team_label})"
                    
                    tx = Transaction.query.filter_by(player_id=player_id, description=desc_with_team, team=team_str).first()
                    
                    # Migration/Fallback: check old format
                    if not tx:
                        tx = Transaction.query.filter_by(player_id=player_id, description="Startguthaben", team=team_str).first()
                        if tx:
                            tx.description = desc_with_team # Update description
                    
                    # Migration/Fallback: If no specific tx found, look for untyped one if saving to team2
                    if not tx and team_str == 'team2':
                         tx = Transaction.query.filter_by(player_id=player_id, description="Startguthaben", team=None).first()
                         if tx:
                             tx.description = desc_with_team
                             tx.team = team_str

                    if tx:
                        tx.amount = float(value)
                        tx.team = team_str # Ensure correct team is set
                    else:
                        db.session.add(Transaction(
                            player_id=player_id, 
                            description=desc_with_team, 
                            amount=float(value),
                            team=team_str,
                            created_by=current_user.username
                        ))
                        
        db.session.commit()
        log_audit("UPDATE", "BALANCES", "Startguthaben (Global/Spieler) wurden aktualisiert.")
        flash("Startwerte erfolgreich gespeichert.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Fehler beim Speichern: {e}", "danger")
    return redirect(url_for('admin'))

@app.route('/admin/backup/download')
@login_required
@role_required(['admin'])
def download_backup():
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.read_sql_table('player', db.engine).to_excel(writer, sheet_name='Spieler', index=False)
            pd.read_sql_table('fine', db.engine).to_excel(writer, sheet_name='Strafenkatalog', index=False)
            pd.read_sql_table('transaction', db.engine).to_excel(writer, sheet_name='Geld-Transaktionen', index=False)
            pd.read_sql_table('kistl_transaction', db.engine).to_excel(writer, sheet_name='Kistl-Transaktionen', index=False)
            pd.read_sql_table('team_expense_real', db.engine).to_excel(writer, sheet_name='Teamausgaben', index=False)
            pd.read_sql_table('kasse_settings', db.engine).to_excel(writer, sheet_name='Kassen-Einstellungen', index=False)
            pd.read_sql_table('admin_user', db.engine).to_excel(writer, sheet_name='Admin-Benutzer', index=False)
        output.seek(0)
        filename = f"backup_mannschaftskasse_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        log_audit("DOWNLOAD", "BACKUP", f"Datenbank-Backup '{filename}' (Excel) wurde heruntergeladen.")
        return send_file(output, download_name=filename, as_attachment=True)
    except Exception as e: flash(f"Fehler beim Erstellen des Backups: {e}", "danger"); return redirect(url_for('admin'))

@app.route('/fupa-log')
@login_required
@role_required(['admin'])
def show_fupa_log():
    log_audit("ACCESS", "FUPA_LOG", "FuPa-System-Log eingesehen.")
    try:
        with open('fupa_log.txt', 'r') as f:
            # Lese die Datei rückwärts, um die neuesten Einträge oben zu haben
            content = f.readlines()
            content.reverse()
            log_content = "".join(content)
        return f'<pre>{log_content}</pre>'
    except FileNotFoundError:
        return "Log-Datei 'fupa_log.txt' noch nicht vorhanden. Bitte rufe die Admin-Seite auf, um sie zu erstellen."
    except Exception as e:
        return f"Fehler beim Lesen der Log-Datei: {e}"

# app.py

# --- NEUE API ROUTEN FÜR PUSH ---
@app.route('/api/vapid-public-key')
def get_vapid_public_key():
    return jsonify({'publicKey': VAPID_PUBLIC_KEY})
    
@app.route('/api/get-player-for-subscription', methods=['POST'])
def get_player_for_subscription():
    """Findet heraus, welcher Spieler zu einem Geräte-Abo gehört und gibt ID und Namen zurück."""
    subscription_data = request.get_json()
    if not subscription_data or 'endpoint' not in subscription_data:
        return jsonify({'error': 'Endpoint missing'}), 400
    
    endpoint_url = subscription_data['endpoint']
    sub_record = PushSubscription.query.filter_by(endpoint=endpoint_url).first()
    
    if sub_record:
        # Gib jetzt auch den Namen des Spielers zurück
        return jsonify({
            'player_id': sub_record.player_id,
            'player_name': sub_record.player.name 
        })
    else:
        return jsonify({'player_id': None, 'player_name': None})

@app.route('/api/check-current-user', methods=['POST'])
def check_current_user():
    """Prüft, ob der aktuelle Endpoint zu einem Spieler gehört."""
    subscription_data = request.get_json()
    if not subscription_data or 'endpoint' not in subscription_data:
        return jsonify({'is_current_user': False, 'player_id': None})
    
    endpoint_url = subscription_data['endpoint']
    sub_record = PushSubscription.query.filter_by(endpoint=endpoint_url).first()
    
    if sub_record:
        return jsonify({
            'is_current_user': True,
            'player_id': sub_record.player_id,
            'player_name': sub_record.player.name
        })
    else:
        return jsonify({'is_current_user': False, 'player_id': None})
        
@app.route('/api/subscribe/player/<int:player_id>', methods=['POST'])
def subscribe_player(player_id):
    """Meldet ein Gerät für einen Spieler an. Überschreibt bestehende Anmeldungen für dieses Gerät."""
    subscription_data = request.get_json()
    if not subscription_data or 'endpoint' not in subscription_data:
        return jsonify({'error': 'Subscription data missing'}), 400

    endpoint_url = subscription_data['endpoint']
    
    # Prüfe, ob dieses Gerät bereits für einen (anderen) Spieler registriert ist
    sub_record = PushSubscription.query.filter_by(endpoint=endpoint_url).first()
    
    if sub_record:
        # Gerät ist bekannt, aktualisiere den Spieler
        push_logger.info(f"Gerät {endpoint_url} wechselt von Spieler {sub_record.player_id} zu {player_id}.")
        sub_record.player_id = player_id
        sub_record.subscription_json = json.dumps(subscription_data)
    else:
        # Neues Gerät, lege neuen Eintrag an
        push_logger.info(f"Neues Gerät {endpoint_url} für Spieler {player_id} registriert.")
        sub_record = PushSubscription(
            player_id=player_id,
            endpoint=endpoint_url,
            subscription_json=json.dumps(subscription_data)
        )
        db.session.add(sub_record)
        
    db.session.commit()
    log_audit("PUSH", "SUBSCRIBE", f"Push-Abonnement für Spieler '{player_id}' (Endpoint: ...{endpoint_url[-20:]}) erstellt/aktualisiert.")
    return jsonify({'success': True})
    

    
@app.route('/admin/debug/view-push-log')
@login_required
@role_required(['admin'])
def view_push_log():
    log_audit("ACCESS", "PUSH_LOG", "Push-System-Log eingesehen.")
    try:
        with open('push_log.txt', 'r') as f:
            content = f.read().replace('\n', '<br>')
        return f'<pre style="font-family: monospace; white-space: pre-wrap;">{content}</pre>'
    except FileNotFoundError:
        return "Log-Datei 'push_log.txt' noch nicht vorhanden. Bitte löse zuerst eine Push-Benachrichtigung aus."
    except Exception as e:
        return f"Fehler beim Lesen der Log-Datei: {e}"

@app.route('/api/unsubscribe', methods=['POST'])
def unsubscribe_device():
    """Entfernt das Abo für ein bestimmtes Gerät, egal für welchen Spieler es war."""
    subscription_data = request.get_json()
    if not subscription_data or 'endpoint' not in subscription_data:
        return jsonify({'error': 'Subscription data missing'}), 400
        
    endpoint_url = subscription_data['endpoint']
    sub_record = PushSubscription.query.filter_by(endpoint=endpoint_url).first()

    if sub_record:
        p_id = sub_record.player_id
        push_logger.info(f"Gerät {endpoint_url} (Spieler {sub_record.player_id}) wird abgemeldet.")
        db.session.delete(sub_record)
        db.session.commit()
        log_audit("PUSH", "UNSUBSCRIBE", f"Push-Abonnement für Spieler-ID {p_id} entfernt (Abmeldung).")

    return jsonify({'success': True})

@app.route('/api/cleanup-orphaned-subs/<int:player_id>', methods=['POST'])
def cleanup_orphaned_subs(player_id):
    """
    Versucht, verwaiste Abos zu bereinigen, wenn der Client keine mehr hat.
    Logik: Wenn genau 1 Abo in der DB existiert, gehen wir davon aus, dass es das 
    alte Abo dieses Geräts war (vor Neuinstallation) und löschen es.
    """
    subs = PushSubscription.query.filter_by(player_id=player_id).all()
    count = len(subs)
    
    if count == 0:
        return jsonify({'status': 'none', 'message': 'Keine Abos vorhanden'})
    
    # User-Wunsch: Auch bei mehreren Abos löschen (Radikal-Schnitt beim Neustart der App)
    if count >= 1:
        try:
            for sub in subs:
                db.session.delete(sub)
            db.session.commit()
            log_audit("PUSH", "CLEANUP", f"{count} verwaiste Push-Abos von Spieler-ID {player_id} gelöscht.")
            push_logger.info(f"Auto-Cleanup: {count} Abo(s) von Spieler {player_id} gelöscht, da Client meldete 'Kein Abo'.")
            return jsonify({'status': 'deleted', 'message': f'{count} alte Abos bereinigt'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': str(e)})
            
    return jsonify({'status': 'none', 'message': 'Keine Aktion.'})

@app.route('/admin/delete-push-subscription/<int:sub_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def delete_push_subscription(sub_id):
    """Löscht ein spezifisches Push-Abonnement aus der Datenbank."""
    sub_record = PushSubscription.query.get_or_404(sub_id)
    
    try:
        p_id = sub_record.player_id
        db.session.delete(sub_record)
        db.session.commit()
        log_audit("PUSH", "DELETE", f"Push-Abo ID {sub_id} für Spieler-ID {p_id} manuell gelöscht.")
        # Check if request prefers JSON (e.g. from fetch)
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({'success': True, 'message': 'Push-Abonnement erfolgreich gelöscht.', 'removeElement': f'#push-sub-row-{sub_id}'})
        
        flash('Push-Abonnement erfolgreich gelöscht.', 'success')
        return redirect(url_for('admin'))
    except Exception as e:
        db.session.rollback()
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({'success': False, 'message': str(e)})
        flash(f'Fehler beim Löschen: {e}', 'danger')
        return redirect(url_for('admin'))
        push_logger.error(f"Fehler beim Löschen von Push-Abo {sub_id}: {e}")
        return jsonify({'success': False, 'message': 'Ein Fehler ist aufgetreten.'})


@app.route('/admin/delete-webauthn/<string:credential_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def delete_webauthn_credential_admin(credential_id):
    """Löscht eine Biometrie-Hinterlegung manuell durch den Admin."""
    credential = WebAuthnCredential.query.get_or_404(credential_id)
    user_name = credential.user.username
    
    try:
        db.session.delete(credential)
        db.session.commit()
        log_audit("WEBAUTHN", "ADMIN_DELETE", f"Biometrie-Credential {credential_id} für User {user_name} manuell gelöscht.")
        flash(f'Biometrie-Hinterlegung für {user_name} erfolgreich gelöscht.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen: {e}', 'danger')
        
    return redirect(url_for('admin'))

# --- CLI-Befehle ---
@app.cli.command('init-db')
def init_db_command(): db.create_all(); print('Alle Datenbank-Tabellen erstellt.')
@app.cli.command('create-admin')
def create_admin_command():
    username = input("Gib einen Benutzernamen für den Admin ein: "); password = input("Gib ein Passwort ein: ")
    if User.query.filter_by(username=username).first(): print(f"Benutzer '{username}' existiert bereits."); return
    admin = User(username=username, role='admin'); admin.set_password(password)
    db.session.add(admin); db.session.commit()
    print(f"Admin-Benutzer '{username}' erfolgreich erstellt.")

@app.cli.command('db-add-roles')
def db_add_roles_command():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('admin_user')]
        if 'role' not in columns:
            with db.engine.connect() as connection:
                connection.execute(text("ALTER TABLE admin_user ADD COLUMN role VARCHAR(80) DEFAULT 'viewer' NOT NULL"))
                connection.commit()
            print("Spalte 'role' zur Tabelle 'admin_user' erfolgreich hinzugefügt.")
        else:
            print("Spalte 'role' existiert bereits.")
    except Exception as e:
        print(f"Fehler bei der Migration: {e}")

@app.cli.command('db-add-image-path')
def db_add_image_path_command():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('player')]
        if 'image_path' not in columns:
            with db.engine.connect() as connection:
                connection.execute(text("ALTER TABLE player ADD COLUMN image_path VARCHAR(255)"))
                connection.commit()
            print("Spalte 'image_path' zur Tabelle 'player' erfolgreich hinzugefügt.")
        else:
            print("Spalte 'image_path' existiert bereits.")
    except Exception as e:
        print(f"Fehler bei der Migration: {e}")

@app.cli.command('set-admin-role')
@click.argument('username')
@click.argument('role')
def set_admin_role(username, role):
    """Setzt die Rolle eines existierenden Benutzers. z.B. flask set-admin-role max admin"""
    if role not in VALID_ROLES:
        print(f"Fehler: Ungültige Rolle '{role}'. Gültige Rollen sind: {', '.join(VALID_ROLES)}")
        return
    user = User.query.filter_by(username=username).first()
    if user:
        user.role = role
        db.session.commit()
        print(f"Rolle für '{username}' wurde auf '{role}' gesetzt.")
    else:
        print(f"Benutzer '{username}' nicht gefunden.")
        
@app.cli.command('send-debtor-reminders')
@click.option('--dry-run', is_flag=True, help="Zeigt nur an, wer eine Nachricht bekommen würde, ohne sie zu senden.")
def send_debtor_reminders_command(dry_run):
    """
    Findet alle Spieler mit Schulden >= 10€, prüft, ob heute ein Spieltag ist,
    und sendet ihnen eine Zahlungs-Erinnerung.
    """
    with app.app_context():
        # --- 1. Prüfen, ob heute Spieltag ist ---
        print("Starte Schuldner-Erinnerungen...")
        push_logger.info("Scheduler: Starte Schuldner-Erinnerungen-Check...")
        
        season_str = get_season_for_date(datetime.utcnow().date())
        fupa_data = get_latest_fupa_game_data(season_str)
        game_date_str = fupa_data.get('team2_date')
        
        if not game_date_str:
            print("Kein Spieldatum von Fupa gefunden. Breche ab.")
            push_logger.info("Scheduler: Kein Fupa-Spieldatum gefunden. Breche ab.")
            return

        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        today = datetime.utcnow().date()

        if game_date != today:
            print(f"Heute ({today}) ist kein Spieltag (nächstes Spiel: {game_date}). Breche ab.")
            push_logger.info(f"Scheduler: Heute ({today}) ist kein Spieltag. Nächstes Spiel: {game_date}. Breche ab.")
            return

        print(f"Heute ist Spieltag! Suche nach Schuldnern...")
        push_logger.info(f"Scheduler: Heute ist Spieltag! Suche nach Schuldnern...")

        # --- 2. Alle Schuldner über 10€ finden ---
        all_players = Player.query.all()
        debtors = [p for p in all_players if p.balance <= -10.0 and p.push_subscription_json]

        if not debtors:
            print("Keine Schuldner über 10€ mit aktivem Push-Abo gefunden.")
            push_logger.info("Scheduler: Keine passenden Schuldner gefunden.")
            return
            
        # --- 3. Base URL für App holen ---
        base_url = "/"

        # --- 4. Benachrichtigungen senden ---
        for player in debtors:
            schulden_betrag = player.balance * -1
            message_body = f"Bitte denke an deine {schulden_betrag:.2f} € Schulden. Du kannst heute am Spieltag bar zahlen oder direkt in der App per PayPal (Klick hier)."
            
            if dry_run:
                print(f"[Dry Run] Würde Nachricht an {player.name} senden: '{message_body}'")
                push_logger.info(f"[Dry Run] Würde Nachricht an {player.name} senden.")
            else:
                print(f"Sende Nachricht an {player.name}...")
                push_logger.info(f"Scheduler: Sende Erinnerung an {player.name}.")
                send_push_notification(
                    player_id=player.id,
                    title="💰 Zahlungs-Erinnerung",
                    body=message_body,
                    url=url_for('player_detail', player_id=player.id, _external=True)
                )
        
        print("Alle Erinnerungen verarbeitet.")
        push_logger.info("Scheduler: Alle Erinnerungen verarbeitet.")

if __name__ == '__main__':
    with app.app_context():

        db.create_all()
        
        # Initialen Admin anlegen, falls keiner existiert
        if not User.query.filter_by(username='admin').first():
            print("Erstelle Standard-Admin Account...")
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            
    # Port 5000 ist Standard, host='0.0.0.0' macht es im Netzwerk verfügbar
    app.run(host='0.0.0.0', port=5000, debug=True)

