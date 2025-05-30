from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients

prompt_bp = Blueprint('prompt', __name__)

@prompt_bp.route('/create_prompt', methods=['GET', 'POST'])
@login_required
def create_prompt():
    clients = get_user_clients(current_user.id)
    selected_client = request.args.get('client_id', '')
    edit_prompt = request.args.get('edit_prompt', '')
    edit_type = request.args.get('prompt_type', 'conversion')
    prompts = []

    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '').strip()
        prompt_name = request.form.get('prompt_name', '').strip()
        prompt_type = request.form.get('prompt_type', 'conversion')
        content = request.form.get('content', '').strip()
        original_prompt_name = request.form.get('original_prompt_name', prompt_name).strip()
        original_prompt_type = request.form.get('original_prompt_type', prompt_type)

        if action == 'create':
            if not prompt_name:
                flash('Prompt name cannot be empty', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            if not content:
                flash('Prompt content cannot be empty', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                client_id_value = None
                if client_id:
                    cur.execute("SELECT id FROM clients WHERE user_id = %s AND client_id = %s", (current_user.id, client_id))
                    client = cur.fetchone()
                    if not client:
                        flash(f'Client "{client_id}" not found', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('prompt.create_prompt', client_id=client_id))
                    client_id_value = client[0]
                cur.execute(
                    "SELECT id FROM prompts WHERE user_id = %s AND (client_id = %s OR %s IS NULL AND client_id IS NULL) AND prompt_name = %s AND prompt_type = %s",
                    (current_user.id, client_id_value, client_id_value, prompt_name, prompt_type)
                )
                if cur.fetchone():
                    flash(f'Prompt "{prompt_name}" of type "{prompt_type}" already exists', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('prompt.create_prompt', client_id=client_id))
                cur.execute(
                    "INSERT INTO prompts (user_id, client_id, prompt_name, prompt_type, content) VALUES (%s, %s, %s, %s, %s)",
                    (current_user.id, client_id_value, prompt_name, prompt_type, content)
                )
                conn.commit()
                flash(f'Prompt "{prompt_name}" created successfully', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            except Exception as e:
                flash(f'Failed to create prompt: {str(e)}', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))

        elif action == 'update':
            if not prompt_name:
                flash('Prompt name cannot be empty', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            if not content:
                flash('Prompt content cannot be empty', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                client_id_value = None
                if client_id:
                    cur.execute("SELECT id FROM clients WHERE user_id = %s AND client_id = %s", (current_user.id, client_id))
                    client = cur.fetchone()
                    if client:
                        client_id_value = client[0]
                if prompt_name != original_prompt_name or prompt_type != original_prompt_type:
                    cur.execute(
                        "SELECT id FROM prompts WHERE user_id = %s AND (client_id = %s OR %s IS NULL AND client_id IS NULL) AND prompt_name = %s AND prompt_type = %s",
                        (current_user.id, client_id_value, client_id_value, prompt_name, prompt_type)
                    )
                    if cur.fetchone():
                        flash(f'Prompt "{prompt_name}" of type "{prompt_type}" already exists', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('prompt.create_prompt', client_id=client_id))
                cur.execute(
                    "UPDATE prompts SET prompt_name = %s, prompt_type = %s, content = %s "
                    "WHERE user_id = %s AND (client_id = %s OR %s IS NULL AND client_id IS NULL) AND prompt_name = %s AND prompt_type = %s",
                    (prompt_name, prompt_type, content, current_user.id, client_id_value, client_id_value, original_prompt_name, original_prompt_type)
                )
                if cur.rowcount == 0:
                    flash(f'Prompt "{original_prompt_name}" not found for update', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('prompt.create_prompt', client_id=client_id))
                conn.commit()
                cur.close()
                conn.close()
                flash(f'Prompt "{prompt_name}" updated successfully', 'success')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))
            except Exception as e:
                flash(f'Failed to update prompt: {str(e)}', 'danger')
                return redirect(url_for('prompt.create_prompt', client_id=client_id))

    conn = get_db_connection()
    cur = conn.cursor()
    if selected_client:
        cur.execute(
            "SELECT p.id, p.prompt_name, p.prompt_type, p.content "
            "FROM prompts p LEFT JOIN clients c ON p.client_id = c.id "
            "WHERE p.user_id = %s AND (c.client_id = %s OR p.client_id IS NULL)",
            (current_user.id, selected_client)
        )
    else:
        cur.execute(
            "SELECT id, prompt_name, prompt_type, content FROM prompts WHERE user_id = %s AND client_id IS NULL",
            (current_user.id,)
        )
    prompts = [{'id': row[0], 'prompt_name': row[1], 'prompt_type': row[2], 'content': row[3]} for row in cur.fetchall()]
    cur.close()
    conn.close()

    return render_template('create_prompt.html', clients=clients, selected_client=selected_client, prompts=prompts, selected_prompt=edit_prompt, selected_prompt_type=edit_type)