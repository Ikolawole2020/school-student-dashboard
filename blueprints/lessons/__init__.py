# blueprints/lessons/__init__.py
from flask import Blueprint

lessons_bp = Blueprint(
    'lessons', __name__, template_folder='../../templates/lessons'
)

from . import routes
