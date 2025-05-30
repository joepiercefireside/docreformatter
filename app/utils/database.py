import psycopg2
from psycopg2.extras import Json
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255),
                google_id VARCHAR(255) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS clients (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                client_id VARCHAR(50) NOT NULL,
                name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT clients_unique_user_client UNIQUE (user_id, client_id)
            );
            CREATE TABLE IF NOT EXISTS prompts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
                prompt_name VARCHAR(255) NOT NULL,
                prompt_type VARCHAR(20) CHECK (prompt_type IN ('template', 'conversion')),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT prompts_unique_user_client_name_type UNIQUE (user_id, client_id, prompt_name, prompt_type)
            );
            CREATE TABLE IF NOT EXISTS templates (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
                template_name VARCHAR(255) NOT NULL,
                template_prompt_id INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
                template_file BYTEA,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT templates_unique_user_client_name UNIQUE (user_id, client_id, template_name)
            );
            CREATE TABLE IF NOT EXISTS template_prompt_associations (
                id SERIAL PRIMARY KEY,
                template_id INTEGER REFERENCES templates(id) ON DELETE CASCADE,
                conversion_prompt_id INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT template_prompt_unique UNIQUE (template_id, conversion_prompt_id)
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Initialized database schema")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise

def get_user_clients(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT client_id, name FROM clients WHERE user_id = %s",
            (user_id,)
        )
        clients = [{'client_id': row[0], 'name': row[1]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Fetched clients for user {user_id}: {clients}")
        return clients
    except Exception as e:
        logger.error(f"Error getting clients: {str(e)}")
        return []

def get_templates_for_client(client_id, user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        client_id_value = None
        if client_id:
            cur.execute("SELECT id FROM clients WHERE user_id = %s AND client_id = %s", (user_id, client_id))
            client = cur.fetchone()
            if client:
                client_id_value = client[0]
        cur.execute(
            "SELECT t.id, t.template_name, p.id, p.prompt_name, p.content, tpa.conversion_prompt_id, cp.prompt_name, cp.content, t.template_file IS NOT NULL "
            "FROM templates t "
            "LEFT JOIN prompts p ON t.template_prompt_id = p.id "
            "LEFT JOIN template_prompt_associations tpa ON t.id = tpa.template_id "
            "LEFT JOIN prompts cp ON tpa.conversion_prompt_id = cp.id "
            "WHERE t.user_id = %s AND (t.client_id = %s OR %s IS NULL AND t.client_id IS NULL)",
            (user_id, client_id_value, client_id_value)
        )
        templates = [
            {
                'id': row[0],
                'template_name': row[1],
                'template_prompt_id': row[2],
                'template_prompt_name': row[3],
                'template_prompt_content': row[4],
                'conversion_prompt_id': row[5],
                'conversion_prompt_name': row[6],
                'conversion_prompt_content': row[7],
                'has_file': row[8]
            } for row in cur.fetchall()
        ]
        cur.close()
        conn.close()
        logger.info(f"Fetched templates for client {client_id or 'global'}, user {user_id}: {templates}")
        return templates
    except Exception as e:
        logger.error(f"Error getting templates: {str(e)}")
        return []

def get_conversion_prompts_for_client(client_id, user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        client_id_value = None
        if client_id:
            cur.execute("SELECT id FROM clients WHERE user_id = %s AND client_id = %s", (user_id, client_id))
            client = cur.fetchone()
            if client:
                client_id_value = client[0]
        cur.execute(
            "SELECT id, prompt_name, content "
            "FROM prompts "
            "WHERE user_id = %s AND (client_id = %s OR %s IS NULL AND client_id IS NULL) AND prompt_type = 'conversion'",
            (user_id, client_id_value, client_id_value)
        )
        prompts = [{'id': row[0], 'prompt_name': row[1], 'content': row[2]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Fetched conversion prompts for client {client_id or 'global'}, user {user_id}: {prompts}")
        return prompts
    except Exception as e:
        logger.error(f"Error getting conversion prompts: {str(e)}")
        return []