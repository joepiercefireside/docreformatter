from flask_login import UserMixin
from ..utils.database import get_db_connection

class User(UserMixin):
    def __init__(self, id, email, google_id=None):
        self.id = id
        self.email = email
        self.google_id = google_id

def load_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, email, google_id FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            return User(user[0], user[1], user[2])
        return None
    except Exception as e:
        print(f"Error loading user: {str(e)}")  # Temporary logging
        return None