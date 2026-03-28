# worker_scheduler.py
import os
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
from app import app, db, Player, KasseSetting, Transaction, get_deadline, send_push_notification, GERMAN_TZ, datetime, timedelta

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


def run_doubling_check():
    """Prüft auf offene Strafen und verdoppelt diese bei Verzug."""
    with app.app_context():
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger('doubling_job')
        logger.info("Starte Verdopplungs-Check...")

        today = datetime.utcnow().date()
        
        s1 = KasseSetting.query.filter_by(key='doubling_active_team1').first()
        active_t1 = s1.value == '1' if s1 else False
        
        s2 = KasseSetting.query.filter_by(key='doubling_active_team2').first()
        active_t2 = s2.value == '1' if s2 else False

        if not active_t1 and not active_t2:
            logger.info("Verdopplung ist für beide Teams deaktiviert.")
            return

        teams_map = []
        if active_t1: teams_map.append('team1')
        if active_t2: teams_map.append('team2')
        
        candidates = Transaction.query.filter(
            Transaction.amount < 0,
            Transaction.category == 'fine',
            Transaction.doubled_by_id == None,
            Transaction.team.in_(teams_map)
        ).all()
        
        doubled_count = 0
        
        for tx in candidates:
            amount_settled = tx.amount_settled if tx.amount_settled is not None else 0.0
            remaining = abs(tx.amount) - amount_settled
            if remaining < 0.01: continue
                
            age_days = (today - tx.date).days
            if age_days >= 15:
                amount_to_add = remaining
                new_desc = f"Verzugszuschlag zu '{tx.description}'"
                
                doubling_tx = Transaction(
                    player_id=tx.player_id, description=new_desc, amount=-amount_to_add,
                    category='fine', team=tx.team, created_by='system_doubler',
                    date=today, amount_settled=0.0
                )
                db.session.add(doubling_tx)
                db.session.flush()
                
                tx.doubled_by_id = doubling_tx.id
                doubled_count += 1
                logger.info(f"Strafen-Verdopplung: {tx.description} -> +{amount_to_add}")
                
                try:
                    from flask import url_for
                    url_to_open = url_for('player_detail', player_id=tx.player_id, _external=True)
                    send_push_notification(tx.player_id, "Strafe verdoppelt!", f"Verzug bei '{tx.description}'", url_to_open)
                except:
                    pass

        db.session.commit()
        logger.info(f"Check beendet. {doubled_count} Strafen verdoppelt.")


def run_fine_reminder():
    """
    Läuft jeden Freitag um 18:00 Uhr.
    Prüft alle aktiven Spieler auf offene Strafen (via oldest_unpaid_fine).
    Sendet Pushes.
    """
    with app.app_context():
        app.logger.info("Starte wöchentlichen Strafen-Reminder (Freitag 18:00)...")
        
        s1 = KasseSetting.query.filter_by(key='doubling_active_team1').first()
        s2 = KasseSetting.query.filter_by(key='doubling_active_team2').first()
        doubling_active_t1 = (s1 and s1.value == '1')
        doubling_active_t2 = (s2 and s2.value == '1')
        
        players = Player.query.filter_by(is_active=True).all()
        count = 0
        today_date = datetime.now(GERMAN_TZ).date()
        
        for p in players:
            fine = p.oldest_unpaid_fine
            if fine:
                msg_body = f"Offene Strafe: {fine.description}."
                
                is_doubling_on = False
                if fine.team == 'team1' and doubling_active_t1: is_doubling_on = True
                elif fine.team != 'team1' and doubling_active_t2: is_doubling_on = True
                
                if is_doubling_on and fine.doubled_by_id is None:
                    deadline = get_deadline(fine.date)
                    doubling_date = deadline + timedelta(days=1)
                    
                    if doubling_date <= today_date:
                        msg_body += " ⚠️ Verdopplung droht morgen!"
                    else:
                        msg_body += f" ⚠️ Verdopplung am {doubling_date.strftime('%d.%m.')}!"

                msg_body += " Bitte begleichen!"
                
                try:
                    from flask import url_for
                    url_to_open = url_for('player_detail', player_id=p.id, _external=True)
                    send_push_notification(p.id, "Zahlungserinnerung", msg_body, url_to_open)
                    count += 1
                except Exception as e:
                    app.logger.error(f"Fehler beim Senden des Reminders an {p.name}: {e}")
                    
        app.logger.info(f"Reminder beendet. {count} Benachrichtigungen versendet.")


def check_birthdays():
    """
    Läuft täglich um 09:00 Uhr.
    Prüft auf Geburtstage und informiert ALLE ANDEREN Spieler.
    """
    from app import User
    with app.app_context():
        try:
            today = datetime.now(GERMAN_TZ).date()
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
    scheduler.add_job(func=run_doubling_check, trigger=CronTrigger(day_of_week=5, hour=3, minute=0), id='doubling_check', name='Strafen-Verdopplung', replace_existing=True)
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
