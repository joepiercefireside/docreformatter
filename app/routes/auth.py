from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, current_user
from ..models.user import User, load_user
from ..utils.database import get_db_connection
import bcrypt
import secrets
from authlib.integrations.flask_client import OAuth

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
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
                return redirect(url_for('main.index'))
            flash('Invalid email or password', 'danger')
        except Exception as e:
            flash(f'Login failed: {str(e)}', 'danger')
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
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
            return redirect(url_for('main.index'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'danger')
    return render_template('register.html')

@auth_bp.route('/google_login')
def google_login():
    oauth = OAuth(current_app)
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    redirect_uri = url_for('auth.google_auth', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)

@auth_bp.route('/google_auth')
def google_auth():
    try:
        oauth = OAuth(current_app)
        token = oauth.google.authorize_access_token()
        if not token:
            raise ValueError("No token received from Google")
        nonce = session.pop('nonce', None)
        if not nonce:
            raise ValueError("Nonce not found in session")
        user_info = oauth.google.parse_id_token(token, nonce=nonce)
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
        return redirect(url_for('main.index'))
    except Exception as e:
        flash(f'Google login failed: {str(e)}', 'danger')
        return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.pop('selected_client', None)
    session.pop('selected_template', None)
    session.pop('template_prompt', None)
    session.pop('conversion_prompt', None)
    session.pop('converted_content', None)
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))