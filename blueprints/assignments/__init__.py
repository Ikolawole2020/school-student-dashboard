# blueprints/assignments/__init__.py
from flask import Blueprint

assignments_bp = Blueprint(
    'assignments', __name__, template_folder='../../templates/assignments'
)

from . import routes
