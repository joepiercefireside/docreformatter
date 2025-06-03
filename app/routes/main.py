from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients, get_templates_for_client, get_conversion_prompts_for_client
from ..utils.document import process_docx, process_text_input
from ..utils.conversion import convert_content
from ..utils.docx_builder import create_reformatted_docx
import json
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

@main_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    clients = get_user_clients(current_user.id)
    selected_client = request.args.get('client_id', '') if request.method == 'GET' else request.form.get('client', '')
    templates = get_templates_for_client(selected_client, current_user.id)
    conversion_prompts = get_conversion_prompts_for_client(selected_client, current_user.id)

    template_prompt = ''
    conversion_prompt = ''
    selected_template = ''
    conversion_prompt_id = ''

    # Filter templates and conversion prompts for the selected client
    filtered_templates = [
        template for template in templates
        if (selected_client and (template['client_id'] is None or template['client_id'] == selected_client)) or
           (not selected_client and template['client_id'] is None)
    ]
    filtered_conversion_prompts = [
        prompt for prompt in conversion_prompts
        if (selected_client and (prompt['client_id'] is None or prompt['client_id'] == selected_client)) or
           (not selected_client and prompt['client_id'] is None)
    ]

    if request.method == 'POST':
        action = request.form.get('action')
        selected_template = request.form.get('template', '')
        template_prompt = request.form.get('template_prompt', '')
        conversion_prompt = request.form.get('conversion_prompt', '')
        conversion_prompt_id = request.form.get('conversion_prompt_id', '')

        if action == 'select_client':
            return redirect(url_for('main.index', client_id=selected_client))

        elif action == 'convert':
            if not selected_template:
                flash('Please select a template', 'danger')
                return redirect(url_for('main.index', client_id=selected_client))
            if not template_prompt:
                flash('Template prompt is required', 'danger')
                return redirect(url_for('main.index', client_id=selected_client))

            try:
                # Get template file for styling
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT template_file FROM templates WHERE id = %s AND user_id = %s",
                    (selected_template, current_user.id)
                )
                template_file = cur.fetchone()[0]
                cur.close()
                conn.close()

                if not template_file:
                    flash('Template file not found. Please ensure the selected template has an associated file.', 'danger')
                    return redirect(url_for('main.index', client_id=selected_client))

                logger.info(f"Using template file for template ID {selected_template} (length: {len(template_file)} bytes)")

                # Process source content
                source_file = request.files.get('source_file')
                if source_file and source_file.filename.endswith('.docx'):
                    content = process_docx(source_file)
                else:
                    flash('Please upload a valid .docx file', 'danger')
                    return redirect(url_for('main.index', client_id=selected_client))

                # Step 1: Semantic structuring with LLM
                converted_content = convert_content(content, template_prompt, conversion_prompt)

                # Step 2: Apply styles with python-docx
                output_file = create_reformatted_docx(converted_content, template_file)

                # Return the file for immediate download
                return Response(
                    output_file,
                    mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    headers={'Content-Disposition': 'attachment; filename=reformatted_document.docx'}
                )
            except Exception as e:
                flash(str(e), 'danger')
                return redirect(url_for('main.index', client_id=selected_client))

    return render_template(
        'index.html',
        clients=clients,
        selected_client=selected_client,
        templates=filtered_templates,
        conversion_prompts=filtered_conversion_prompts,
        template_prompt=template_prompt,
        conversion_prompt=conversion_prompt,
        selected_template=selected_template,
        conversion_prompt_id=conversion_prompt_id
    )

@main_bp.route('/load_client', methods=['POST'])
def load_client():
    client_id = request.form.get('client_id', '')
    template_id = request.form.get('template_id', '')
    prompt_id = request.form.get('prompt_id', '')

    if template_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT p.content AS template_prompt, cp.content AS conversion_prompt "
            "FROM templates t "
            "JOIN prompts p ON t.template_prompt_id = p.id "
            "LEFT JOIN template_prompt_associations tpa ON t.id = tpa.template_id "
            "LEFT JOIN prompts cp ON tpa.conversion_prompt_id = cp.id "
            "WHERE t.id = %s AND t.user_id = %s",
            (template_id, current_user.id)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result:
            return {'prompt': result[0], 'conversion': result[1] if result[1] else ''}
        return {'prompt': '', 'conversion': ''}

    if prompt_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM prompts WHERE id = %s AND user_id = %s",
            (prompt_id, current_user.id)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result:
            return {'prompt': result[0]}
        return {'prompt': ''}

    return {'prompt': '', 'conversion': ''}