# blueprints/auth/routes.py
from flask import render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user, fresh_login_required

from extensions import db
from models import User, Student, Class, SeniorStudent
from forms import LoginForm, StudentRegisterForm, ChangePasswordForm
from utils import save_upload
from . import auth_bp


def _home_for(user):
    """Role-aware landing page after login.

    Teachers used to be sent to admin.teachers, an admin-only page, so every
    teacher login landed on a 403. They now go to their own dashboard.
    """
    if user.role == 'admin':
        return url_for('admin.dashboard')
    if user.role == 'teacher':
        return url_for('teacher.dashboard')
    return url_for('student.dashboard')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.is_active and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            flash(f'Welcome back, {user.email}.', 'success')
            # honour ?next= so deep links still work after a session expires
            nxt = request.args.get('next')
            if nxt and nxt.startswith('/') and not nxt.startswith('//'):
                return redirect(nxt)
            return redirect(_home_for(user))
        if user and not user.is_active:
            flash('This account has been deactivated. Please contact the school office.', 'danger')
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('public.home'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Lets any account replace a school-issued password.

    Accounts created with a derived or generated password are flagged
    must_change_password, and app.py bounces them here until they set their own.
    """
    first_login = bool(request.args.get('first_login')) or bool(
        getattr(current_user, 'must_change_password', False)
    )
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password_hash, form.current_password.data):
            flash('Your current password is incorrect.', 'danger')
        elif current_user.password_hash == form.new_password.data:
            flash('The new password must be different from the old one.', 'warning')
        else:
            current_user.password_hash = generate_password_hash(form.new_password.data)
            # the school-issued password has now been replaced
            current_user.must_change_password = False
            db.session.commit()
            flash('Password updated successfully.', 'success')
            if first_login:
                flash('You can now use the rest of the portal.', 'info')
            return redirect(_home_for(current_user))
    return render_template(
        'auth/change_password.html', form=form, first_login=first_login
    )


@auth_bp.route('/register-student', methods=['GET', 'POST'])
def register_student():
    form = StudentRegisterForm()

    if request.method == 'POST' and form.name.data:
        # derive the public ID and email from the name before validating
        from utils import slugify_name
        base = slugify_name(form.name.data)
        form.student_public_id.data = base
        form.email.data = f'{base}@smc.com'

    if form.validate_on_submit():
        public_id = form.student_public_id.data.strip()
        email = form.email.data.strip().lower()

        if Student.query.filter_by(student_public_id=public_id).first():
            flash('A student with that ID already exists.', 'warning')
            return render_template('auth/register_student.html', form=form)

        if User.query.filter_by(email=email).first():
            # a same-named student already registered - keep both usable
            email = f'{public_id}2@smc.com'
            form.email.data = email

        user = User(
            email=email,
            password_hash=generate_password_hash(form.password.data),
            role='student',
        )
        db.session.add(user)
        db.session.flush()

        cls = Class.query.filter(
            Class.class_name.ilike(form.class_name.data.strip())
        ).first()

        student = Student(
            user_id=user.id,
            student_public_id=public_id,
            name=form.name.data.strip(),
            dob=form.dob.data,
            gender=form.gender.data.strip(),
            class_id=cls.id if cls else None,
            email=email,
            guardian_phone=(form.guardian_phone.data or '').strip() or None,
            profile_picture=save_upload(
                request.files.get('profile_picture'), prefix=public_id
            ),
        )
        db.session.add(student)
        db.session.flush()

        if cls and cls.class_name.upper().startswith('SS') and form.department.data:
            db.session.add(SeniorStudent(
                student_id=student.id, department=form.department.data.strip()
            ))

        db.session.commit()
        flash('Registration successful. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_student.html', form=form)
