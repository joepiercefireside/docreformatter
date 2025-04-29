from flask import Flask, request, send_file, render_template
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
import requests
import json
import re
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Get AI API config from environment variables
AI_API_URL = os.environ.get('AI_API_URL', 'https://api.openai.com/v1/chat/completions')
API_KEY = os.environ.get('API_KEY', 'your-api-key')

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
                if row_data:  # Only add non-empty rows
                    table_data.append(row_data)
            if table_data:  # Only add non-empty tables
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
    
    messages = [
        {
            "role": "system",
            "content": "You are a medical document analyst. Categorize the provided document content into sections matching this output format: "
                       "- Summary: Brief overview of the drug and key points.\n"
                       "- Background Information: Disease context and background.\n"
                       "- Product Monograph: Official prescribing information or usage guidelines.\n"
                       "- Real-World Experiences: Patient or clinician experiences (if present, else empty).\n"
                       "- Enclosures: Supporting documents or posters.\n"
                       "Return a JSON object with these keys and their corresponding text from the input. Assign tables to relevant sections (e.g., Clinical Trial Results). Preserve references separately. Ensure the response is valid JSON. For tables, return a dictionary where keys are section names and values are lists of rows, each row being a list of cell values."
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
            
            # Validate and flatten tables to remove extra nesting
            if "tables" in parsed_content and isinstance(parsed_content["tables"], dict):
                for section_name, table_data in parsed_content["tables"].items():
                    # If table_data is overly nested, flatten it
                    while isinstance(table_data, list) and len(table_data) == 1 and isinstance(table_data[0], list):
                        table_data = table_data[0]
                    parsed_content["tables"][section_name] = table_data
                    # Ensure table_data is a list of lists (rows)
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
    """Add a bold, underlined heading in 14pt Arial."""
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
    """Add text in 12pt Calibri, optionally as a bullet."""
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
    """Add a table with 10pt Calibri text and borders."""
    try:
        if not table_data or not table_data[0] or not any(cell for row in table_data for cell in row):
            print(f"Skipping invalid or empty table for section: {section_name}")
            return None
        # Ensure all rows have the same number of columns
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
        
        # Simplified border styling
        for i, row in enumerate(table.rows):
            for j, cell in enumerate(row.cells):
                print(f"Setting borders for cell at row {i}, col {j}")
                cell._tc.get_or_add_tcPr().get_or_add_tcBorders()
        
        return table
    except Exception as e:
        print(f"Error adding styled table for {section_name}: {str(e)}")
        raise

def create_reformatted_docx(sections, output_path, drug_name="KRESLADI"):
    """Create a new .docx matching the output format."""
    try:
        doc = Document()
        
        add_styled_heading(doc, f"{drug_name} (marnetegragene autotemcel)", level=1)
        
        # Ensure required keys exist
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
def index():
    """Render the upload form."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
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
        return f"Internal Server Error: {str(e)}", 500
    finally:
        # Clean up files
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