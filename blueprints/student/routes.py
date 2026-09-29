# blueprints/student/routes.py
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import Student, Result, Assignment, AssignmentScore
from forms import StudentProfileForm, ViewResultForm
from utils import current_student, save_upload, delete_upload
from . import student_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _require_student():
    """Returns (student, response). response is set when access is denied."""
    if current_user.role != 'student':
        return None, _forbidden()
    student = current_student()
    if not student:
        flash('No student profile is linked to this account.', 'danger')
        return None, redirect(url_for('auth.logout'))
    return student, None


@student_bp.route('/dashboard')
@login_required
def dashboard():
    student, denied = _require_student()
    if denied:
        return denied

    class_param = request.args.get('class_name')
    term_param = request.args.get('term')
    filtered_results = None
    if class_param and term_param:
        filtered_results = Result.query.filter_by(
            student_id=student.id, class_name=class_param, term=term_param
        ).all()

    assignments = (
        Assignment.query.filter_by(class_id=student.class_id)
        .order_by(Assignment.due_date.is_(None), Assignment.due_date.asc())
        .all() if student.class_id else []
    )

    my_scores = {
        s.assignment_id: s for s in student.assignment_scores
    }

    return render_template(
        'student/dashboard.html', student=student,
        form=ViewResultForm(), filtered_results=filtered_results,
        assignments=assignments, my_scores=my_scores,
        result_count=Result.query.filter_by(student_id=student.id).count(),
    )


@student_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    student, denied = _require_student()
    if denied:
        return denied

    form = StudentProfileForm(obj=student)
    if form.validate_on_submit():
        student.name = form.name.data.strip()
        student.dob = form.dob.data
        student.gender = form.gender.data.strip()
        student.email = form.email.data.strip()
        student.guardian_phone = (form.guardian_phone.data or '').strip() or None

        stored = save_upload(
            request.files.get('profile_picture'), prefix=student.student_public_id
        )
        if stored:
            delete_upload(student.profile_picture)
            student.profile_picture = stored

        # keep the login email in step with the profile email
        if student.user:
            student.user.email = student.email

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('student.profile'))

    return render_template('student/profile.html', student=student, form=form)


@student_bp.route('/results')
@login_required
def results():
    student, denied = _require_student()
    if denied:
        return denied

    class_param = request.args.get('class_name', '').strip()
    term_param = request.args.get('term', '').strip()

    query = Result.query.filter_by(student_id=student.id)
    if class_param:
        query = query.filter_by(class_name=class_param)
    if term_param:
        query = query.filter_by(term=term_param)

    rows = query.order_by(Result.class_name, Result.term, Result.subject).all()

    # average percentage across whatever rows are in view
    average = sum(r.percentage for r in rows) / len(rows) if rows else None

    return render_template(
        'student/results.html', student=student, results=rows,
        class_param=class_param, term_param=term_param, average=average,
    )


@student_bp.route('/assignments')
@login_required
def assignments():
    """Shortcut into the assignment hub, pre-scoped to this student."""
    return redirect(url_for('assignments.index'))
