# utils.py
"""Shared helpers used across blueprints."""
import os
import secrets
import string

from flask import current_app
from flask_login import current_user
from werkzeug.utils import secure_filename

from extensions import db


# ------------------------------------------------------------------ uploads

def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[-1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    )


def save_upload(file_storage, prefix=''):
    """Validate and store an uploaded image. Returns the stored filename or None.

    Guards against two problems the old inline code had:
      * a rejected file still produced a filename, so the record pointed at
        a file that was never written;
      * the extension was the only check, so a script renamed to .png passed.
    """
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None

    ext = file_storage.filename.rsplit('.', 1)[-1].lower()
    # random component stops two students uploading "photo.png" from
    # overwriting each other's file
    token = secrets.token_hex(6)
    filename = secure_filename(f"{prefix}_{token}.{ext}" if prefix else f"{token}.{ext}")
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file_storage.save(path)
    return filename


def delete_upload(filename):
    """Best-effort removal of a previously stored upload."""
    if not filename:
        return
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], secure_filename(filename))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# -------------------------------------------------------------- role guards

def is_admin():
    return current_user.is_authenticated and current_user.role == 'admin'


def is_teacher():
    return current_user.is_authenticated and current_user.role == 'teacher'


def is_staff():
    """Admin or teacher - used for pages both roles may reach."""
    return is_admin() or is_teacher()


def current_teacher():
    """The Teacher row for the logged-in teacher, or None."""
    if not is_teacher():
        return None
    from models import Teacher
    return Teacher.query.filter_by(user_id=current_user.id).first()


def current_student():
    """The Student row for the logged-in student, or None."""
    if not current_user.is_authenticated:
        return None
    from models import Student
    return Student.query.filter_by(user_id=current_user.id).first()


# -------------------------------------------------------------- id generation

def slugify_name(name):
    """Lowercase, alphanumeric identifier derived from a person's name."""
    cleaned = ''.join(c.lower() for c in (name or '').strip() if c.isalnum() or c.isspace())
    return cleaned.replace(' ', '')


def unique_staff_id(name):
    """Derive a staff ID from the name, appending a number if it is taken."""
    from models import Teacher
    base = slugify_name(name) or 'staff'
    candidate = base
    counter = 1
    while Teacher.query.filter_by(staff_id=candidate).first():
        counter += 1
        candidate = f'{base}{counter}'
    return candidate


def unique_email(name, domain='smc.com'):
    """Derive an email from the name, appending a number if it is taken."""
    from models import User
    base = slugify_name(name) or 'user'
    candidate = f'{base}@{domain}'
    counter = 1
    while User.query.filter_by(email=candidate).first():
        counter += 1
        candidate = f'{base}{counter}@{domain}'
    return candidate


def generate_password(length=10):
    """Readable random password that satisfies the 6-char minimum."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def grade_for(percentage):
    """Grade band used for both exam results and assignment scores."""
    if percentage >= 70:
        return 'A'
    if percentage >= 60:
        return 'B'
    if percentage >= 50:
        return 'C'
    if percentage >= 45:
        return 'D'
    return 'F'
