# ... (previous app.py content up to @app.route('/upload') ...)
@app.route('/create_client', methods=['GET', 'POST'])
@login_required
def create_client():
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id').strip()
            if not client_id:
                flash('Client ID cannot be empty')
                return redirect(url_for('create_client'))
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM settings WHERE user_id = %s AND client_id = %s", (current_user.id, client_id))
            if cur.fetchone():
                flash('Client ID already exists')
                cur.close()
                conn.close()
                return redirect(url_for('create_client'))
            cur.execute("INSERT INTO settings (user_id, client_id, prompt) VALUES (%s, %s, %s)", 
                       (current_user.id, client_id, Json({'prompt': DEFAULT_AI_PROMPT})))
            conn.commit()
            cur.close()
            conn.close()
            flash('Client created successfully')
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Error creating client: {str(e)}")
            flash('Failed to create client')
            return redirect(url_for('create_client'))
    return render_template('create_client.html')
# ... (rest of app.py from if __name__ == '__main__': ...)