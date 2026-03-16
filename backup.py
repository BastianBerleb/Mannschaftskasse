# -*- coding: utf-8 -*-
import os
import shutil
import datetime
import logging
import sys

# Google API Bibliotheken
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google Authentifizierungs-Bibliotheken
from dotenv import load_dotenv
load_dotenv()

import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from importlib.metadata import version as get_lib_version

# --- Konfiguration ------------------------------------------------------------------
# WICHTIG: Die ID des Google Drive Ordners, in den die Backups hochgeladen werden sollen.
GOOGLE_DRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID') # Deine korrekte Ordner-ID

# Verzeichnisse & Einstellungen
SOURCE_DIR = os.path.dirname(__file__)
BACKUP_DIR = os.path.join(SOURCE_DIR, 'tmp_backups')
KEEP_LAST_N_BACKUPS = 30 # Anzahl der Backups, die auf Google Drive behalten werden

# Logging-Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# ------------------------------------------------------------------------------------


def create_google_drive_service():
    """Authentifiziert sich ueber den OAuth 2.0 Flow und erstellt den Google Drive Service."""
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = None
    
    CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')
    TOKEN_FILE = os.path.join(os.path.dirname(__file__), 'token.json')

    try:
        # Versuche, Anmeldedaten aus der token.json-Datei zu laden.
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
        # Wenn keine g�ltigen Anmeldedaten vorhanden sind, starte den Anmeldevorgang.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logging.info("Anmeldedaten sind abgelaufen. Erneuere Token...")
                creds.refresh(Request())
            else:
                logging.info("Keine gueltigen Anmeldedaten gefunden. Bitte autorisiere das Skript.")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                
                # --- HIER IST DIE �NDERUNG ---
                # Wir weisen die Funktion an, keinen Browser zu �ffnen.
                creds = flow.run_local_server(port=0, open_browser=False)
            
            # Speichere die neuen Anmeldedaten f�r zuk�nftige Ausf�hrungen.
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
            logging.info(f"Anmeldedaten erfolgreich in {TOKEN_FILE} gespeichert.")
                
        service = build('drive', 'v3', credentials=creds)
        logging.info("Google Drive Service erfolgreich erstellt.")
        return service

    except Exception as e:
        logging.error(f"Fehler bei der Authentifizierung mit Google Drive: {e}")
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            logging.warning(f"Potentiell beschaedigte {TOKEN_FILE} wurde entfernt. Bitte Skript erneut ausfuehren.")
        return None

def create_backup_archive():
    """Erstellt eine ZIP-Archivdatei des Projektverzeichnisses."""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    # Ein tempor�res Verzeichnis f�r die saubere Kopie
    temp_copy_dir = os.path.join(BACKUP_DIR, f'temp_copy_{timestamp}')
    archive_name_base = f'mannschaftskasse_backup_{timestamp}'
    archive_path_base = os.path.join(BACKUP_DIR, archive_name_base)

    try:
        # Definiert, welche Dateien und Ordner ignoriert werden sollen
        ignore_patterns = shutil.ignore_patterns(
            'tmp_backups*',       # Der Backup-Ordner selbst
            '__pycache__*',       # Python Cache-Dateien
            '*.pyc',              # Kompilierte Python-Dateien
            '.git*',              # Git-Verzeichnis
            'venv*',              # Virtuelle Umgebungen
            'venv_kaputt',        # Alte, kaputte Umgebungen
            '*.json',             # Alle JSON-Dateien (credentials.json, token.json)
            'backup_log.txt',     # Log-Dateien
            '.*'                  # Alle versteckten Dateien (z.B. .bash_history)
        )
        
        # SCHRITT 1: Erstelle eine saubere, tempor�re Kopie und ignoriere Dateien
        logging.info(f"Erstelle eine temporaere Kopie von '{SOURCE_DIR}' nach '{temp_copy_dir}'")
        shutil.copytree(SOURCE_DIR, temp_copy_dir, ignore=ignore_patterns)

        # SCHRITT 2: Erstelle das Archiv aus der sauberen Kopie
        logging.info(f"Erstelle Archiv aus '{temp_copy_dir}'")
        full_archive_path = shutil.make_archive(
            base_name=archive_path_base,
            format='zip',
            root_dir=temp_copy_dir  # Wichtig: Archiviert wird die tempor�re Kopie
        )
        
        logging.info(f"Archiv erfolgreich erstellt: {full_archive_path}")
        return full_archive_path

    except Exception as e:
        logging.error(f"Fehler beim Erstellen des Archivs: {e}")
        return None
        
    finally:
        # Aufr�umen: L�sche die tempor�re Kopie nach der Archivierung
        if os.path.exists(temp_copy_dir):
            shutil.rmtree(temp_copy_dir)
            logging.info(f"Temporaeres Kopie-Verzeichnis '{temp_copy_dir}' geloescht.")

def upload_to_drive(service, file_path):
    """Laedt eine Datei in den spezifizierten Google Drive Ordner hoch."""
    if not service or not file_path:
        return None
        
    file_name = os.path.basename(file_path)
    logging.info(f"Starte Upload von '{file_name}' nach Google Drive...")
    
    file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
    
    # MediaFileUpload sorgt f�r einen robusten, unterbrechbaren Upload.
    media = MediaFileUpload(file_path, mimetype='application/zip', resumable=True)
    
    try:
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logging.info(f"Upload Fortschritt: {int(status.progress() * 100)}%")

        logging.info(f"Upload erfolgreich! Datei-ID: {response.get('id')}")
        return response.get('id')
        
    except Exception as e:
        logging.error(f"Fehler beim Upload nach Google Drive: {e}")
        return None

def cleanup_old_backups(service):
    """Loescht alte Backups auf Google Drive, um Platz zu sparen."""
    if not service: return
    logging.info(f"Suche nach alten Backups. Behalte die letzten {KEEP_LAST_N_BACKUPS}.")
    try:
        query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed = false"
        results = service.files().list(q=query, pageSize=100, fields="files(id, name, createdTime)", orderBy="createdTime desc").execute()
        items = results.get('files', [])
        
        if len(items) > KEEP_LAST_N_BACKUPS:
            files_to_delete = items[KEEP_LAST_N_BACKUPS:]
            logging.info(f"{len(files_to_delete)} alte Backups gefunden, die geloescht werden.")
            for item in files_to_delete:
                service.files().delete(fileId=item['id']).execute()
                logging.info(f"Altes Backup '{item['name']}' geloescht.")
        else:
            logging.info("Keine alten Backups zum Loeschen gefunden.")
    except Exception as e:
        logging.error(f"Fehler beim Aufraeumen alter Backups: {e}")

def main():
    """Hauptfunktion, die den gesamten Backup-Prozess steuert."""
    
    # --- START: DIAGNOSE-BLOCK ---
    try:
        py_version = sys.version.replace('\n', ' ')
        py_executable = sys.executable
        
        logging.info("------------------- System-Diagnose -------------------")
        logging.info(f"Python Version: {py_version}")
        logging.info(f"Python Pfad: {py_executable}")
        
        # �berpr�fe die Versionen der kritischen Bibliotheken
        for lib in ['google-api-python-client', 'google-auth-oauthlib']:
            logging.info(f"{lib} Version: {get_lib_version(lib)}")
            
        logging.info("-------------------------------------------------------")
    except Exception as e:
        logging.error(f"Fehler bei der Diagnose: {e}")
    # --- ENDE: DIAGNOSE-BLOCK ---

    logging.info("===== Starte Backup-Prozess =====")
    
    # 1. Lokales ZIP-Archiv erstellen
    archive_path = create_backup_archive()
    if not archive_path:
        logging.error("Backup-Prozess abgebrochen, da Archiv nicht erstellt werden konnte.")
        return
        
    # 2. Mit Google Drive verbinden
    drive_service = create_google_drive_service()
    if not drive_service:
        logging.error("Backup-Prozess abgebrochen, da keine Verbindung zu Google Drive hergestellt werden konnte.")
        if os.path.exists(archive_path): os.remove(archive_path)
        return
        
    try:
        # 3. Archiv hochladen
        upload_to_drive(drive_service, archive_path)
        # 4. Alte Backups auf Drive aufr�umen
        cleanup_old_backups(drive_service)
    finally:
        # 5. Lokales Archiv nach dem Upload l�schen
        if os.path.exists(archive_path):
            os.remove(archive_path)
            logging.info(f"Lokale temporaere Datei '{os.path.basename(archive_path)}' geloescht.")
        
    logging.info("===== Backup-Prozess erfolgreich beendet =====")

if __name__ == '__main__':
    main()

