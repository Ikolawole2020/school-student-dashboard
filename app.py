# app.py
import os
from datetime import date, timedelta

from flask import Flask, request, render_template, flash, redirect, url_for
import click

from config import Config
from extensions import db, login_manager, csrf
from models import User
from blueprints.auth import auth_bp
from blueprints.public import public_bp
from blueprints.student import student_bp
from blueprints.admin import admin_bp
from blueprints.teacher import teacher_bp
from blueprints.assignments import assignments_bp
from blueprints.lessons import lessons_bp
from blueprints.attendance import attendance_bp
from blueprints.content import content_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    # Accounts created with a school-issued password (derived from the name,
    # or generated) must replace it before they can use the rest of the app.
    @app.before_request
    def force_password_change():
        from flask_login import current_user
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, 'must_change_password', False):
            return None

        allowed = {
            'auth.change_password', 'auth.logout', 'static',
        }
        if request.endpoint in allowed:
            return None
        # never trap them in a redirect loop
        if request.endpoint in ('public.search',):
            return None
        return redirect(url_for('auth.change_password', first_login=1))

    # Make request available to all templates for active link highlighting
    @app.context_processor
    def inject_globals():
        return dict(request=request, today=date.today())

    @app.template_filter('friendly_date')
    def friendly_date(value):
        if not value:
            return 'N/A'
        if isinstance(value, str):
            return value
        return value.strftime('%d %b %Y')

    @app.template_filter('due_badge')
    def due_badge(due_date):
        """Returns a (label, css-class) pair describing an assignment due date."""
        if not due_date:
            return 'No due date', 'bg-secondary'
        today = date.today()
        if due_date < today:
            return f'Closed {(today - due_date).days}d ago', 'bg-danger'
        if due_date == today:
            return 'Due today', 'bg-danger'
        if due_date == today + timedelta(days=1):
            return 'Due tomorrow', 'bg-warning text-dark'
        return f'Due in {(due_date - today).days}d', 'bg-info text-dark'

    @app.errorhandler(403)
    def forbidden(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template('errors/413.html'), 413

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        # A schema mismatch is by far the most common cause of a 500 on a
        # deployment, so say so plainly instead of showing a dead end.
        from utils import schema_problems
        try:
            problems = schema_problems(app)
        except Exception:
            problems = []
        return render_template('errors/500.html', schema_problems=problems), 500

    @app.cli.command('check-schema')
    def check_schema():
        """Report any tables or columns the current code needs but the DB lacks."""
        from utils import schema_problems
        problems = schema_problems(app)
        if not problems:
            click.echo('Database schema is up to date.')
            return
        click.echo('')
        click.echo('DATABASE SCHEMA IS OUT OF DATE')
        click.echo('-' * 60)
        for problem in problems:
            click.echo(f'  - {problem}')
        click.echo('')
        click.echo('Run this to fix it:')
        click.echo('    python migrate_guardian_phone.py')

    @app.cli.command('list-users')
    def list_users():
        """Show every account, so you can see what is really in the database."""
        rows = User.query.order_by(User.id).all()
        if not rows:
            click.echo('No accounts exist yet.')
            return
        click.echo(f'{"ID":<5}{"EMAIL":<34}{"ROLE":<10}ACTIVE')
        for u in rows:
            click.echo(f'{u.id:<5}{u.email:<34}{u.role:<10}{bool(u.is_active)}')

    @app.cli.command('create-admin')
    @click.option('--email', prompt='Admin email address')
    @click.option('--password', prompt='Password', hide_input=True,
                  confirmation_prompt=True)
    @click.option('--reset', is_flag=True,
                  help='Reset the password if the account already exists')
    def create_admin(email, password, reset):
        """Create an admin account, or reset an existing one's password."""
        from werkzeug.security import generate_password_hash

        if len(password) < 8:
            click.echo('Password must be at least 8 characters.')
            return

        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()

        if user and not reset:
            click.echo(
                f'{email} already exists (role: {user.role}). '
                f'Re-run with --reset to change the password.'
            )
            return

        if user:
            user.password_hash = generate_password_hash(password)
            user.role = 'admin'
            user.is_active = True
            click.echo(f'Password reset for {email}.')
        else:
            db.session.add(User(
                email=email,
                password_hash=generate_password_hash(password),
                role='admin',
            ))
            click.echo(f'Admin account created: {email}')

        db.session.commit()

    @app.cli.command('set-password')
    @click.option('--email', prompt='Account email address')
    @click.option('--password', prompt='New password', hide_input=True,
                  confirmation_prompt=True)
    def set_password(email, password):
        """Set the password for any account (admin, teacher or student)."""
        from werkzeug.security import generate_password_hash

        if len(password) < 6:
            click.echo('Password must be at least 6 characters.')
            return

        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f'No account found for {email}.')
            return

        user.password_hash = generate_password_hash(password)
        user.is_active = True
        db.session.commit()
        click.echo(f'Password updated for {email} (role: {user.role}).')

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(public_bp, url_prefix='/')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')
    app.register_blueprint(assignments_bp, url_prefix='/assignments')
    app.register_blueprint(lessons_bp, url_prefix='/lessons')
    app.register_blueprint(attendance_bp, url_prefix='/attendance')
    app.register_blueprint(content_bp, url_prefix='')

    with app.app_context():
        db.create_all()

    # Tell the operator immediately if the database predates the code,
    # rather than letting the first edit fail with an unexplained 500.
    from utils import log_schema_problems
    log_schema_problems(app)

    return app


# A module-level instance so the Flask CLI can find the app
# (e.g. FLASK_APP="app:create_admin" flask list-users).
app = create_app()


if __name__ == '__main__':
    app.run(debug=True)


