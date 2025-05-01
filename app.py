from flask import Flask, request, send_file, render_template, jsonify, redirect, url_for, flash, session
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
from auth import setup_auth
from database import init_db, get_clients, load_ai_prompt, save_ai_prompt, save_template
from document import extract_content_from_docx, call_ai_api, create_reformatted_docx

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

# Initialize authentication and database
setup_auth(app)
with app.app_context():
    init_db()

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    clients = get_clients(current_user.id)
    print(f"Clients for user {current_user.id}: {clients}")
    
    # Handle client selection
    selected_client = session.get('selected_client')
    selected_prompt = session.get('selected_prompt')
    prompt_content = ""
    prompts = []

    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id')
        
        if action == 'select_client' and client_id in clients:
            session['selected_client'] = client_id
            session.pop('selected_prompt', None)
            selected_client = client_id
            flash(f'Selected client: {client_id}', 'success')
        
        elif action == 'update_prompt':
            prompt_name = request.form.get('prompt_name')
            prompt_content = request.form.get('prompt_content')
            if prompt_name and prompt_content and selected_client:
                save_ai_prompt(prompt_content, selected_client, current_user.id, prompt_name)
                session['selected_prompt'] = prompt_name
                flash('Prompt updated successfully', 'success')
            else:
                flash('Failed to update prompt: Missing prompt name or content', 'danger')
        
        elif action == 'create_prompt':
            new_prompt_name = request.form.get('new_prompt_name')
            if new_prompt_name and selected_client:
                save_ai_prompt('', selected_client, current_user.id, new_prompt_name)
                session['selected_prompt'] = new_prompt_name
                flash(f'Created new prompt: {new_prompt_name}', 'success')
            else:
                flash('Failed to create prompt: Missing prompt name', 'danger')
        
        elif action == 'upload_template':
            template_file = request.files.get('template_file')
            prompt_name = request.form.get('prompt_name')
            if template_file and template_file.filename.endswith('.docx') and selected_client:
                save_template(template_file, selected_client, current_user.id, prompt_name or selected_prompt)
                flash('Template uploaded successfully', 'success')
            else:
                flash('Invalid template file or missing client', 'danger')
        
        elif action == 'upload_document':
            document_file = request.files.get('document_file')
            prompt_name = request.form.get('prompt_name')
            if document_file and document_file.filename.endswith('.docx') and prompt_name and selected_client:
                filename = secure_filename(document_file.filename)
                input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"reformatted_{filename}")
                document_file.save(input_path)
                content = extract_content_from_docx(input_path)
                sections = call_ai_api(content, selected_client, current_user.id, prompt_name)
                if "error" in sections:
                    flash(f"AI processing failed: {sections['error']}", 'danger')
                    return redirect(url_for('index'))
                sections["references"] = content["references"]
                create_reformatted_docx(sections, output_path, client_id=selected_client, user_id=current_user.id)
                response = send_file(output_path, as_attachment=True, download_name=f"reformatted_{filename}")
                os.remove(input_path)
                os.remove(output_path)
                return response
            else:
                flash('Invalid document file, prompt, or missing client', 'danger')

    # Handle GET with query parameter
    client_id = request.args.get('client_id')
    if client_id and client_id in clients:
        session['selected_client'] = client_id
        session.pop('selected_prompt', None)
        selected_client = client_id

    # Load prompts for selected client
    if selected_client and selected_client in clients:
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = %s AND prompt IS NOT NULL",
            (current_user.id, selected_client)
        )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1] or ''} for row in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"Prompts for client {selected_client}: {prompts}")
        if prompts:
            if selected_prompt and any(p['prompt_name'] == selected_prompt for p in prompts):
                prompt_content = next(p['prompt_content'] for p in prompts if p['prompt_name'] == selected_prompt)
            else:
                selected_prompt = prompts[0]['prompt_name']
                session['selected_prompt'] = selected_prompt
                prompt_content = prompts[0]['prompt_content']
        else:
            selected_prompt = None
            session.pop('selected_prompt', None)

    return render_template('index.html', 
                         clients=clients, 
                         selected_client=selected_client, 
                         prompts=prompts, 
                         selected_prompt=selected_prompt, 
                         prompt_content=prompt_content)

@app.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id').strip()
            prompt_name = request.form.get('prompt_name', 'Default Prompt').strip()
            prompt_content = request.form.get('prompt_content', load_ai_prompt()).strip()
            if not client_id:
                flash('Client ID cannot be empty', 'danger')
                return redirect(url_for('create_client'))
            if not prompt_name:
                flash('Prompt name cannot be empty', 'danger')
                return redirect(url_for('create_client'))
            from database import get_db_connection
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM settings WHERE user_id = %s AND client_id = %s AND prompt_name = %s", 
                       (current_user.id, client_id, prompt_name))
            if cur.fetchone():
                flash('Client ID and prompt name combination already exists', 'danger')
                cur.close()
                conn.close()
                return redirect(url_for('create_client'))
            cur.execute(
                "INSERT INTO settings (user_id, client_id, prompt, prompt_name) VALUES (%s, %s, %s, %s)",
                (current_user.id, client_id, Json({'prompt': prompt_content}), prompt_name)
            )
            conn.commit()
            cur.close()
            conn.close()
            session['selected_client'] = client_id
            session['selected_prompt'] = prompt_name
            flash(f'Client {client_id} created successfully', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Error creating client: {str(e)}")
            flash('Failed to create client', 'danger')
            return redirect(url_for('create_client'))
    return render_template('create_client.html')

@app.route('/load_prompts', methods=['POST'])
@login_required
def load_prompts():
    try:
        client_id = request.form.get('client_id')
        if not client_id:
            return jsonify({'error': 'Client ID cannot be empty'}), 400
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT prompt_name, prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND client_id = %s AND prompt IS NOT NULL",
            (current_user.id, client_id)
        )
        prompts = [{'prompt_name': row[0], 'prompt_content': row[1]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"Loaded prompts for client {client_id}: {prompts}")
        return jsonify({'prompts': prompts}), 200
    except Exception as e:
        print(f"Error loading prompts: {str(e)}")
        return jsonify({'error': 'Failed to load prompts'}), 500

@app.route('/load_client', methods=['POST'])
@login_required
def load_client():
    try:
        data = request.form
        client_id = data.get('client_id')
        prompt_name = data.get('prompt_name')
        if not client_id:
            return jsonify({'error': 'Client ID cannot be empty'}), 400
        prompt = load_ai_prompt(client_id, current_user.id, prompt_name)
        return jsonify({'prompt': prompt, 'prompt_name': prompt_name}), 200
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
        prompt_name = data.get('prompt_name', 'Default Prompt').strip()
        if not new_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400
        if not prompt_name:
            return jsonify({'error': 'Prompt name cannot be empty'}), 400
        save_ai_prompt(new_prompt, client_id, current_user.id, prompt_name)
        session['selected_prompt'] = prompt_name
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
        prompt_name = request.form.get('prompt_name', 'Default Prompt')
        save_template(file, client_id, current_user.id, prompt_name)
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
        prompt_name = request.form.get('prompt_name')
        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)
        content = extract_content_from_docx(input_path)
        sections = call_ai_api(content, client_id, current_user.id, prompt_name)
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