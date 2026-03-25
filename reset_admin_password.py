#!/usr/bin/env python3
"""
Skript zum Zurücksetzen des Admin-Passworts der Mannschaftskasse-App

Verwendung:
python reset_admin_password.py

Das Skript zeigt alle existierenden Admin-Benutzer an und ermöglicht es,
das Passwort für einen bestehenden Benutzer zu ändern oder einen neuen
Admin-Benutzer zu erstellen.
"""

import os
import sys
import getpass
from werkzeug.security import generate_password_hash

# Flask-App Setup
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# App konfigurieren
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'mannschaftskasse.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'temp-key-for-password-reset'

db = SQLAlchemy(app)

# AdminUser Modell (kopiert aus app.py)
class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(80), nullable=False, default='viewer')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

def show_existing_users():
    """Zeigt alle existierenden Admin-Benutzer an"""
    users = AdminUser.query.all()
    if not users:
        print("❌ Keine Admin-Benutzer in der Datenbank gefunden!")
        return None
    
    print("\n📋 Existierende Admin-Benutzer:")
    print("-" * 40)
    for i, user in enumerate(users, 1):
        print(f"{i}. Benutzername: {user.username}")
        print(f"   Rolle: {user.role}")
        print(f"   ID: {user.id}")
        print()
    
    return users

def reset_password_for_user(user):
    """Setzt das Passwort für einen bestehenden Benutzer zurück"""
    print(f"\n🔄 Passwort zurücksetzen für Benutzer: {user.username}")
    
    while True:
        new_password = getpass.getpass("Neues Passwort eingeben: ")
        if len(new_password) < 6:
            print("❌ Passwort muss mindestens 6 Zeichen lang sein!")
            continue
        
        confirm_password = getpass.getpass("Passwort bestätigen: ")
        if new_password != confirm_password:
            print("❌ Passwörter stimmen nicht überein!")
            continue
        
        break
    
    # Passwort setzen
    user.set_password(new_password)
    db.session.commit()
    
    print(f"✅ Passwort für Benutzer '{user.username}' erfolgreich geändert!")

def create_new_admin():
    """Erstellt einen neuen Admin-Benutzer"""
    print("\n➕ Neuen Admin-Benutzer erstellen")
    
    while True:
        username = input("Benutzername: ").strip()
        if not username:
            print("❌ Benutzername darf nicht leer sein!")
            continue
        
        # Prüfen ob Benutzername bereits existiert
        existing_user = AdminUser.query.filter_by(username=username).first()
        if existing_user:
            print(f"❌ Benutzername '{username}' existiert bereits!")
            continue
        
        break
    
    while True:
        new_password = getpass.getpass("Passwort eingeben: ")
        if len(new_password) < 6:
            print("❌ Passwort muss mindestens 6 Zeichen lang sein!")
            continue
        
        confirm_password = getpass.getpass("Passwort bestätigen: ")
        if new_password != confirm_password:
            print("❌ Passwörter stimmen nicht überein!")
            continue
        
        break
    
    # Rolle auswählen
    print("\nRolle auswählen:")
    print("1. admin (Vollzugriff)")
    print("2. strafen_manager (Kann Strafen verwalten)")
    print("3. viewer (Vereinsverantwortlicher - Nur Lesezugriff)")
    
    while True:
        choice = input("Rolle wählen (1-3): ").strip()
        if choice == "1":
            role = "admin"
            break
        elif choice == "2":
            role = "strafen_manager"
            break
        elif choice == "3":
            role = "viewer"
            break
        else:
            print("❌ Ungültige Auswahl!")
    
    # Neuen Benutzer erstellen
    new_user = AdminUser(username=username, role=role)
    new_user.set_password(new_password)
    
    db.session.add(new_user)
    db.session.commit()
    
    print(f"✅ Neuer Admin-Benutzer '{username}' mit Rolle '{role}' erfolgreich erstellt!")

def main():
    print("🔐 Mannschaftskasse - Admin Passwort Reset Tool")
    print("=" * 50)
    
    # App-Kontext erstellen
    with app.app_context():
        # Datenbank initialisieren falls nötig
        db.create_all()
        
        # Existierende Benutzer anzeigen
        users = show_existing_users()
        
        if users:
            print("\nWas möchten Sie tun?")
            print("1. Passwort für existierenden Benutzer zurücksetzen")
            print("2. Neuen Admin-Benutzer erstellen")
            print("3. Beenden")
            
            while True:
                choice = input("\nWählen Sie eine Option (1-3): ").strip()
                
                if choice == "1":
                    # Benutzer auswählen
                    while True:
                        try:
                            user_choice = int(input(f"\nWelchen Benutzer möchten Sie bearbeiten? (1-{len(users)}): "))
                            if 1 <= user_choice <= len(users):
                                selected_user = users[user_choice - 1]
                                reset_password_for_user(selected_user)
                                break
                            else:
                                print("❌ Ungültige Auswahl!")
                        except ValueError:
                            print("❌ Bitte geben Sie eine Nummer ein!")
                    break
                
                elif choice == "2":
                    create_new_admin()
                    break
                
                elif choice == "3":
                    print("👋 Auf Wiedersehen!")
                    sys.exit(0)
                
                else:
                    print("❌ Ungültige Auswahl!")
        
        else:
            # Keine Benutzer vorhanden - ersten Admin erstellen
            print("\n🚀 Es wurden keine Admin-Benutzer gefunden.")
            print("Möchten Sie den ersten Admin-Benutzer erstellen?")
            
            while True:
                create_first = input("Ersten Admin erstellen? (j/n): ").strip().lower()
                if create_first in ['j', 'ja', 'y', 'yes']:
                    create_new_admin()
                    break
                elif create_first in ['n', 'nein', 'no']:
                    print("👋 Auf Wiedersehen!")
                    sys.exit(0)
                else:
                    print("❌ Bitte antworten Sie mit 'j' oder 'n'!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Abgebrochen!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        sys.exit(1)
