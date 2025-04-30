from flask import Flask, request, send_file, render_template, jsonify
from flask_httpauth import HTTPBasicAuth
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import requests
import json
import re
import os
import psycopg2
from psycopg2.extras import Json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
auth = HTTPBasicAuth()

# Authentication setup
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', 'default-password')
users = {"admin": AUTH_PASSWORD}

@auth.verify_password
def verify_password(username, password):
    return users.get(username) == password

# Database setup
DATABASE_URL = os.environ.get('DATABASE_URL')
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY,
            prompt JSONB,
            template BYTEA,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# AI API configuration
AI_API_URL = os.environ.get('AI_API_URL', 'https://api.openai.com/v1/chat/completions')
API_KEY = os.environ.get('API_KEY', 'your-api-key')

# Default AI system prompt
DEFAULT_AI_PROMPT = """You are a medical document analyst. Analyze the provided document content and categorize it into the following sections based on the input text and tables:
- Summary: A concise overview of the drug, its purpose, and key findings.
- Background: Context about the disease or condition the drug treats.
- Monograph: Official prescribing information, usage guidelines, or clinical details.
- Real-World Experiences: Patient or clinician experiences, if present (else empty).
- Enclosures: Descriptions of supporting documents, posters, or additional materials.
- Tables: Assign tables to appropriate sections (e.g., 'Patient Demographics', 'Adverse Events') based on their content.
Return a JSON object with these keys and the corresponding content extracted or rewritten from the input. Preserve references separately. Ensure the response is valid JSON. For tables, return a dictionary where keys are descriptive section names and values are lists of rows, each row being a list of cell values. Focus on accurately interpreting and summarizing the source material, avoiding any formatting instructions."""

def load_ai_prompt():
    """Load the AI prompt from database or return the default."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT prompt FROM settings WHERE prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1")
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0]['prompt'] if result and result[0] else DEFAULT_AI_PROMPT
    except Exception as e:
        print(f"Error loading AI prompt: {str(e)}")
        return DEFAULT_AI_PROMPT

def save_ai_prompt(prompt):
    """Save the AI prompt to database."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO settings (prompt) VALUES (%s)", (Json({'prompt': prompt}),))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved AI prompt: {prompt[:100]}...")
    except Exception as e:
        print(f"Error saving AI prompt: {str(e)}")
        raise

def save_template(file):
    """Save the uploaded template .docx file to database."""
    try:
        file_data = file.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO settings (template) VALUES (%s)", (file_data,))
        conn.commit()
        cur.close()
        conn.close()
        print("Saved template to database")
    except Exception as e:
        print(f"Error saving template: {str(e)}")
        raise

def load_template(output_path):
    """Load the template .docx from database to a temporary file."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT template FROM settings WHERE template IS NOT NULL ORDER BY created_at DESC LIMIT 1")
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

def extract_content_from_docx(file_path):
    """Extract text, tables, and references from a .docx file."""
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

def call_ai_api(content):
    """Send content to AI to categorize into output sections."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    text = "\n".join(content["text"])
    tables = json.dumps(content["tables"])
    
    ai_prompt = load_ai_prompt()
    
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
    """Add a bold, underlined heading in 14pt Arial (for fallback formatting)."""
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
    """Add text in 12pt Calibri, optionally as a bullet (for fallback formatting)."""
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
    """Add a table with 10pt Calibri text and borders (for fallback formatting)."""
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

def create_reformatted_docx(sections, output_path, drug_name="KRESLADI"):
    """Create a new .docx using the stored template or fallback formatting."""
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
        if load_template(template_path):
            print(f"Using template: {template_path}")
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
            print("No template found, using default formatting")
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
@auth.login_required
def index():
    """Render the upload form with the current AI prompt."""
    ai_prompt = load_ai_prompt()
    return render_template('index.html', ai_prompt=ai_prompt)

@app.route('/update_prompt', methods=['POST'])
@auth.login_required
def update_prompt():
    """Update the AI system prompt."""
    try:
        data = request.form
        new_prompt = data.get('prompt', '').strip()
        if not new_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400
        save_ai_prompt(new_prompt)
        return jsonify({'message': 'Prompt updated successfully'}), 200
    except Exception as e:
        print(f"Error updating prompt: {str(e)}")
        return jsonify({'error': 'Failed to update prompt'}), 500

@app.route('/upload_template', methods=['POST'])
@auth.login_required
def upload_template():
    """Handle template .docx upload."""
    try:
        if 'template' not in request.files:
            return jsonify({'error': 'No template file uploaded'}), 400
        file = request.files['template']
        if file.filename == '':
            return jsonify({'error': 'No template file selected'}), 400
        if not file.filename.endswith('.docx'):
            return jsonify({'error': 'Only .docx files are supported'}), 400
        
        save_template(file)
        return jsonify({'message': 'Template uploaded successfully'}), 200
    except Exception as e:
        print(f"Error uploading template: {str(e)}")
        return jsonify({'error': 'Failed to upload template'}), 500

@app.route('/upload', methods=['POST'])
@auth.login_required
def upload_file():
    """Handle file upload and return reformatted .docx."""
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
        
        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)
        
        content = extract_content_from_docx(input_path)
        sections = call_ai_api(content)
        if "error" in sections:
            print(f"AI processing failed: {sections['error']}")
            return f"AI API error: {sections['error']}", 500
        
        sections["references"] = content["references"]
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"reformatted_{filename}")
        create_reformatted_docx(sections, output_path)
        
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
    init_db()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)