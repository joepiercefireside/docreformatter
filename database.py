import os
import psycopg2
from psycopg2.extras import Json

# Database setup
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

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
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                client_id VARCHAR(50) NOT NULL,
                prompt JSONB,
                prompt_name VARCHAR(255) NOT NULL,
                template BYTEA,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, client_id, prompt_name)
            );
            CREATE INDEX IF NOT EXISTS idx_client_id ON settings(client_id);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Initialized database schema")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        raise

DEFAULT_AI_PROMPT = """You are a medical document analyst. Analyze the provided document content and categorize it into the following sections based on the input text and tables:
- Summary: A concise overview of the drug, its purpose, and key findings.
- Background: Context about the disease or condition the drug treats.
- Monograph: Official prescribing information, usage guidelines, or clinical details.
- Real-World Experiences: Patient or clinician experiences, if present (else empty).
- Enclosures: Descriptions of supporting documents, posters, or additional materials.
- Tables: Assign tables to appropriate sections (e.g., 'Patient Demographics', 'Adverse Events') based on their content.
Return a JSON object with these keys and the corresponding content extracted or rewritten from the input. Preserve references separately. Ensure the response is valid JSON. For tables, return a dictionary where keys are descriptive section names and values are lists of rows, each row being a list of cell values. Focus on accurately interpreting and summarizing the source material, avoiding any formatting instructions."""

def load_ai_prompt(client_id=None, user_id=None, prompt_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id and user_id and prompt_name:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE client_id = %s AND user_id = %s AND prompt_name = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id, prompt_name)
            )
        elif client_id and user_id:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE client_id = %s AND user_id = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id)
            )
        else:
            cur.execute(
                "SELECT prompt->'prompt' AS prompt_content FROM settings WHERE user_id = %s AND prompt IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result and result[0] else DEFAULT_AI_PROMPT
    except Exception as e:
        print(f"Error loading AI prompt: {str(e)}")
        return DEFAULT_AI_PROMPT

def save_ai_prompt(prompt, client_id=None, user_id=None, prompt_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings (user_id, client_id, prompt, prompt_name) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, client_id, prompt_name) DO UPDATE SET prompt = EXCLUDED.prompt",
            (user_id, client_id, Json({'prompt': prompt}), prompt_name or 'Default Prompt')
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved AI prompt '{prompt_name}' for client {client_id}, user {user_id}: {prompt[:100]}...")
    except Exception as e:
        print(f"Error saving AI prompt: {str(e)}")
        raise

def save_template(file, client_id=None, user_id=None, prompt_name=None):
    try:
        file_data = file.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings (user_id, client_id, template, prompt_name) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, client_id, prompt_name) DO UPDATE SET template = EXCLUDED.template",
            (user_id, client_id, file_data, prompt_name or 'Default Prompt')
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved template for client {client_id}, user {user_id}, prompt {prompt_name}")
    except Exception as e:
        print(f"Error saving template: {str(e)}")
        raise

def load_template(output_path, client_id=None, user_id=None, prompt_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if client_id and user_id and prompt_name:
            cur.execute(
                "SELECT template FROM settings WHERE client_id = %s AND user_id = %s AND prompt_name = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id, prompt_name)
            )
        elif client_id and user_id:
            cur.execute(
                "SELECT template FROM settings WHERE client_id = %s AND user_id = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (client_id, user_id)
            )
        else:
            cur.execute(
                "SELECT template FROM settings WHERE user_id = %s AND template IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result and result[0]:
            with open(output_path, 'wb') as f:
                f.write(result[0])
            return True
        return False
    except Exception as e:
        print(f"Error loading template: {str(e)}")
        return False

def get_clients(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT client_id FROM settings WHERE user_id = %s AND client_id IS NOT NULL AND client_id != ''",
            (user_id,)
        )
        clients = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"Fetched clients for user {user_id}: {clients}")
        return clients
    except Exception as e:
        print(f"Error getting clients: {str(e)}")
        return []