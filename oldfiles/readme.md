Diligent Doc Reformatter
A Flask-based web application for reformatting medical documents using AI, with Google OAuth, client management, and customizable prompts/templates.

Features
Authentication: Email/password and Google OAuth login.
Client Management: Create and select clients to manage prompts and templates.
Prompt Management: Save, update, and select AI prompts for document analysis.
Document Processing: Upload .docx files, analyze with OpenAI API, and reformat using templates.
UI: Bootstrap 5 with Fireside Technologies blue (#005B99) and logo.
Project Structure
text

Copy
project_root/
├── app.py                  # Main Flask app and routes
├── auth.py                # Authentication routes and user model
├── database.py            # Database connection and utilities
├── document.py            # Document processing functions
├── static/
│   └── images/
│       ├── diligent_logo.png
│       ├── favicon.png
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── create_client.html
├── requirements.txt
├── README.md
Setup
Clone Repository:
bash

Copy
git clone https://git.heroku.com/diligentreformatter.git
cd diligentreformatter
Install Dependencies:
bash

Copy
pip install -r requirements.txt
Set Environment Variables:
bash

Copy
heroku config:set SECRET_KEY=<your-secret-key>
heroku config:set GOOGLE_CLIENT_ID=<your-google-client-id>
heroku config:set GOOGLE_CLIENT_SECRET=<your-google-client-secret>
heroku config:set DATABASE_URL=<your-postgres-url>
heroku config:set AI_API_URL=https://api.openai.com/v1/chat/completions
heroku config:set API_KEY=<your-openai-api-key>
Deploy to Heroku:
bash

Copy
git push heroku main
heroku open
Database Schema
users: Stores user data (id, email, password_hash, google_id, created_at).
settings: Stores client settings (id, user_id, client_id, prompt, prompt_name, template, created_at).
Usage
Log in with email (joepierce88@gmail.com) or Google OAuth.
Create a client (e.g., FiresideTestOne).
Manage prompts and upload templates/documents.
Download reformatted .docx files.
Development Notes
Version: v1.1 (tagged in Git, includes modularization and fixed document.py syntax error).
Modularization: Split app.py into auth.py, database.py, document.py for maintainability.
UI: Matches Fireside Technologies blue (#005B99) with logo in navbar.
Deployed on Heroku: https://diligentreformatter-cf11e263a6b8.herokuapp.com
Contact: joepierce88@gmail.com for support