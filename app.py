from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from auth import setup_auth, login_required
from database import init_db, get_db_connection, get_clients, load_ai_prompt, save_ai_prompt, save_template
from document import extract_content_from_docx, call_ai_api, create_reformatted_docx
from werkzeug.utils import secure_filename
import os
import json
from psycopg2.extras import RealDictCursor
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', '/tmp')

setup_auth(app)
init_db()

ALLOWED_EXTENSIONS = {'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
@login_required
def index():
    user_id = request.current_user.id
    client_id = request.args.get('client_id')
    clients = get_clients(user_id)
    logger.info(f"Fetched clients for user {user_id}: {clients}")
    prompts = []
    if client_id:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT prompt_name, prompt->'prompt' AS prompt_content
                    FROM settings
                    WHERE user_id = %s AND client_id = %s
                """, (user_id, client_id))
                prompts = cur.fetchall()
            logger.info(f"Prompts for client {client_id}: {prompts}")
        finally:
            conn.close()
    return render_template('index.html', clients=clients, selected_client=client_id, prompts=prompts)

@app.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        if not client_id:
            flash('Client ID is required.', 'danger')
            return redirect(url_for('create_client'))
        try:
            default_prompt = json.dumps({
                'prompt': (
                    "You are a medical document analyst. Analyze the provided document content and categorize it into the following sections based on the input text and tables:\n"
                    "- Summary: A concise overview of the drug, its purpose, and key findings.\n"
                    "- Background: Context about the disease or condition the drug treats.\n"
                    "- Monograph: Official prescribing information, usage guidelines, or clinical details.\n"
                    "- Real-World Experiences: Patient or clinician experiences, if present (else empty).\n"
                    "- Enclosures: Descriptions of supporting documents, posters, or additional materials.\n"
                    "- Tables: Assign tables to appropriate sections (e.g., 'Patient Demographics', 'Adverse Events') based on their content.\n"
                    "Return a JSON object with these keys and the corresponding content extracted or rewritten from the input. "
                    "Preserve references separately. Ensure the response is valid JSON. "
                    "For tables, return a dictionary where keys are descriptive section names and values are lists of rows, each row being a list of cell values. "
                    "Focus on accurately interpreting and summarizing the source material, avoiding any formatting instructions."
                ),
                'prompt_name': 'Default Prompt'
            })
            save_ai_prompt(request.current_user.id, client_id, default_prompt, 'Default Prompt')
            flash('Client created successfully.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error creating client: {str(e)}")
            flash(f'Error creating client: {str(e)}', 'danger')
            return redirect(url_for('create_client'))
    return render_template('create_client.html')

@app.route('/update_prompt', methods=['POST'])
@login_required
def update_prompt():
    user_id = request.current_user.id
    client_id = request.form.get('client_id')
    prompt_name = request.form.get('prompt_name')
    prompt_content = request.form.get('prompt_content')
    if not all([client_id, prompt_name, prompt_content]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('index'))
    try:
        prompt_data = json.dumps({'prompt': prompt_content, 'prompt_name': prompt_name})
        save_ai_prompt(user_id, client_id, prompt_data, prompt_name)
        flash('Prompt updated successfully.', 'success')
    except Exception as e:
        logger.error(f"Error updating prompt: {str(e)}")
        flash(f'Error updating prompt: {str(e)}', 'danger')
    return redirect(url_for('index', client_id=client_id))

@app.route('/upload_template', methods=['POST'])
@login_required
def upload_template():
    user_id = request.current_user.id
    client_id = request.form.get('client_id')
    if 'template' not in request.files or not client_id:
        flash('Template file and client ID are required.', 'danger')
        return redirect(url_for('index'))
    file = request.files['template']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('index'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(file_path)
            save_template(user_id, client_id, file_path)
            flash('Template uploaded successfully.', 'success')
        except Exception as e:
            logger.error(f"Error uploading template: {str(e)}")
            flash(f'Error uploading template: {str(e)}', 'danger')
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    else:
        flash('Invalid file format. Only .docx files are allowed.', 'danger')
    return redirect(url_for('index', client_id=client_id))

@app.route('/process_document', methods=['POST'])
@login_required
def process_document():
    user_id = request.current_user.id
    client_id = request.form.get('client_id')
    prompt_name = request.form.get('prompt_name')
    if 'document' not in request.files or not client_id:
        flash('Document file and client ID are required.', 'danger')
        return redirect(url_for('index'))
    file = request.files['document']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('index'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], f'reformatted_{filename}')
        try:
            file.save(file_path)
            content = extract_content_from_docx(file_path)
            ai_response = call_ai_api(content, client_id, user_id, prompt_name)
            if 'error' in ai_response:
                flash(f'AI processing error: {ai_response["error"]}', 'danger')
                return redirect(url_for('index', client_id=client_id))
            create_reformatted_docx(ai_response, output_path, client_id=client_id, user_id=user_id)
            flash('Document processed successfully.', 'success')
            return send_file(output_path, as_attachment=True)
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            flash(f'Error processing document: {str(e)}', 'danger')
            return redirect(url_for('index', client_id=client_id))
        finally:
            for path in [file_path, output_path]:
                if os.path.exists(path):
                    os.remove(path)
    else:
        flash('Invalid file format. Only .docx files are allowed.', 'danger')
    return redirect(url_for('index', client_id=client_id))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))