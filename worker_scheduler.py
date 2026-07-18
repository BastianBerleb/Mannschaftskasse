# worker_scheduler.py
import os
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
from app import app, db, Player, KasseSetting, Transaction, get_deadline, send_push_notification, GERMAN_TZ, datetime, timedelta, get_local_now

def send_debt_reminders():
    """
    Routine Schulden-Erinnerung (Sonntag 10:00 & Freitag 18:00)
    Sendet Push-Benachrichtigungen an alle Spieler mit 10€ oder mehr Schulden
    """
    try:
        with app.app_context():
            # Nur Spieler mit Schulden <= -10.00€ erfassen
            debtors = Player.query.filter(Player.balance <= -10.00).all()
            if not debtors:
                print("📅 Routine-Reminder: Keine Schuldner gefunden!")
                return
            
            reminder_count = 0
            for player in debtors:
                if player.subscriptions.count() > 0:
                    debt_amount = abs(player.balance)
                    # Manuell URL bauen, da kein voller Request-Context vorhanden
                    from flask import url_for
                    url_to_open = url_for('player_detail', player_id=player.id, _external=True)
                    
                    if debt_amount >= 20:
                        title = "🚨 Hohe Schulden - Dringend zahlen!"
                        body = f"Dein Schuldenstand beträgt {debt_amount:.2f}€. Bitte zahle zeitnah!"
                    elif debt_amount >= 15:
                        title = "⚠️ Schulden-Erinnerung"
                        body = f"Du hast {debt_amount:.2f}€ Schulden. Zeit zum Begleichen!"
                    else:
                        title = "💰 Freundliche Zahlungserinnerung"
                        body = f"Kleiner Reminder: Du hast {debt_amount:.2f}€ offen."
                    
                    send_push_notification(player.id, title, body, url_to_open)
                    reminder_count += 1
            
            print(f"📅 Routine-Reminder: {reminder_count} Erinnerungen versendet an {len(debtors)} Schuldner")
    except Exception as e:
        print(f"❌ Fehler beim Senden der Routine-Reminder: {e}")


def run_escalation_check():
    """
    Täglicher Check auf Schulden-Eskalation.
    Prüft ob ein Spieler den Threshold (z.B. -25€) erreicht hat und startet den Timer.
    Verteilt nach X Tagen Strafen und sendet Pushes an Spieler und Strafenmanager.
    """
    from app import User
    with app.app_context():
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger('escalation_job')
        logger.info("Starte Schulden-Eskalation-Check...")

        try:
            today = get_local_now().date()
            
            s1 = KasseSetting.query.filter_by(key='escalation_active_team1').first()
            active_t1 = s1.value == '1' if s1 else False
            s2 = KasseSetting.query.filter_by(key='escalation_active_team2').first()
            active_t2 = s2.value == '1' if s2 else False

            if not active_t1 and not active_t2:
                logger.info("Schulden-Eskalation ist für beide Teams deaktiviert.")
                return

            st = KasseSetting.query.filter_by(key='escalation_threshold').first()
            threshold = float(st.value) if st and st.value else 25.0
            st_days = KasseSetting.query.filter_by(key='escalation_days').first()
            days_limit = int(st_days.value) if st_days and st_days.value else 7
            st_pen = KasseSetting.query.filter_by(key='escalation_penalty').first()
            penalty = float(st_pen.value) if st_pen and st_pen.value else 5.0
            
            players = Player.query.filter_by(is_active=True).all()
            
            for player in players:
                # Check team setting
                if player.team1 and not active_t1 and not player.team2: continue
                if player.team2 and not active_t2 and not player.team1: continue
                if not player.team1 and not player.team2: continue

                target_team = 'team1' if player.team1 else 'team2'
                if player.team1 and player.team2:
                     target_team = 'team1' if active_t1 else 'team2'

                current_balance = player.balance
                
                # Check condition
                if current_balance <= -threshold:
                    if not player.escalation_start_date:
                        # Timer starten
                        player.escalation_start_date = today
                        db.session.commit()
                        
                        logger.info(f"Eskalations-Timer für {player.name} gestartet (Guthaben: {current_balance:.2f}€).")
                        from flask import url_for
                        try:
                            url_to_open = url_for('player_detail', player_id=player.id, _external=True)
                            send_push_notification(player.id, "⚠️ Schulden Warnung!", f"Dein Guthaben ({current_balance:.2f}€) ist zu niedrig. Bitte begleiche deine Schulden innerhalb von {days_limit} Tagen, sonst fallen {penalty:.2f}€ Strafgebühr an.", url_to_open)
                        except: pass
                        
                    else:
                        # Timer überprüfen
                        age_days = (today - player.escalation_start_date).days
                        if age_days >= days_limit:
                            # Strafe buchen
                            desc = f"Strafzuschlag: Schulden-Eskalation (> {days_limit} Tage)"
                            tx = Transaction(player_id=player.id, amount=-penalty, description=desc, date=today, category='fine', team=target_team, created_by='system_escalation')
                            db.session.add(tx)
                            
                            # Timer neustarten
                            player.escalation_start_date = today
                            db.session.commit()
                            
                            logger.info(f"Strafe von {penalty:.2f}€ für {player.name} gebucht.")
                            
                            # Push zu Spieler
                            from flask import url_for
                            try:
                                url_to_open = url_for('player_detail', player_id=player.id, _external=True)
                                send_push_notification(player.id, "❌ Strafe gebucht!", f"{penalty:.2f}€ Strafe wurden wegen zu hohen Schulden über mehrere Tage gebucht. Nächste Strafe in {days_limit} Tagen.", url_to_open)
                            except: pass
                            
                            # Push zu Managern
                            managers = []
                            manager_role = 'strafen_manager_1' if target_team == 'team1' else 'strafen_manager_2'
                            users = User.query.filter(User.role.in_(['admin', manager_role])).all()
                            for u in users:
                                if u.player_id and u.player_id != player.id:
                                    try:
                                        send_push_notification(u.player_id, "Schulden Eskalation", f"System hat {penalty:.2f}€ Strafe bei {player.name} ({target_team}) gebucht.", url_to_open)
                                    except: pass

                elif player.escalation_start_date:
                    # Schulden beglichen, Timer stoppen
                    player.escalation_start_date = None
                    db.session.commit()
                    logger.info(f"Eskalations-Timer für {player.name} beendet (Guthaben: {current_balance:.2f}€).")
                    
        except Exception as e:
            logger.error(f"Kritischer Fehler im Eskalations-Check: {e}")
            db.session.rollback()


def run_fine_reminder():
    """
    Läuft jeden Freitag um 18:00 Uhr.
    Prüft alle aktiven Spieler auf offene Strafen (via oldest_unpaid_fine).
    Sendet Pushes.
    """
    with app.app_context():
        app.logger.info("Starte wöchentlichen Strafen-Reminder (Freitag 18:00)...")
        
        try:
            players = Player.query.filter_by(is_active=True).all()
            count = 0
            
            for p in players:
                fine = p.oldest_unpaid_fine
                if fine:
                    msg_body = f"Offene Strafe: {fine.description}. Bitte begleichen!"
                    
                    try:
                        from flask import url_for
                        url_to_open = url_for('player_detail', player_id=p.id, _external=True)
                        send_push_notification(p.id, "Zahlungserinnerung", msg_body, url_to_open)
                        count += 1
                    except Exception as e:
                        app.logger.error(f"Fehler beim Senden des Reminders an {p.name}: {e}")
                        
            app.logger.info(f"Reminder beendet. {count} Benachrichtigungen versendet.")
        except Exception as e:
            app.logger.error(f"Fehler im Strafen-Reminder: {e}")


def check_birthdays():
    """
    Läuft täglich um 09:00 Uhr.
    Prüft auf Geburtstage und informiert ALLE ANDEREN Spieler.
    """
    from app import User
    with app.app_context():
        try:
            today = get_local_now().date()
            all_players = Player.query.filter_by(is_active=True).all()
            birthday_kids = []
            
            for p in all_players:
                if p.birthday and p.birthday.month == today.month and p.birthday.day == today.day:
                    birthday_kids.append(p)
            
            if not birthday_kids:
                print("📅 Birthday-Check: Keine Geburtstage heute.")
                return

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
            
            recipients = [
                p for p in all_players 
                if p.id not in birthday_ids 
                and user_roles.get(p.id) is not None 
                and user_roles.get(p.id) != 'player'
            ]
            
            count = 0
            from flask import url_for
            url_to_open = url_for('geburtstage', _external=True)
            
            for recipient in recipients:
                try:
                    send_push_notification(recipient.id, title, body, url_to_open)
                    count += 1
                except: pass
            
            for kid in birthday_kids:
                try:
                     send_push_notification(kid.id, "🎈 Alles Gute!", "Das Team wünscht dir einen tollen Geburtstag!", url_to_open)
                except: pass

            print(f"📅 Birthday-Check: {len(birthday_kids)} Geburtstag(e) gefunden. {count} Benachrichtigungen verschickt.")
        except Exception as e:
            print(f"❌ Fehler beim Birthday-Check: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone=GERMAN_TZ)
    
    # Jobs regruppieren
    scheduler.add_job(func=send_debt_reminders, trigger=CronTrigger(day_of_week=6, hour=10, minute=0), id='weekly_debt_reminders', name='Sonntägliche Schulden-Erinnerung', replace_existing=True)
    scheduler.add_job(func=send_debt_reminders, trigger=CronTrigger(day_of_week=4, hour=18, minute=0), id='friday_debt_reminders', name='Freitagliche Schulden-Erinnerung', replace_existing=True)
    scheduler.add_job(func=check_birthdays, trigger=CronTrigger(hour=9, minute=0), id='daily_birthday_check', name='Täglicher Geburtstags-Check', replace_existing=True)
    scheduler.add_job(func=run_escalation_check, trigger=CronTrigger(hour=4, minute=30), id='escalation_check', name='Schulden-Eskalation', replace_existing=True)
    scheduler.add_job(func=run_fine_reminder, trigger=CronTrigger(day_of_week=4, hour=18, minute=0), id='fine_reminder', name='Zahlungserinnerung', replace_existing=True)
    
    scheduler.start()
    print("🚀 Worker-Scheduler gestartet! Läuft im Hintergrund...")
    
    try:
        # Halt the script
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Worker-Scheduler beendet.")

if __name__ == '__main__':
    # URL For benötigt in Flask einen Request Context. Da wir hier in einem externen Skript sind,
    # faken wir den Server Namen, damit `url_for(..., _external=True)` klappt.
    # WICHTIG: Setze SERVER_NAME via Umgebungsvariable oder hier fest, falls bekannt.
    app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:5000') 
    app.config['APPLICATION_ROOT'] = '/'
    
    with app.app_context():
        start_scheduler()
