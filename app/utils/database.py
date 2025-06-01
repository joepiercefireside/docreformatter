import psycopg2
from psycopg2 import sql
import logging
import os
from flask_login import current_user

logger = logging.getLogger(__name__)

def get_db_connection():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database: {str(e)}")
        raise

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255),
            google_id VARCHAR(255) UNIQUE
        );
    """)
    
    # Create clients table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            UNIQUE(user_id, client_id)
        );
    """)
    
    # Create prompts table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            prompt_name VARCHAR(255) NOT NULL,
            prompt_type VARCHAR(50) NOT NULL CHECK (prompt_type IN ('template', 'conversion')),
            content TEXT NOT NULL,
            UNIQUE(user_id, client_id, prompt_name)
        );
    """)
    
    # Create templates table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            template_name VARCHAR(255) NOT NULL,
            template_prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE RESTRICT,
            template_file BYTEA,
            UNIQUE(user_id, client_id, template_name)
        );
    """)
    
    # Create template_prompt_associations table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS template_prompt_associations (
            template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            conversion_prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE RESTRICT,
            PRIMARY KEY (template_id, conversion_prompt_id)
        );
    """)
    
    conn.commit()
    logger.info("Initialized database schema")
    cur.close()
    conn.close()

def get_user_clients(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT client_id, name FROM clients WHERE user_id = %s", (user_id,))
    clients = [{'client_id': row[0], 'name': row[1]} for row in cur.fetchall()]
    cur.close()
    conn.close()
    logger.info(f"Fetched clients for user {user_id}: {clients}")
    return clients

def get_templates_for_client(client_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    if client_id:
        cur.execute("""
            SELECT t.id, t.template_name, p.prompt_name AS template_prompt_name, p.content AS template_prompt_content, 
                   cp.prompt_name AS conversion_prompt_name, cp.content AS conversion_prompt_content, 
                   t.template_file IS NOT NULL AS has_file, t.template_prompt_id, tpa.conversion_prompt_id
            FROM templates t
            JOIN prompts p ON t.template_prompt_id = p.id
            LEFT JOIN template_prompt_associations tpa ON t.id = tpa.template_id
            LEFT JOIN prompts cp ON tpa.conversion_prompt_id = cp.id
            JOIN clients c ON t.client_id = c.id
            WHERE t.user_id = %s AND (c.client_id = %s OR t.client_id IS NULL);
        """, (user_id, client_id))
    else:
        cur.execute("""
            SELECT t.id, t.template_name, p.prompt_name AS template_prompt_name, p.content AS template_prompt_content, 
                   cp.prompt_name AS conversion_prompt_name, cp.content AS conversion_prompt_content, 
                   t.template_file IS NOT NULL AS has_file, t.template_prompt_id, tpa.conversion_prompt_id
            FROM templates t
            JOIN prompts p ON t.template_prompt_id = p.id
            LEFT JOIN template_prompt_associations tpa ON t.id = tpa.template_id
            LEFT JOIN prompts cp ON tpa.conversion_prompt_id = cp.id
            WHERE t.user_id = %s AND t.client_id IS NULL;
        """, (user_id,))
    templates = [
        {
            'id': row[0],
            'template_name': row[1],
            'template_prompt_name': row[2],
            'template_prompt_content': row[3],
            'conversion_prompt_name': row[4],
            'conversion_prompt_content': row[5],
            'has_file': row[6],
            'template_prompt_id': row[7],
            'conversion_prompt_id': row[8]
        } for row in cur.fetchall()
    ]
    cur.close()
    conn.close()
    logger.info(f"Fetched templates for client {client_id}, user {user_id}: {[t['template_name'] for t in templates]}")
    return templates

def get_conversion_prompts_for_client(client_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    if client_id:
        cur.execute("""
            SELECT p.id, p.prompt_name, p.content
            FROM prompts p
            JOIN clients c ON p.client_id = c.id
            WHERE p.user_id = %s AND (c.client_id = %s OR p.client_id IS NULL) AND p.prompt_type = 'conversion';
        """, (user_id, client_id))
    else:
        cur.execute("""
            SELECT p.id, p.prompt_name, p.content
            FROM prompts p
            WHERE p.user_id = %s AND p.client_id IS NULL AND p.prompt_type = 'conversion';
        """, (user_id,))
    prompts = [{'id': row[0], 'prompt_name': row[1], 'content': row[2]} for row in cur.fetchall()]
    cur.close()
    conn.close()
    logger.info(f"Fetched conversion prompts for client {client_id}, user {user_id}: {[p['prompt_name'] for p in prompts]}")
    return prompts