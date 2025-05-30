import sys
import os
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

project_root = os.path.abspath(os.path.dirname(__file__))
logger.debug(f"Project root: {project_root}")
logger.debug(f"sys.path before: {sys.path}")
sys.path.insert(0, project_root)
logger.debug(f"sys.path after: {sys.path}")

try:
    from app import create_app
    logger.debug("Successfully imported create_app")
except ImportError as e:
    logger.error(f"Failed to import create_app: {str(e)}")
    raise

app = create_app()

if __name__ == '__main__':
    logger.debug("Starting Flask app")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))