from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients, get_templates_for_client, get_conversion_prompts_for_client
from ..utils.document import process_docx, process_text_input
from ..utils.conversion import convert_content
from ..utils.docx_builder import create_reformatted_docx
from tempfile import TemporaryDirectory
import json

main_bp = Blueprint('main', __name__)

@main_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    clients = get_user_clients(current_user.id)
    selected_client = session.get('selected_client', '')
    selected_template = session.get('selected_template', '')
    template_prompt = session.get('template_prompt', '')
    conversion_prompt = session.get('conversion_prompt', '')
    converted_content = session.get('converted_content', None)

    templates = get_templates_for_client(selected_client, current_user.id)
    conversion_prompts = get_conversion_prompts_for_client(selected_client, current_user.id)

    if request.method == 'POST':
        action = request.form.get('action')
        selected_client = request.form.get('client', '').strip()
        selected_template = request.form.get('template', '').strip()
        template_prompt = request.form.get('template_prompt', '').strip()
        conversion_prompt = request.form.get('conversion_prompt', '').strip()
        source_file = request.files.get('source_file')
        source_text = request.form.get('source_text', '').strip()

        session['selected_client'] = selected_client
        session['selected_template'] = selected_template
        session['template_prompt'] = template_prompt
        session['conversion_prompt'] = conversion_prompt

        if action == 'convert':
            if not selected_template:
                flash('Template is required', 'danger')
                return redirect(url_for('main.index'))
            if not template_prompt:
                flash('Template prompt is required', 'danger')
                return redirect(url_for('main.index'))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                client_id_value = None
                if selected_client:
                    cur.execute("SELECT id FROM clients WHERE user_id = %s AND client_id = %s", (current_user.id, selected_client))
                    client = cur.fetchone()
                    if client:
                        client_id_value = client[0]
                cur.execute(
                    "SELECT template_file "
                    "FROM templates t "
                    "WHERE t.user_id = %s AND (t.client_id = %s OR %s IS NULL AND t.client_id IS NULL) AND t.id = %s",
                    (current_user.id, client_id_value, client_id_value, int(selected_template))
                )
                template = cur.fetchone()
                cur.close()
                conn.close()
                if not template:
                    flash('Template not found', 'danger')
                    return redirect(url_for('main.index'))

                template_file = template[0]
                with TemporaryDirectory() as temp_dir:
                    temp_template_path = os.path.join(temp_dir, 'template.docx')
                    if template_file:
                        with open(temp_template_path, 'wb') as f:
                            f.write(template_file)
                    content = process_docx(source_file) if source_file and source_file.filename.endswith('.docx') else process_text_input(source_text)
                    converted_content = convert_content(content, template_prompt, conversion_prompt)
                    session['converted_content'] = converted_content
                    output_path = os.path.join(temp_dir, 'reformatted_document.docx')
                    create_reformatted_docx(converted_content, output_path, temp_template_path)
                    return send_file(output_path, as_attachment=True, download_name='reformatted_document.docx')
            except Exception as e:
                flash(f'Error processing document: {str(e)}', 'error')
                return redirect(url_for('main.index'))

        elif action == 'accept':
            session.pop('selected_client', None)
            session.pop('selected_template', None)
            session.pop('template_prompt', None)
            session.pop('conversion_prompt', None)
            session.pop('converted_content', None)
            flash('Conversion accepted', 'success')
            return redirect(url_for('main.index'))

        elif action == 'make_changes':
            return render_template(
                'index.html',
                clients=clients,
                templates=templates,
                conversion_prompts=conversion_prompts,
                selected_client=selected_client,
                selected_template=selected_template,
                template_prompt=template_prompt,
                conversion_prompt=conversion_prompt,
                converted_content=converted_content
            )

    return render_template(
        'index.html',
        clients=clients,
        templates=templates,
        conversion_prompts=conversion_prompts,
        selected_client=selected_client,
        selected_template=selected_template,
        template_prompt=template_prompt,
        conversion_prompt=conversion_prompt,
        converted_content=converted_content
    )