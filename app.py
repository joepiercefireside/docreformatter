from flask import Flask, request, send_file, render_template, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_httpauth import HTTPBasicAuth
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
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
from authlib.integrations.flask_client import OAuth
from urllib.parse import quote_plus

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')

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
                client_id VARCHAR(50),
                prompt JSONB,
                template BYTEA,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_client_id ON settings(client_id);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Initialized database schema")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
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
            flash('Invalid email or password')
        except Exception as e:
            print(f"Error during login: {str(e)}")
            flash('Login failed')
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
                flash('Email already registered')
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
            flash('Registration failed')
    return render_template('register.html')

@app.route('/google_login')
def google_login():
    redirect_uri = url_for('google_auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/google_auth')
def google_auth():
    token = google.authorize_access_token()
    user_info = google.parse_id_token(token)
    google_id = user_info['sub']
    email = user_info['email']
    try:
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
        flash('Google login failed')
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Existing functionality (updated for user_id)
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

def load_ai_prompt(client_id=None, user_id=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id and user_id:
            cur.execute("SELECT prompt FROM settings WHERE client_id = %s AND user_id = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1", (client_id, user_id))
        else:
            cur.execute("SELECT prompt FROM settings WHERE user_id = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0]['prompt'] if result and result[0] else DEFAULT_AI_PROMPT
    except Exception as e:
        print(f"Error loading AI prompt: {str(e)}")
        return DEFAULT_AI_PROMPT

def save_ai_prompt(prompt, client_id=None, user_id=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO settings (user_id, client_id, prompt) VALUES (%s, %s, %s)", (user_id, client_id, Json({'prompt': prompt})))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved AI prompt for client {client_id}, user {user_id}: {prompt[:100]}...")
    except Exception as e:
        print(f"Error saving AI prompt: {str(e)}")
        raise

def save_template(file, client_id=None, user_id=None):
    try:
        file_data = file.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO settings (user_id, client_id, template) VALUES (%s, %s, %s)", (user_id, client_id, file_data))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved template for client {client_id}, user {user_id}")
    except Exception as e:
        print(f"Error saving template: {str(e)}")
        raise

def load_template(output_path, client_id=None, user_id=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id and user_id:
            cur.execute("SELECT template FROM settings WHERE client_id = %s AND user_id = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1", (client_id, user_id))
        else:
            cur.execute("SELECT template FROM settings WHERE user_id = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result and result[0]:
            with open(output_path, 'wb') as f:
                f.write(result[0])
            return True
        return False
    except Exception as e:
        print(f"Error loading template: {str(e)}")
        return False

def get_clients(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT client_id FROM settings WHERE user_id = %s AND client_id IS NOT NULL", (user_id,))
        clients = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return clients
    except Exception as e:
        print(f"Error getting clients: {str(e)}")
        return []

def extract_content_from_docx(file_path):
    try:
        doc = Document(file_path)
        content = {"text": [], "tables": [], "references": []}
        
        in_references = False
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                if text.lower().startswith("references"):
                    in_references = True
                    continue
                if in_references:
                    content["references"].append(text)
                else:
                    content["text"].append(text)
        
        for table in doc.tables:
            table_data = []
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_data:
                    table_data.append(row_data)
            if table_data:
                print(f"Extracted table: {table_data}")
                content["tables"].append(table_data)
        
        return content
    except Exception as e:
        print(f"Error extracting content from docx: {str(e)}")
        raise

def call_ai_api(content, client_id=None, user_id=None):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    text = "\n".join(content["text"])
    tables = json.dumps(content["tables"])
    
    ai_prompt = load_ai_prompt(client_id, user_id)
    
    messages = [
        {
            "role": "system",
            "content": ai_prompt
        },
        {
            "role": "user",
            "content": f"Input Text:\n{text}\n\nTables:\n{tables}\n\nOutput format:\n"
                       "{\"summary\": \"...\", \"background\": \"...\", \"monograph\": \"...\", "
                       "\"real_world\": \"\", \"enclosures\": \"...\", "
                       "\"tables\": {\"section_name\": [[\"cell1\", \"cell2\"], [\"cell3\", \"cell4\"]]}, "
                       "\"references\": [\"ref1\", \"ref2\", ...]}"
        }
    ]
    
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(AI_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        raw_content = data["choices"][0]["message"]["content"]
        print(f"Raw AI response: {raw_content[:1000]}...")
        
        try:
            parsed_content = json.loads(raw_content)
            if not isinstance(parsed_content, dict):
                raise ValueError("AI response is not a JSON object")
            
            if "tables" in parsed_content and isinstance(parsed_content["tables"], dict):
                for section_name, table_data in parsed_content["tables"].items():
                    while isinstance(table_data, list) and len(table_data) == 1 and isinstance(table_data[0], list):
                        table_data = table_data[0]
                    parsed_content["tables"][section_name] = table_data
                    if not all(isinstance(row, list) for row in table_data):
                        print(f"Invalid table data for {section_name}: {table_data}")
                        parsed_content["tables"][section_name] = []
            
            print(f"Parsed AI response: {parsed_content}")
            return parsed_content
        except json.JSONDecodeError as e:
            print(f"JSON validation error: {str(e)}")
            return {
                "error": f"Invalid JSON from AI: {str(e)}",
                "summary": "Unable to categorize due to AI response error",
                "background": content["text"][:500] if content["text"] else "",
                "monograph": "",
                "real_world": "",
                "enclosures": "",
                "tables": {},
                "references": content["references"]
            }
    except requests.exceptions.HTTPError as e:
        error_response = response.json() if response else {"error": str(e)}
        print(f"API Error: {response.status_code} - {error_response}")
        return {"error": f"HTTP Error: {str(e)} - {error_response}"}
    except Exception as e:
        print(f"Unexpected Error: {str(e)}")
        return {"error": str(e)}

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
        print(f"Error adding styled heading: {str(e)}")
        raise

def add_styled_text(doc, text, bullet=False):
    try:
        para = doc.add_paragraph(style="List Bullet" if bullet else None)
        run = para.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(12)
        return para
    except Exception as e:
        print(f"Error adding styled text: {str(e)}")
        raise

def add_styled_table(doc, table_data, section_name):
    try:
        if not table_data or not table_data[0] or not any(cell for row in table_data for cell in row):
            print(f"Skipping invalid or empty table for section: {section_name}")
            return None
        max_cols = max(len(row) for row in table_data)
        table_data = [row + [""] * (max_cols - len(row)) for row in table_data]
        print(f"Adding table for {section_name}: {table_data}")
        
        table = doc.add_table(rows=len(table_data), cols=max_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        
        for i, row_data in enumerate(table_data):
            row = table.rows[i]
            print(f"Processing row {i}: {row_data}")
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
                print(f"Setting borders for cell at row {i}, col {j}")
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
        print(f"Error adding styled table for {section_name}: {str(e)}")
        raise

def create_reformatted_docx(sections, output_path, drug_name="KRESLADI", client_id=None, user_id=None):
    try:
        default_sections = {
            "summary": "No summary provided",
            "background": "No background provided",
            "monograph": "No monograph provided",
            "real_world": "",
            "enclosures": "No enclosures provided",
            "tables": {},
            "references": []
        }
        sections = {**default_sections, **sections}

        template_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_template.docx')
        if load_template(template_path, client_id, user_id):
            print(f"Using template for client {client_id}, user {user_id}: {template_path}")
            doc = Document(template_path)
            
            def replace_placeholder(paragraph, placeholder, content, preserve_style=True):
                if placeholder.lower() in paragraph.text.lower():
                    if preserve_style:
                        paragraph.text = ""
                        run = paragraph.add_run(content)
                        if paragraph.runs:
                            first_run = paragraph.runs[0]
                            run.bold = first_run.bold
                            run.underline = first_run.underline
                            run.font.name = first_run.font.name
                            run.font.size = first_run.font.size
                    else:
                        paragraph.text = content

            def add_table_after_placeholder(doc, placeholder, table_data, section_name):
                for i, para in enumerate(doc.paragraphs):
                    if placeholder.lower() in para.text.lower():
                        print(f"Adding table for {section_name} after placeholder: {placeholder}")
                        max_cols = max(len(row) for row in table_data)
                        table_data = [row + [""] * (max_cols - len(row)) for row in table_data]
                        table = doc.add_table(rows=len(table_data), cols=max_cols)
                        table.alignment = WD_TABLE_ALIGNMENT.CENTER
                        table.autofit = True
                        for row_idx, row_data in enumerate(table_data):
                            row = table.rows[row_idx]
                            for col_idx, cell_text in enumerate(row_data):
                                cell = row.cells[col_idx]
                                cell.text = cell_text or ""
                                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                                for p in cell.paragraphs:
                                    for r in p.runs:
                                        r.font.name = para.runs[0].font.name if para.runs else "Calibri"
                                        r.font.size = para.runs[0].font.size if para.runs else Pt(10)
                        if doc.tables:
                            for row in table.rows:
                                for cell in row.cells:
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
                        return True
                return False

            for para in doc.paragraphs:
                if "drug name" in para.text.lower():
                    replace_placeholder(para, "drug name", f"{drug_name} (marnetegragene autotemcel)")
                elif "summary" in para.text.lower():
                    replace_placeholder(para, "summary", sections["summary"])
                elif "background" in para.text.lower():
                    replace_placeholder(para, "background", sections["background"])
                elif "monograph" in para.text.lower():
                    replace_placeholder(para, "monograph", sections["monograph"])
                elif "real-world experiences" in para.text.lower() and sections["real_world"].strip():
                    replace_placeholder(para, "real-world experiences", sections["real_world"])
                elif "enclosures" in para.text.lower():
                    replace_placeholder(para, "enclosures", sections["enclosures"])
                elif "references" in para.text.lower():
                    replace_placeholder(para, "references", "\n".join([f"{i}. {ref}" for i, ref in enumerate(sections["references"], 1)]))

            for section_name, table_data in sections["tables"].items():
                if not add_table_after_placeholder(doc, section_name, table_data, section_name):
                    print(f"No placeholder found for table: {section_name}, appending at end")
                    para = doc.add_paragraph(section_name)
                    add_styled_table(doc, table_data, section_name)
        else:
            print(f"No template found for client {client_id}, user {user_id}, using default formatting")
            doc = Document()
            
            add_styled_heading(doc, f"{drug_name} (marnetegragene autotemcel)", level=1)
            
            add_styled_heading(doc, "Summary", level=1)
            for line in sections["summary"].split("\n"):
                if line.strip():
                    add_styled_text(doc, line, bullet=True)
            
            add_styled_heading(doc, "Background Information on Leukocyte Adhesion Deficiency (LAD-I)", level=1)
            for line in sections["background"].split("\n"):
                if line.strip():
                    add_styled_text(doc, line)
            
            add_styled_heading(doc, "Product Monograph", level=1)
            for line in sections["monograph"].split("\n"):
                if line.strip():
                    add_styled_text(doc, line, bullet=True)
            
            if sections["real_world"].strip():
                add_styled_heading(doc, "Real-World Experiences with KRESLADI", level=1)
                for line in sections["real_world"].split("\n"):
                    if line.strip():
                        add_styled_text(doc, line)
            
            print(f"Processing tables: {sections['tables']}")
            for section_name, table_data in sections["tables"].items():
                add_styled_heading(doc, section_name, level=2)
                add_styled_table(doc, table_data, section_name)
            
            add_styled_heading(doc, "Figures", level=1)
            add_styled_text(doc, "Insert Figure 1: Study Administration and Treatment here")
            add_styled_text(doc, "Insert Figure 2: Incidence of Infection-related Hospitalizations here")
            
            add_styled_heading(doc, "Enclosures", level=1)
            for line in sections["enclosures"].split("\n"):
                if line.strip():
                    add_styled_text(doc, line, bullet=True)
            
            add_styled_heading(doc, "References", level=1)
            for i, ref in enumerate(sections["references"], 1):
                add_styled_text(doc, f"{i}. {ref}", bullet=False)
        
        doc.save(output_path)
    except Exception as e:
        print(f"Error creating reformatted docx: {str(e)}")
        raise

@app.route('/')
@login_required
def index():
    ai_prompt = load_ai_prompt(user_id=current_user.id)
    clients = get_clients(current_user.id)
    return render_template('index.html', ai_prompt=ai_prompt, clients=clients)

@app.route('/load_client', methods=['POST'])
@login_required
def load_client():
    try:
        data = request.form
        client_id = data.get('client_id')
        if not client_id:
            return jsonify({'error': 'Client ID cannot be empty'}), 400
        prompt = load_ai_prompt(client_id, current_user.id)
        return jsonify({'prompt': prompt}), 200
    except Exception as e:
        print(f"Error loading client: {str(e)}")
        return jsonify({'error': 'Failed to load client'}), 500

@app.route('/update_prompt', methods=['POST'])
@login_required
def update_prompt():
    try:
        data = request.form
        print(f"Form data: {dict(data)}")
        new_prompt = data.get('prompt', '').strip()
        client_id = data.get('client_id')
        if not new_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400
        save_ai_prompt(new_prompt, client_id, current_user.id)
        return jsonify({'message': 'Prompt updated successfully'}), 200
    except Exception as e:
        print(f"Error updating prompt: {str(e)}")
        return jsonify({'error': 'Failed to update prompt'}), 500

@app.route('/upload_template', methods=['POST'])
@login_required
def upload_template():
    try:
        if 'template' not in request.files:
            return jsonify({'error': 'No template file uploaded'}), 400
        file = request.files['template']
        if file.filename == '':
            return jsonify({'error': 'No template file selected'}), 400
        if not file.filename.endswith('.docx'):
            return jsonify({'error': 'Only .docx files are supported'}), 400
        client_id = request.form.get('client_id')
        save_template(file, client_id, current_user.id)
        return jsonify({'message': 'Template uploaded successfully'}), 200
    except Exception as e:
        print(f"Error uploading template: {str(e)}")
        return jsonify({'error': 'Failed to upload template'}), 500

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    input_path = None
    output_path = None
    try:
        if 'file' not in request.files:
            return "No file uploaded", 400
        file = request.files['file']
        if file.filename == '':
            return "No file selected", 400
        if not file.filename.endswith('.docx'):
            return "Only .docx files are supported", 400
        client_id = request.form.get('client_id')
        
        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)
        
        content = extract_content_from_docx(input_path)
        sections = call_ai_api(content, client_id, current_user.id)
        if "error" in sections:
            print(f"AI processing failed: {sections['error']}")
            return f"AI API error: {sections['error']}", 500
        
        sections["references"] = content["references"]
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"reformatted_{filename}")
        create_reformatted_docx(sections, output_path, client_id=client_id, user_id=current_user.id)
        
        return send_file(output_path, as_attachment=True, download_name=f"reformatted_{filename}")
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return "Internal Server Error", 500
    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.remove(input_path)
            except Exception as e:
                print(f"Error removing input file: {str(e)}")
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception as e:
                print(f"Error removing output file: {str(e)}")

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)