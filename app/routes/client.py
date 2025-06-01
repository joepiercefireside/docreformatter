from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients, get_templates_for_client, get_conversion_prompts_for_client

client_bp = Blueprint('client', __name__)

@client_bp.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    clients = get_user_clients(current_user.id)
    selected_client = request.form.get('selected_client', '') if request.method == 'POST' else request.args.get('selected_client', '')
    templates = []
    prompts = []
    client_details = {'client_id': '', 'client_name': '', 'prompt_name': '', 'prompt_content': ''}

    # Fetch client details if a client is selected
    if selected_client:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetch client details
        cur.execute(
            "SELECT client_id, name FROM clients WHERE user_id = %s AND client_id = %s",
            (current_user.id, selected_client)
        )
        client = cur.fetchone()
        if client:
            client_details['client_id'] = client[0]
            client_details['client_name'] = client[1]

        # Fetch initial prompt (template type) for the client
        cur.execute(
            "SELECT prompt_name, content FROM prompts WHERE user_id = %s AND client_id = (SELECT id FROM clients WHERE user_id = %s AND client_id = %s) AND prompt_type = 'template'",
            (current_user.id, current_user.id, selected_client)
        )
        initial_prompt = cur.fetchone()
        if initial_prompt:
            client_details['prompt_name'] = initial_prompt[0]
            client_details['prompt_content'] = initial_prompt[1]

        # Fetch templates and prompts
        templates = get_templates_for_client(selected_client, current_user.id)
        # Fetch all prompts (template and conversion)
        cur.execute(
            "SELECT id, prompt_name, prompt_type, content "
            "FROM prompts p LEFT JOIN clients c ON p.client_id = c.id "
            "WHERE p.user_id = %s AND (c.client_id = %s OR p.client_id IS NULL)",
            (current_user.id, selected_client)
        )
        prompts = [{'id': row[0], 'prompt_name': row[1], 'prompt_type': row[2], 'content': row[3]} for row in cur.fetchall()]
        cur.close()
        conn.close()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            client_id = request.form.get('client_id', '').strip()
            client_name = request.form.get('client_name', '').strip()
            prompt_name = request.form.get('prompt_name', '').strip()
            prompt_content = request.form.get('prompt_content', '').strip()

            if not client_id or not client_name:
                flash('Client ID and Name are required', 'danger')
                return redirect(url_for('client.create_client', selected_client=selected_client))

            try:
                conn = get_db_connection()
                cur = conn.cursor()

                # Check if client_id already exists
                cur.execute(
                    "SELECT id FROM clients WHERE user_id = %s AND client_id = %s",
                    (current_user.id, client_id)
                )
                if cur.fetchone():
                    flash(f'Client ID "{client_id}" already exists', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('client.create_client', selected_client=selected_client))

                # Insert new client
                cur.execute(
                    "INSERT INTO clients (user_id, client_id, name) VALUES (%s, %s, %s) RETURNING id",
                    (current_user.id, client_id, client_name)
                )
                client_db_id = cur.fetchone()[0]

                # If prompt_name and prompt_content are provided, create a default prompt
                if prompt_name and prompt_content:
                    cur.execute(
                        "SELECT id FROM prompts WHERE user_id = %s AND client_id = %s AND prompt_name = %s",
                        (current_user.id, client_db_id, prompt_name)
                    )
                    if cur.fetchone():
                        flash(f'Prompt name "{prompt_name}" already exists for this client', 'danger')
                        cur.close()
                        conn.close()
                        return redirect(url_for('client.create_client', selected_client=selected_client))

                    cur.execute(
                        "INSERT INTO prompts (user_id, client_id, prompt_name, prompt_type, content) "
                        "VALUES (%s, %s, %s, 'template', %s)",
                        (current_user.id, client_db_id, prompt_name, prompt_content)
                    )

                conn.commit()
                flash(f'Client "{client_name}" created successfully', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('client.create_client', selected_client=client_id))
            except Exception as e:
                flash(f'Failed to create client: {str(e)}', 'danger')
                return redirect(url_for('client.create_client', selected_client=selected_client))

        elif action == 'update':
            client_id = request.form.get('client_id', '').strip()
            client_name = request.form.get('client_name', '').strip()
            prompt_name = request.form.get('prompt_name', '').strip()
            prompt_content = request.form.get('prompt_content', '').strip()

            if not client_id or not client_name:
                flash('Client ID and Name are required', 'danger')
                return redirect(url_for('client.create_client', selected_client=selected_client))

            try:
                conn = get_db_connection()
                cur = conn.cursor()

                # Check if client exists
                cur.execute(
                    "SELECT id FROM clients WHERE user_id = %s AND client_id = %s",
                    (current_user.id, selected_client)
                )
                client = cur.fetchone()
                if not client:
                    flash(f'Client "{selected_client}" not found', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('client.create_client', selected_client=selected_client))

                client_db_id = client[0]

                # Update client details
                cur.execute(
                    "UPDATE clients SET client_id = %s, name = %s WHERE id = %s AND user_id = %s",
                    (client_id, client_name, client_db_id, current_user.id)
                )

                # Update or create initial prompt
                if prompt_name and prompt_content:
                    cur.execute(
                        "SELECT id FROM prompts WHERE user_id = %s AND client_id = %s AND prompt_type = 'template'",
                        (current_user.id, client_db_id)
                    )
                    existing_prompt = cur.fetchone()
                    if existing_prompt:
                        # Update existing prompt
                        cur.execute(
                            "UPDATE prompts SET prompt_name = %s, content = %s WHERE id = %s",
                            (prompt_name, prompt_content, existing_prompt[0])
                        )
                    else:
                        # Create new prompt
                        cur.execute(
                            "INSERT INTO prompts (user_id, client_id, prompt_name, prompt_type, content) "
                            "VALUES (%s, %s, %s, 'template', %s)",
                            (current_user.id, client_db_id, prompt_name, prompt_content)
                        )

                conn.commit()
                flash(f'Client "{client_name}" updated successfully', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('client.create_client', selected_client=client_id))
            except Exception as e:
                flash(f'Failed to update client: {str(e)}', 'danger')
                return redirect(url_for('client.create_client', selected_client=selected_client))

    return render_template('create_client.html', clients=clients, selected_client=selected_client, templates=templates, prompts=prompts, client_details=client_details)

@client_bp.route('/delete_client/<client_id>', methods=['POST'])
@login_required
def delete_client(client_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM clients WHERE user_id = %s AND client_id = %s",
            (current_user.id, client_id)
        )
        if cur.rowcount == 0:
            flash(f'Client "{client_id}" not found', 'danger')
        else:
            flash(f'Client "{client_id}" deleted successfully', 'success')
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'Failed to delete client: {str(e)}', 'danger')
    return redirect(url_for('client.create_client'))