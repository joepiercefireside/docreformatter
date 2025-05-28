from flask import Flask, request, send_file, render_template, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import requests
import json
import os
import psycopg2
from psycopg2.extras import Json
from werkzeug.utils import secure_filename
import bcrypt
from authlib.integrations.flask_client import OAuth
import secrets
import logging

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Database setup
DATABASE_URL = os.environ.get('DATABASE_URL')
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255),
                google_id VARCHAR(255) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                client_id VARCHAR(50) NOT NULL,
                prompt JSONB,
                prompt_name VARCHAR(255),
                template BYTEA,
                template_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT settings_unique_user_client_prompt_template UNIQUE (user_id, client_id, prompt_name, template_name)
            );
            CREATE INDEX IF NOT EXISTS idx_client_id ON settings(client_id);
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Initialized database schema")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise

with app.app_context():
    init_db()

# User model
class User(UserMixin):
    def __init__(self, id, email, google_id=None):
        self.id = id
        self.email = email
        self.google_id = google_id

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
        logger.error(f"Error loading user: {str(e)}")
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
            logger.error(f"Error during login: {str(e)}")
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
            logger.error(f"Error during registration: {str(e)}")
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
        logger.error(f"Error during Google auth: {str(e)}")
        flash(f'Google login failed: {str(e)}', 'danger')
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    session.pop('selected_client', None)
    session.pop('selected_prompt', None)
    session.pop('selected_template', None)
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# Client creation route
@app.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    clients = get_clients(current_user.id)
    selected_client = request.args.get('selected_client', '')
    prompts = []
    templates = []

    if selected_client:
        conn = get_db_connection()
        cur = conn.cursor()
        # Load prompts
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = %s AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id, selected_client)
        )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
        # Load templates
        cur.execute(
            "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND client_id = %s AND template IS NOT NULL",
            (current_user.id, selected_client)
        )
        templates = [{'template_name': row[0], 'prompt_name': row[1]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Loaded prompts for client {selected_client}: {prompts}")
        logger.info(f"Loaded templates for client {selected_client}: {templates}")

    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '').strip()

        if action == 'create':
            if not client_id:
                flash('Client ID cannot be empty', 'danger')
                return redirect(url_for('create_client'))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO settings (user_id, client_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (current_user.id, client_id)
                )
                conn.commit()
                cur.close()
                conn.close()
                flash(f'Client {client_id} created successfully', 'success')
                return redirect(url_for('create_client', selected_client=client_id))
            except Exception as e:
                logger.error(f"Error creating client: {str(e)}")
                flash(f'Failed to create client: {str(e)}', 'danger')
                return redirect(url_for('create_client'))

    return render_template('create_client.html', clients=clients, selected_client=selected_client, prompts=prompts, templates=templates)

# Prompt creation/editing route
@app.route('/create_prompt', methods=['GET', 'POST'])
@login_required
def create_prompt():
    clients = get_clients(current_user.id)
    selected_client = request.args.get('client_id', '')
    edit_prompt = request.args.get('edit_prompt', '')
    prompts = []
    
    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '').strip()
        prompt_name = request.form.get('prompt_name', '').strip()
        prompt_content = request.form.get('prompt_content', '').strip()
        original_prompt_name = request.form.get('original_prompt_name', prompt_name).strip()
        
        if action == 'create':
            if not prompt_name:
                flash('Prompt name cannot be empty', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
            if not prompt_content:
                flash('Prompt content cannot be empty', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s AND template_name IS NULL",
                    (current_user.id, client_id, prompt_name)
                )
                if cur.fetchone():
                    flash(f'Prompt "{prompt_name}" already exists for this client', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('create_prompt', client_id=client_id))
                save_prompt(prompt_content, client_id, current_user.id, prompt_name)
                flash(f'Prompt "{prompt_name}" created successfully', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('create_prompt', client_id=client_id))
            except Exception as e:
                logger.error(f"Error creating prompt: {str(e)}")
                flash(f'Failed to create prompt: {str(e)}', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
        
        elif action == 'update':
            if not prompt_name:
                flash('Prompt name cannot be empty', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
            if not prompt_content:
                flash('Prompt content cannot be empty', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                if prompt_name != original_prompt_name:
                    cur.execute(
                        "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s AND template_name IS NULL",
                        (current_user.id, client_id, prompt_name)
                    )
                    if cur.fetchone():
                        flash(f'Prompt "{prompt_name}" already exists for this client', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('create_prompt', client_id=client_id))
                cur.execute(
                    "UPDATE settings SET prompt = %s, prompt_name = %s WHERE user_id = %s AND client_id = %s AND prompt_name = %s AND template_name IS NULL",
                    (Json({'prompt': prompt_content}), prompt_name, current_user.id, client_id, original_prompt_name)
                )
                if cur.rowcount == 0:
                    flash(f'Prompt "{original_prompt_name}" not found for update', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('create_prompt', client_id=client_id))
                conn.commit()
                cur.close()
                conn.close()
                flash(f'Prompt "{prompt_name}" updated successfully', 'success')
                return redirect(url_for('create_prompt', client_id=client_id))
            except Exception as e:
                logger.error(f"Error updating prompt: {str(e)}")
                flash(f'Failed to update prompt: {str(e)}', 'danger')
                return redirect(url_for('create_prompt', client_id=client_id))
    
    # Load prompts for selected client or global
    conn = get_db_connection()
    cur = conn.cursor()
    if selected_client:
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id, selected_client)
        )
    else:
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = '' AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id,)
        )
    prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
    cur.close()
    conn.close()
    logger.info(f"Prompts for client {selected_client or 'global'}: {prompts}")
    
    return render_template('create_prompt.html', clients=clients, selected_client=selected_client, prompts=prompts, selected_prompt=edit_prompt)

# Template creation/editing route
@app.route('/create_template', methods=['GET', 'POST'])
@login_required
def create_template():
    clients = get_clients(current_user.id)
    selected_client = request.args.get('client_id', '')
    edit_template = request.args.get('edit_template', '')
    templates = []
    prompts = []
    
    # Load prompts for selected client or global
    conn = get_db_connection()
    cur = conn.cursor()
    if selected_client:
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id, selected_client)
        )
    else:
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = '' AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id,)
        )
    prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
    
    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '').strip()
        template_name = request.form.get('template_name', '').strip()
        prompt_name = request.form.get('prompt_name', '').strip()
        prompt_name_new = request.form.get('prompt_name_new', '').strip()
        prompt_content = request.form.get('prompt_content', '').strip()
        template_file = request.files.get('template_file')
        original_template_name = request.form.get('original_template_name', template_name).strip()
        
        # Use new prompt name if provided
        if prompt_name_new and prompt_content:
            prompt_name = prompt_name_new
        
        if action == 'create':
            if not template_name:
                flash('Template name cannot be empty', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
            if not template_file or not template_file.filename.endswith('.docx'):
                flash('Valid .docx template file required', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
            if not prompt_name:
                flash('Please select an existing prompt or provide a new one', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # Check if template name exists
                cur.execute(
                    "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND template_name = %s",
                    (current_user.id, client_id, template_name)
                )
                if cur.fetchone():
                    flash(f'Template "{template_name}" already exists for this client', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('create_template', client_id=client_id))
                # Check if prompt name exists if new
                if prompt_name_new:
                    cur.execute(
                        "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s AND template_name IS NULL",
                        (current_user.id, client_id, prompt_name)
                    )
                    if cur.fetchone():
                        flash(f'Prompt "{prompt_name}" already exists for this client', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('create_template', client_id=client_id))
                    save_prompt(prompt_content, client_id, current_user.id, prompt_name)
                # Fetch existing prompt_content for selected prompt
                prompt_json = None
                if prompt_name and not prompt_name_new:
                    cur.execute(
                        "SELECT prompt FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt_name = %s AND prompt IS NOT NULL AND template_name IS NULL LIMIT 1",
                        (current_user.id, client_id, prompt_name)
                    )
                    result = cur.fetchone()
                    if result:
                        prompt_json = result[0]
                    else:
                        flash(f'Prompt "{prompt_name}" not found', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('create_template', client_id=client_id))
                # Save template
                file_data = template_file.read()
                cur.execute(
                    "INSERT INTO settings (user_id, client_id, prompt, prompt_name, template, template_name) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (current_user.id, client_id, Json(prompt_json) if prompt_json else None, prompt_name, file_data, template_name)
                )
                conn.commit()
                flash(f'Template "{template_name}" created successfully', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('create_template', client_id=client_id))
            except Exception as e:
                logger.error(f"Error creating template: {str(e)}")
                flash(f'Failed to create template: {str(e)}', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
        
        elif action == 'update':
            if not template_name:
                flash('Template name cannot be empty', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
            if not prompt_name:
                flash('Please select an existing prompt or provide a new one', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # Check if new template_name conflicts
                if template_name != original_template_name:
                    cur.execute(
                        "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND template_name = %s",
                        (current_user.id, client_id, template_name)
                    )
                    if cur.fetchone():
                        flash(f'Template "{template_name}" already exists for this client', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('create_template', client_id=client_id))
                # Check if new prompt_name conflicts
                if prompt_name_new:
                    cur.execute(
                        "SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s AND template_name IS NULL",
                        (current_user.id, client_id, prompt_name)
                    )
                    if cur.fetchone():
                        flash(f'Prompt "{prompt_name}" already exists for this client', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('create_template', client_id=client_id))
                    save_prompt(prompt_content, client_id, current_user.id, prompt_name)
                # Fetch existing prompt_content for selected prompt
                prompt_json = None
                if prompt_name and not prompt_name_new:
                    cur.execute(
                        "SELECT prompt FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt_name = %s AND prompt IS NOT NULL AND template_name IS NULL LIMIT 1",
                        (current_user.id, client_id, prompt_name)
                    )
                    result = cur.fetchone()
                    if result:
                        prompt_json = result[0]
                # Update template
                if template_file and template_file.filename.endswith('.docx'):
                    cur.execute(
                        "UPDATE settings SET template = %s, prompt = %s, prompt_name = %s, template_name = %s "
                        "WHERE user_id = %s AND client_id = %s AND template_name = %s",
                        (template_file.read(), Json(prompt_json) if prompt_json else None, prompt_name, template_name, current_user.id, client_id, original_template_name)
                    )
                else:
                    cur.execute(
                        "UPDATE settings SET prompt = %s, prompt_name = %s, template_name = %s "
                        "WHERE user_id = %s AND client_id = %s AND template_name = %s",
                        (Json(prompt_json) if prompt_json else None, prompt_name, template_name, current_user.id, client_id, original_template_name)
                    )
                if cur.rowcount == 0:
                    flash(f'Template "{original_template_name}" not found for update', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('create_template', client_id=client_id))
                conn.commit()
                cur.close()
                conn.close()
                flash(f'Template "{template_name}" updated successfully', 'success')
                return redirect(url_for('create_template', client_id=client_id))
            except Exception as e:
                logger.error(f"Error updating template: {str(e)}")
                flash(f'Failed to update template: {str(e)}', 'danger')
                return redirect(url_for('create_template', client_id=client_id))
    
    # Load templates for selected client or global
    conn = get_db_connection()
    cur = conn.cursor()
    if selected_client:
        cur.execute(
            "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template IS NOT NULL",
            (current_user.id, selected_client)
        )
    else:
        cur.execute(
            "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND client_id = '' AND template IS NOT NULL",
            (current_user.id,)
        )
    templates = [{'template_name': row[0], 'prompt_name': row[1]} for row in cur.fetchall()]
    cur.close()
    conn.close()
    logger.info(f"Templates for client {selected_client or 'global'}: {templates}")
    
    return render_template('create_template.html', clients=clients, selected_client=selected_client, templates=templates, prompts=prompts, selected_template=edit_template)

# Template deletion route
@app.route('/delete_template', methods=['POST'])
@login_required
def delete_template():
    try:
        client_id = request.form.get('client_id', '').strip()
        template_name = request.form.get('template_name').strip()
        if not template_name:
            return jsonify({'success': False, 'error': 'Template name is required'}), 400
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM settings WHERE user_id = %s AND client_id = %s AND template_name = %s AND template IS NOT NULL",
            (current_user.id, client_id, template_name)
        )
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Deleted template '{template_name}' for client {client_id or 'global'}, user {current_user.id}")
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error deleting template: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Prompt deletion route
@app.route('/delete_prompt', methods=['POST'])
@login_required
def delete_prompt():
    try:
        client_id = request.form.get('client_id', '').strip()
        prompt_name = request.form.get('prompt_name').strip()
        if not prompt_name:
            return jsonify({'success': False, 'error': 'Prompt name is required'}), 400
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s "
            "AND prompt IS NOT NULL AND template_name IS NULL AND template IS NULL",
            (current_user.id, client_id, prompt_name)
        )
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Prompt not found'}), 404
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Deleted prompt '{prompt_name}' for client {client_id or 'global'}, user {current_user.id}")
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error deleting prompt: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Client deletion route
@app.route('/delete_client', methods=['POST'])
@login_required
def delete_client():
    try:
        client_id = request.form.get('client_id').strip()
        if not client_id:
            return jsonify({'success': False, 'error': 'Client ID is required'}), 400
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM settings WHERE user_id = %s AND client_id = %s",
            (current_user.id, client_id)
        )
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Client not found'}), 404
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Deleted client '{client_id}' for user {current_user.id}")
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error deleting client: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Prompt management routes
@app.route('/load_prompts', methods=['POST'])
@login_required
def load_prompts():
    try:
        client_id = request.form.get('client_id', '')
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id:
            cur.execute(
                "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt IS NOT NULL AND template_name IS NULL",
                (current_user.id, client_id)
            )
        else:
            cur.execute(
                "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = '' AND prompt IS NOT NULL AND template_name IS NULL",
                (current_user.id,)
            )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Loaded prompts for client {client_id or 'global'}: {prompts}")
        return jsonify({'prompts': prompts}), 200
    except Exception as e:
        logger.error(f"Error loading prompts: {str(e)}")
        return jsonify({'error': 'Failed to load prompts'}), 500

@app.route('/load_templates', methods=['POST'])
@login_required
def load_templates():
    try:
        client_id = request.form.get('client_id', '')
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id:
            cur.execute(
                "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template IS NOT NULL",
                (current_user.id, client_id)
            )
        else:
            cur.execute(
                "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND client_id = '' AND template IS NOT NULL",
                (current_user.id,)
            )
        templates = [{'template_name': row[0], 'prompt_name': row[1]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Loaded templates for client {client_id or 'global'}: {templates}")
        return jsonify({'templates': templates}), 200
    except Exception as e:
        logger.error(f"Error loading templates: {str(e)}")
        return jsonify({'error': 'Failed to load templates'}), 500

@app.route('/load_client', methods=['POST'])
@login_required
def load_client():
    try:
        data = request.form
        client_id = data.get('client_id', '')
        template_name = data.get('template_name')
        prompt_name = data.get('prompt_name')
        if template_name:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content, prompt_name, template IS NOT NULL AS has_file "
                "FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template_name = %s LIMIT 1",
                (current_user.id, client_id, template_name)
            )
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                prompt = result[0] or ''
                prompt_name = result[1] or 'Custom'
                has_file = result[2]
                return jsonify({'prompt': prompt, 'prompt_name': prompt_name, 'has_file': has_file}), 200
            return jsonify({'prompt': '', 'prompt_name': 'Custom', 'has_file': False}), 404
        elif prompt_name and prompt_name != 'Custom':
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings "
                "WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt_name = %s AND prompt IS NOT NULL AND template_name IS NULL "
                "ORDER BY client_id DESC LIMIT 1",
                (current_user.id, client_id, prompt_name)
            )
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                return jsonify({'prompt': result[0] or '', 'prompt_name': prompt_name, 'has_file': False}), 200
            return jsonify({'prompt': '', 'prompt_name': 'Custom', 'has_file': False}), 404
        return jsonify({'prompt': '', 'prompt_name': 'Custom', 'has_file': False}), 200
    except Exception as e:
        logger.error(f"Error loading client: {str(e)}")
        return jsonify({'error': 'Failed to load client'}), 500

# Main page route
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    clients = get_clients(current_user.id)
    selected_client = session.get('selected_client')
    selected_template = session.get('selected_template')
    selected_prompt = session.get('selected_prompt', 'Custom')
    prompt_content = ""
    templates = []
    prompts = []
    has_template_file = False

    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '')

        if action == 'select_client':
            session['selected_client'] = client_id if client_id in clients or client_id == '' else None
            session.pop('selected_template', None)
            session.pop('selected_prompt', None)
            selected_client = client_id if client_id in clients or client_id == '' else None
            selected_template = None
            selected_prompt = 'Custom'
            if client_id:
                flash(f'Selected client: {client_id}', 'success')

        elif action == 'select_template':
            template_name = request.form.get('template_name')
            if template_name:
                session['selected_template'] = template_name
                selected_template = template_name
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT prompt->'prompt' AS prompt_content, prompt_name, template IS NOT NULL AS has_file "
                    "FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template_name = %s LIMIT 1",
                    (current_user.id, selected_client or '', template_name)
                )
                result = cur.fetchone()
                cur.close()
                conn.close()
                if result:
                    prompt_content = result[0] or ''
                    selected_prompt = result[1] or 'Custom'
                    has_template_file = result[2]
                    session['selected_prompt'] = selected_prompt
                    flash(f'Selected template: {template_name}', 'success')
                else:
                    selected_template = None
                    selected_prompt = 'Custom'
                    prompt_content = ''
                    session.pop('selected_template', None)
                    session.pop('selected_prompt', None)
                    flash(f'Template {template_name} not found', 'danger')
            else:
                session.pop('selected_template', None)
                session.pop('selected_prompt', None)
                selected_template = None
                selected_prompt = 'Custom'
                prompt_content = ""

        elif action == 'upload_document':
            document_file = request.files.get('document_file')
            template_name = request.form.get('template_name')
            prompt_name = request.form.get('prompt_name', 'Custom')
            custom_prompt = request.form.get('custom_prompt', '').strip()
            template_file = request.files.get('template_file')

            if not document_file or not document_file.filename.endswith('.docx'):
                flash('Valid .docx document required', 'danger')
                return redirect(url_for('index'))

            if prompt_name == 'Custom' and not custom_prompt:
                flash('Please enter a custom prompt or select an existing one', 'danger')
                return redirect(url_for('index'))

            filename = secure_filename(document_file.filename)
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"reformatted_{filename}")
            document_file.save(input_path)
            content = extract_content_from_docx(input_path)

            # Handle prompt
            ai_prompt = custom_prompt if custom_prompt else load_prompt_for_template(selected_client or '', current_user.id, template_name) if template_name else load_prompt(selected_client or '', current_user.id, prompt_name) if prompt_name != 'Custom' else DEFAULT_AI_PROMPT

            # Handle template
            temp_template_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_template.docx')
            template_used = False
            if template_file and template_file.filename.endswith('.docx'):
                template_file.save(temp_template_path)
                template_used = True
            elif template_name:
                template_used = load_template(temp_template_path, selected_client or '', current_user.id, template_name)

            sections = call_ai_api(content, selected_client, current_user.id, prompt_name, custom_prompt=ai_prompt)
            if "error" in sections:
                flash(f"AI processing failed: {sections['error']}", 'danger')
                os.remove(input_path)
                if template_used and os.path.exists(temp_template_path):
                    os.remove(temp_template_path)
                return redirect(url_for('index'))
            sections["references"] = content["references"]
            create_reformatted_docx(sections, output_path, client_id=selected_client, user_id=current_user.id)
            response = send_file(output_path, as_attachment=True, download_name=f"reformatted_{filename}")
            os.remove(input_path)
            if template_used and os.path.exists(temp_template_path):
                os.remove(temp_template_path)
            os.remove(output_path)
            return response

    # Handle GET with query parameter
    client_id = request.args.get('client_id', '')
    if client_id and (client_id in clients or client_id == ''):
        session['selected_client'] = client_id
        session.pop('selected_template', None)
        session.pop('selected_prompt', None)
        selected_client = client_id
        selected_template = None
        selected_prompt = 'Custom'

    # Load templates and prompts
    conn = get_db_connection()
    cur = conn.cursor()
    if selected_client:
        cur.execute(
            "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template IS NOT NULL",
            (current_user.id, selected_client)
        )
        templates = [{'template_name': row[0], 'prompt_name': row[1]} for row in cur.fetchall()]
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id, selected_client)
        )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
    else:
        cur.execute(
            "SELECT template_name, prompt_name FROM settings WHERE user_id = %s AND client_id = '' AND template IS NOT NULL",
            (current_user.id,)
        )
        templates = [{'template_name': row[0], 'prompt_name': row[1]} for row in cur.fetchall()]
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = '' AND prompt IS NOT NULL AND template_name IS NULL",
            (current_user.id,)
        )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
    cur.close()
    conn.close()
    logger.info(f"Templates for client {selected_client or 'global'}: {templates}")
    logger.info(f"Prompts for client {selected_client or 'global'}: {prompts}")

    if selected_template:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT prompt->'prompt' AS prompt_content, prompt_name, template IS NOT NULL AS has_file "
            "FROM settings WHERE user_id = %s AND (client_id = %s OR client_id = '') AND template_name = %s LIMIT 1",
            (current_user.id, selected_client or '', selected_template)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result:
            prompt_content = result[0] or ''
            selected_prompt = result[1] or 'Custom'
            has_template_file = result[2]
        else:
            selected_template = None
            selected_prompt = 'Custom'
            prompt_content = ''

    return render_template('index.html', clients=clients, selected_client=selected_client, templates=templates, prompts=prompts, selected_template=selected_template, selected_prompt=selected_prompt, prompt_content=prompt_content, has_template_file=has_template_file)

# Existing functionality
AI_API_URL = os.environ.get('AI_API_URL', 'https://api.openai.com/v1/chat/completions')
API_KEY = os.environ.get('API_KEY', 'your-api-key')

DEFAULT_AI_PROMPT = """You are a medical document analyst. Analyze the provided document content and categorize it into the following sections based on the input text and tables:
- Summary: A concise overview of the drug, its purpose, and key findings.
- Background: Context about the disease or condition the drug treats.
- Monograph: Official prescribing information, usage guidelines, or clinical details.
- Real-World Experiences: Patient or clinician experiences, if present (else empty).
- Enclosures: Descriptions of supporting documents, posters, or additional materials.
- Tables: Assign tables to appropriate sections (e.g., 'Patient Demographics', 'Adverse Events') based on their content.
Return a JSON object with these keys and the corresponding content extracted or rewritten from the input. Preserve references separately. Ensure the response is valid JSON. For tables, return a dictionary where keys are descriptive section names and values are lists of rows, each row being a list of cell values. Focus on accurately interpreting and summarizing the source material, avoiding any formatting instructions."""

def load_prompt(client_id=None, user_id=None, prompt_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id is not None and user_id and prompt_name:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE client_id = %s AND user_id = %s AND prompt_name = %s AND prompt IS NOT NULL AND template_name IS NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id, prompt_name)
            )
        elif client_id is not None and user_id:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE client_id = %s AND user_id = %s AND prompt IS NOT NULL AND template_name IS NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id)
            )
        else:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = '' AND prompt IS NOT NULL AND template_name IS NULL ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result and result[0] else DEFAULT_AI_PROMPT
    except Exception as e:
        logger.error(f"Error loading prompt: {str(e)}")
        return DEFAULT_AI_PROMPT

def load_prompt_for_template(client_id, user_id, template_name):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = %s AND template_name = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (user_id, client_id, template_name)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result and result[0] else DEFAULT_AI_PROMPT
    except Exception as e:
        logger.error(f"Error loading prompt for template: {str(e)}")
        return DEFAULT_AI_PROMPT

def get_prompt_name_for_template(client_id, user_id, template_name):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT prompt_name FROM settings WHERE user_id = %s AND client_id = %s AND template_name = %s ORDER BY created_at DESC LIMIT 1",
            (user_id, client_id, template_name)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting prompt name for template: {str(e)}")
        return None

def save_prompt(prompt, client_id, user_id, prompt_name):
    try:
        if not prompt_name:
            raise ValueError(f"Prompt name cannot be empty: prompt_name={prompt_name}")
        if not prompt:
            raise ValueError(f"Prompt content cannot be empty")
        # Sanitize prompt to handle special characters
        sanitized_prompt = prompt.encode('utf-8', errors='replace').decode('utf-8')
        client_id = client_id or ''
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings (user_id, client_id, prompt, prompt_name) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT ON CONSTRAINT settings_unique_user_client_prompt_template DO UPDATE SET prompt = EXCLUDED.prompt",
            (user_id, client_id, Json({'prompt': sanitized_prompt}), prompt_name)
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Saved prompt '{prompt_name}' for client {client_id or 'global'}, user {user_id}: {sanitized_prompt[:100]}...")
    except Exception as e:
        logger.error(f"Error saving prompt: {str(e)}")
        raise

def save_template(file, client_id, user_id, prompt_name, template_name):
    try:
        if not template_name:
            raise ValueError(f"Template name cannot be empty: template_name={template_name}")
        if not prompt_name:
            raise ValueError(f"Prompt name cannot be empty: prompt_name={prompt_name}")
        client_id = client_id or ''
        file_data = file.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings (user_id, client_id, template, prompt_name, template_name) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT ON CONSTRAINT settings_unique_user_client_prompt_template DO UPDATE SET template = EXCLUDED.template, prompt_name = EXCLUDED.prompt_name",
            (user_id, client_id, file_data, prompt_name, template_name)
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Saved template '{template_name}' for client {client_id or 'global'}, user {user_id}, prompt {prompt_name}")
    except Exception as e:
        logger.error(f"Error saving template: {str(e)}")
        raise

def load_template(output_path, client_id=None, user_id=None, template_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id is not None and user_id and template_name:
            cur.execute(
                "SELECT template FROM settings WHERE client_id = %s AND user_id = %s AND template_name = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id, template_name)
            )
        elif client_id is not None and user_id:
            cur.execute(
                "SELECT template FROM settings WHERE client_id = %s AND user_id = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id)
            )
        else:
            cur.execute(
                "SELECT template FROM settings WHERE user_id = %s AND client_id = '' AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result and result[0]:
            with open(output_path, 'wb') as f:
                f.write(result[0])
            return True
        return False
    except Exception as e:
        logger.error(f"Error loading template: {str(e)}")
        return False

def get_clients(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT client_id FROM settings WHERE user_id = %s AND client_id IS NOT NULL AND client_id != ''",
            (user_id,)
        )
        clients = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Fetched clients for user {user_id}: {clients}")
        return clients
    except Exception as e:
        logger.error(f"Error getting clients: {str(e)}")
        return []

def extract_content_from_docx(file_path):
    try:
        doc = Document(file_path)
        content = {"text_chunks": [], "tables": [], "references": []}
        in_references = False
        chunk = []
        chunk_size = 1000  # Characters per chunk for large files
        current_chunk_length = 0

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                if text.lower().startswith("references"):
                    in_references = True
                    continue
                if in_references:
                    content["references"].append(text)
                else:
                    chunk.append(text)
                    current_chunk_length += len(text)
                    if current_chunk_length >= chunk_size:
                        content["text_chunks"].append("\n".join(chunk))
                        chunk = []
                        current_chunk_length = 0
        if chunk:
            content["text_chunks"].append("\n".join(chunk))

        for table in doc.tables:
            table_data = []
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_data:
                    table_data.append(row_data)
            if table_data:
                logger.info(f"Extracted table: {table_data}")
                content["tables"].append(table_data)
        return content
    except Exception as e:
        logger.error(f"Error extracting content from docx: {str(e)}")
        raise

def call_ai_api(content, client_id=None, user_id=None, prompt_name=None, custom_prompt=None):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    ai_prompt = custom_prompt if custom_prompt else load_prompt(client_id, user_id, prompt_name)
    
    def process_chunk(chunk_text, tables, chunk_index):
        messages = [
            {"role": "system", "content": ai_prompt},
            {"role": "user", "content": f"Input Text (Chunk {chunk_index}):\n{chunk_text}\n\nTables:\n{json.dumps(tables)}"}
        ]
        payload = {
            "model": "gpt-3.5-turbo-0125",
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7
        }
        try:
            response = requests.post(AI_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            if not response.text:
                logger.error(f"Empty response from API (chunk {chunk_index})")
                return {"error": f"Empty response from API in chunk {chunk_index}"}
            try:
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    logger.error(f"No choices in API response (chunk {chunk_index}): {data}")
                    return {"error": f"No valid choices in API response for chunk {chunk_index}"}
                raw_content = data["choices"][0]["message"]["content"]
                logger.info(f"Raw AI response (chunk {chunk_index}): {raw_content[:1000]}...")
                try:
                    parsed_content = json.loads(raw_content)
                    if not isinstance(parsed_content, dict):
                        raise ValueError("AI response is not a JSON object")
                    # Normalize key case
                    normalized_content = {k.lower(): v for k, v in parsed_content.items()}
                    return normalized_content
                except json.JSONDecodeError as e:
                    logger.error(f"JSON validation error (chunk {chunk_index}): {str(e)}, raw: {raw_content[:1000]}")
                    try:
                        # Parse markdown/plain text as fallback
                        lines = raw_content.split("\n")
                        parsed_content = {}
                        current_key = None
                        current_value = []
                        for line in lines:
                            line = line.strip()
                            if line.startswith("**") and line.endswith("**"):
                                if current_key:
                                    parsed_content[current_key.lower()] = "\n".join(current_value).strip()
                                    current_value = []
                                current_key = line.strip("**").strip()
                            elif line:
                                current_value.append(line)
                        if current_key and current_value:
                            parsed_content[current_key.lower()] = "\n".join(current_value).strip()
                        if parsed_content:
                            logger.info(f"Parsed markdown content (chunk {chunk_index}): {parsed_content}")
                            return parsed_content
                        return {"error": f"Failed to parse non-JSON content in chunk {chunk_index}"}
                    except Exception as parse_e:
                        logger.error(f"Markdown parsing error (chunk {chunk_index}): {str(parse_e)}")
                        return {"error": f"Invalid JSON in chunk {chunk_index}: {str(e)}"}
            except ValueError as e:
                logger.error(f"Invalid JSON response (chunk {chunk_index}): {response.text[:1000]}")
                return {"error": f"Invalid JSON response in chunk {chunk_index}: {response.text[:1000]}"}
        except requests.exceptions.HTTPError as e:
            error_response = response.text
            logger.error(f"API Error (chunk {chunk_index}): {response.status_code} - {error_response}")
            return {"error": f"HTTP Error in chunk {chunk_index}: {response.status_code} - {error_response}"}
        except Exception as e:
            logger.error(f"Unexpected Error (chunk {chunk_index}): {str(e)}")
            return {"error": str(e)}

    # Process text chunks
    results = []
    for i, chunk in enumerate(content["text_chunks"], 1):
        result = process_chunk(chunk, content["tables"], i)
        results.append(result)
    
    # Merge results
    merged_content = {}
    errors = []
    for result in results:
        if "error" in result:
            errors.append(result["error"])
        else:
            for key, value in result.items():
                if key in merged_content:
                    if isinstance(value, str) and isinstance(merged_content[key], str):
                        if value not in merged_content[key].split("\n"):
                            merged_content[key] += "\n" + value if value else ""
                    elif isinstance(value, dict) and isinstance(merged_content[key], dict):
                        for subkey, subvalue in value.items():
                            if subkey in merged_content[key]:
                                if isinstance(subvalue, str) and isinstance(merged_content[key][subkey], str):
                                    if subvalue not in merged_content[key][subkey].split("\n"):
                                        merged_content[key][subkey] += "\n" + subvalue if subvalue else ""
                                elif isinstance(subvalue, list) and isinstance(merged_content[key][subkey], list):
                                    merged_content[key][subkey].extend([x for x in subvalue if x not in merged_content[key][subkey]])
                                elif isinstance(subvalue, dict) and isinstance(merged_content[key][subkey], dict):
                                    for subsubkey, subsubvalue in subvalue.items():
                                        merged_content[key][subkey][subsubkey] = subsubvalue
                                else:
                                    merged_content[key][subkey] = subvalue
                            else:
                                merged_content[key][subkey] = subvalue
                    elif isinstance(value, list) and isinstance(merged_content[key], list):
                        merged_content[key].extend([x for x in value if x not in merged_content[key]])
                    else:
                        # Overwrite with newer value to avoid conflicts
                        merged_content[key] = value
                else:
                    merged_content[key] = value
    
    if errors:
        logger.error(f"Errors in processing: {errors}")
        return {
            "error": "; ".join(errors),
            "content": content["text_chunks"][0][:500] if content["text_chunks"] else "",
            "tables": content["tables"],
            "references": content["references"]
        }
    
    # Add references
    merged_content["references"] = content["references"]
    logger.info(f"Merged AI response: {merged_content}")
    return merged_content

def add_styled_heading(doc, text, level=1):
    try:
        para = doc.add_paragraph()
        run = para.add_run(text)
        run.bold = True
        run.underline = True if level == 1 else False
        run.font.name = "Arial"
        run.font.size = Pt(14)
        return para
    except Exception as e:
        logger.error(f"Error adding styled heading: {str(e)}")
        raise

def add_styled_text(doc, text, bullet=False):
    try:
        para = doc.add_paragraph(style="List Bullet" if bullet else None)
        run = para.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(12)
        return para
    except Exception as e:
        logger.error(f"Error adding styled text: {str(e)}")
        raise

def add_styled_table(doc, table_data, section_name):
    try:
        if not table_data or not table_data[0] or not any(cell for row in table_data for cell in row):
            logger.warning(f"Skipping invalid or empty table for section: {section_name}")
            return None
        max_cols = max(len(row) for row in table_data)
        table_data = [row + [""] * (max_cols - len(row)) for row in table_data]
        logger.info(f"Adding table for {section_name}: {table_data}")
        table = doc.add_table(rows=len(table_data), cols=max_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        for i, row_data in enumerate(table_data):
            row = table.rows[i]
            logger.debug(f"Processing row {i}: {row_data}")
            for j, cell_text in enumerate(row_data):
                cell = row.cells[j]
                cell.text = cell_text or ""
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = "Calibri"
                        run.font.size = Pt(10)
        for i, row in enumerate(table.rows):
            for j, cell in enumerate(row.cells):
                logger.debug(f"Setting borders for cell at row {i}, col {j}")
                tcPr = cell._tc.get_or_add_tcPr()
                tcBorders = tcPr.first_child_found_in("w:tcBorders")
                if not tcBorders:
                    tcBorders = OxmlElement('w:tcBorders')
                    tcPr.append(tcBorders)
                for border_name in ['top', 'left', 'bottom', 'right']:
                    border = OxmlElement(f'w:{border_name}')
                    border.set(qn('w:val'), 'single')
                    border.set(qn('w:sz'), '4')
                    border.set(qn('w:space'), '0')
                    border.set(qn('w:color'), 'auto')
                    tcBorders.append(border)
        return table
    except Exception as e:
        logger.error(f"Error adding styled table for {section_name}: {str(e)}")
        raise

def create_reformatted_docx(sections, output_path, client_id=None, user_id=None):
    try:
        template_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_template.docx')
        doc = Document(template_path) if os.path.exists(template_path) else Document()
        
        def apply_template_style(paragraph, template_para):
            if template_para and template_para.runs:
                for run in paragraph.runs:
                    run.bold = template_para.runs[0].bold if template_para.runs else False
                    run.underline = template_para.runs[0].underline if template_para.runs else False
                    run.font.name = template_para.runs[0].font.name if template_para.runs else "Arial"
                    run.font.size = template_para.runs[0].font.size if template_para.runs else Pt(12)
            paragraph.style = template_para.style if template_para and template_para.style else None
        
        def format_content(content, indent=0):
            if isinstance(content, str):
                return content.strip()
            elif isinstance(content, list):
                formatted = []
                for item in content:
                    if isinstance(item, str):
                        formatted.append("• " + item.strip())
                    elif isinstance(item, dict):
                        for subkey, subvalue in item.items():
                            subcontent = format_content(subvalue, indent + 1)
                            if subcontent:
                                formatted.append(f"{'  ' * indent}{subkey}: {subcontent}")
                    elif isinstance(item, list):
                        formatted.extend(format_content(item, indent + 1))
                return "\n".join(formatted)
            elif isinstance(content, dict):
                formatted = []
                for subkey, subvalue in content.items():
                    subcontent = format_content(subvalue, indent + 1)
                    if subcontent:
                        formatted.append(f"{'  ' * indent}{subkey}: {subcontent}")
                return "\n".join(formatted)
            return ""

        # Load template for styling
        template_doc = Document(template_path) if os.path.exists(template_path) else None
        template_paras = template_doc.paragraphs if template_doc else []
        
        # Handle errors
        if "error" in sections:
            para = doc.add_paragraph(f"Error: {sections['error']}")
            apply_template_style(para, template_paras[0] if template_paras else None)
            doc.save(output_path)
            return
        
        # Map JSON keys to template headers
        key_mapping = {
            "name": "Name",
            "contact": "Contact",
            "contact_information": "Contact",
            "professional summary": "Professional Summary",
            "summary": "Professional Summary",
            "core competencies": "Core Competencies",
            "skills": "Core Competencies",
            "professional_experience": "Professional Experience",
            "work_experience": "Professional Experience",
            "work experience": "Professional Experience",
            "experience": "Professional Experience",
            "education": "Education",
            "affiliations": "Affiliations",
            "professional_affiliations": "Affiliations",
            "certifications": "Certifications",
            "projects_awards": "Projects and Awards",
            "projects & awards": "Projects and Awards"
        }
        
        # Add sections dynamically
        processed_keys = set()
        for key, value in sections.items():
            normalized_key = key.lower()
            if normalized_key in processed_keys:
                continue
            processed_keys.add(normalized_key)
            
            display_key = key_mapping.get(normalized_key, key.capitalize())
            if display_key == "References" and value:
                para = doc.add_paragraph("References")
                apply_template_style(para, next((p for p in template_paras if "references" in p.text.lower()), template_paras[0] if template_paras else None))
                for ref in value:
                    para = doc.add_paragraph(ref, style="ListBullet")
                    apply_template_style(para, next((p for p in template_paras if p.style and "bullet" in p.style.name.lower()), template_paras[0] if template_paras else None))
            else:
                para = doc.add_paragraph(display_key)
                apply_template_style(para, next((p for p in template_paras if display_key.lower() in p.text.lower()), template_paras[0] if template_paras else None))
                
                formatted_content = format_content(value)
                if formatted_content:
                    lines = formatted_content.split("\n")
                    for line in lines:
                        if line.strip():
                            para = doc.add_paragraph(line, style="ListBullet" if line.startswith("•") else None)
                            apply_template_style(para, next((p for p in template_paras if p.style and "bullet" in p.style.name.lower()), template_paras[0] if template_paras else None))
        
        doc.save(output_path)
    except Exception as e:
        logger.error(f"Error creating reformatted docx: {str(e)}")
        raise

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)