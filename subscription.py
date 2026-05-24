import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "subscriptions.db"

class SubscriptionManager:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                subscription_status TEXT,
                subscription_date TIMESTAMP,
                expiry_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    
    def add_user(self, user_id, username, subscription_days=30):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.now()
        expiry = now + timedelta(days=subscription_days)
        try:
            cursor.execute('INSERT OR REPLACE INTO users (user_id, username, subscription_status, subscription_date, expiry_date) VALUES (?, ?, ?, ?, ?)', (user_id, username, 'active', now, expiry))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def remove_user(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE users SET subscription_status = ? WHERE user_id = ?', ('inactive', user_id))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def is_user_active(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT subscription_status, expiry_date FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                return False
            status, expiry_date = result
            if status != 'active':
                return False
            if expiry_date:
                expiry = datetime.fromisoformat(expiry_date)
                if datetime.now() > expiry:
                    cursor.execute('UPDATE users SET subscription_status = ? WHERE user_id = ?', ('expired', user_id))
                    conn.commit()
                    return False
            return True
        except:
            return False
        finally:
            conn.close()
    
    def get_all_users(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT user_id, username, subscription_status, expiry_date FROM users ORDER BY created_at DESC')
            return cursor.fetchall()
        except:
            return []
        finally:
            conn.close()
    
    def renew_subscription(self, user_id, days=30):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.now()
        expiry = now + timedelta(days=days)
        try:
            cursor.execute('UPDATE users SET subscription_status = ?, subscription_date = ?, expiry_date = ? WHERE user_id = ?', ('active', now, expiry, user_id))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()

subscription_manager = SubscriptionManager()
