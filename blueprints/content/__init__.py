# blueprints/content/__init__.py
from flask import Blueprint

content_bp = Blueprint(
    'content', __name__, template_folder='../../templates/content'
)

from . import routes
