from flask import Flask
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
import os
import logging
from .utils import init_db
from .routes.auth import auth_bp
from .routes.client import client_bp
from .routes.prompt import prompt_bp
from .routes.template import template_bp
from .routes.main import main_bp
from .models.user import load_user  # Added import

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__, template_folder='../../templates', static_folder='../../static')
    app.config['UPLOAD_FOLDER'] = '/tmp'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

    logger.debug("Initializing Flask app with static_folder=../../static")

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.user_loader(load_user)  # Register user_loader

    oauth = OAuth(app)
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    with app.app_context():
        init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(prompt_bp)
    app.register_blueprint(template_bp)
    app.register_blueprint(main_bp)

    return app