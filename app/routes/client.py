from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients

client_bp = Blueprint('client', __name__)

@client_bp.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    clients = get_user_clients(current_user.id)

    if request.method == 'POST':
        client_id = request.form.get('client_id', '').strip()
        client_name = request.form.get('client_name', '').strip()
        prompt_name = request.form.get('prompt_name', '').strip()
        prompt_content = request.form.get('prompt_content', '').strip()

        if not client_id or not client_name:
            flash('Client ID and Name are required', 'danger')
            return redirect(url_for('client.create_client'))

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
                return redirect(url_for('client.create_client'))

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
                    return redirect(url_for('client.create_client'))

                cur.execute(
                    "INSERT INTO prompts (user_id, client_id, prompt_name, prompt_type, content) "
                    "VALUES (%s, %s, %s, 'template', %s)",
                    (current_user.id, client_db_id, prompt_name, prompt_content)
                )

            conn.commit()
            flash(f'Client "{client_name}" created successfully', 'success')
            cur.close()
            conn.close()
            return redirect(url_for('main.index'))
        except Exception as e:
            flash(f'Failed to create client: {str(e)}', 'danger')
            return redirect(url_for('client.create_client'))

    return render_template('create_client.html', clients=clients)