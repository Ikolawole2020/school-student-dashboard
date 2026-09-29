# app.py
import os
from datetime import date, timedelta

from flask import Flask, request, render_template, flash, redirect, url_for

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
        return render_template('errors/500.html'), 500

    @app.cli.command('seed-admin')
    def seed_admin():
        """Create an admin account if none exists yet."""
        from werkzeug.security import generate_password_hash
        if User.query.filter_by(role='admin').first():
            print('An admin account already exists.')
            return
        email = os.environ.get('ADMIN_EMAIL', 'admin@smc.com')
        password = os.environ.get('ADMIN_PASSWORD', 'Admin123#')
        db.session.add(User(
            email=email,
            password_hash=generate_password_hash(password),
            role='admin',
        ))
        db.session.commit()
        print(f'Created admin {email} with password {password}')

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(public_bp, url_prefix='/')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')
    app.register_blueprint(assignments_bp, url_prefix='/assignments')
    app.register_blueprint(lessons_bp, url_prefix='/lessons')

    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    create_app().run(debug=True)
