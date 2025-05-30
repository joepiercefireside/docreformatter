from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..utils.database import get_db_connection, get_user_clients

client_bp = Blueprint('client', __name__)

@client_bp.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    clients = get_user_clients(current_user.id)
    selected_client = request.args.get('selected_client', '')

    if request.method == 'POST':
        action = request.form.get('action')
        client_id = request.form.get('client_id', '').strip()
        name = request.form.get('name', '').strip()

        if action == 'create':
            if not client_id:
                flash('Client ID cannot be empty', 'danger')
                return redirect(url_for('client.create_client'))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM clients WHERE user_id = %s AND client_id = %s",
                    (current_user.id, client_id)
                )
                if cur.fetchone():
                    flash(f'Client "{client_id}" already exists', 'danger')
                    cur.close()
                    conn.close()
                    return redirect(url_for('client.create_client'))
                cur.execute(
                    "INSERT INTO clients (user_id, client_id, name) VALUES (%s, %s, %s)",
                    (current_user.id, client_id, name or client_id)
                )
                conn.commit()
                cur.close()
                conn.close()
                flash(f'Client {client_id} created successfully', 'success')
                return redirect(url_for('client.create_client', selected_client=client_id))
            except Exception as e:
                flash(f'Failed to create client: {str(e)}', 'danger')
                return redirect(url_for('client.create_client'))

    return render_template('create_client.html', clients=clients, selected_client=selected_client)