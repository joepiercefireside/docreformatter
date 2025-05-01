from flask import request, render_template, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
import psycopg2
import bcrypt
import secrets
from database import get_db_connection

# User model
class User(UserMixin):
    def __init__(self, id, email, google_id=None):
        self.id = id
        self.email = email
        self.google_id = google_id

def setup_auth(app):
    # Flask-Login setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    # OAuth setup
    oauth = OAuth(app)
    google = oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    @login_manager.user_loader
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
            print(f"Error loading user: {str(e)}")
            return None

    # Authentication routes
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT id, email, password_hash FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
                cur.close()
                conn.close()
                if user and bcrypt.checkpw(password.encode('utf-8'), user[2].encode('utf-8')):
                    login_user(User(user[0], user[1]))
                    return redirect(url_for('index'))
                flash('Invalid email or password', 'danger')
            except Exception as e:
                print(f"Error during login: {str(e)}")
                flash('Login failed', 'danger')
        return render_template('login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cur.fetchone():
                    flash('Email already registered', 'danger')
                    cur.close()
                    conn.close()
                    return render_template('register.html')
                password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id", (email, password_hash))
                user_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
                login_user(User(user_id, email))
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Error during registration: {str(e)}")
                flash('Registration failed', 'danger')
        return render_template('register.html')

    @app.route('/google_login')
    def google_login():
        nonce = secrets.token_urlsafe(16)
        session['nonce'] = nonce
        redirect_uri = url_for('google_auth', _external=True)
        return google.authorize_redirect(redirect_uri, nonce=nonce)

    @app.route('/google_auth')
    def google_auth():
        try:
            token = google.authorize_access_token()
            if not token:
                raise ValueError("No token received from Google")
            nonce = session.pop('nonce', None)
            if not nonce:
                raise ValueError("Nonce not found in session")
            user_info = google.parse_id_token(token, nonce=nonce)
            if not user_info:
                raise ValueError("Failed to parse user info from token")
            google_id = user_info.get('sub')
            email = user_info.get('email')
            if not google_id or not email:
                raise ValueError(f"Missing user info: google_id={google_id}, email={email}")
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, email FROM users WHERE google_id = %s OR email = %s", (google_id, email))
            user = cur.fetchone()
            if user:
                login_user(User(user[0], user[1], google_id))
            else:
                cur.execute("INSERT INTO users (email, google_id) VALUES (%s, %s) RETURNING id", (email, google_id))
                user_id = cur.fetchone()[0]
                conn.commit()
                login_user(User(user_id, email, google_id))
            cur.close()
            conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Error during Google auth: {str(e)}")
            import traceback
            print(traceback.format_exc())
            flash(f'Google login failed: {str(e)}', 'danger')
            return redirect(url_for('login'))

    @app.route('/logout')
    @login_required
    def logout():
        session.pop('selected_client', None)
        session.pop('selected_prompt', None)
        logout_user()
        flash('You have been logged out.', 'success')
        return redirect(url_for('login'))