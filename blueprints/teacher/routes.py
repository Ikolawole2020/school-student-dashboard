# blueprints/teacher/routes.py
from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from models import Teacher, Class, Student, Assignment, AssignmentScore
from utils import current_teacher, is_teacher
from . import teacher_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _require_teacher():
    """Returns (teacher, denied_response)."""
    if not is_teacher():
        return None, _forbidden()
    teacher = current_teacher()
    if not teacher:
        flash('No teacher profile is linked to this account.', 'danger')
        return None, redirect(url_for('auth.logout'))
    return teacher, None


@teacher_bp.route('/dashboard')
@login_required
def dashboard():
    teacher, denied = _require_teacher()
    if denied:
        return denied

    assigned_classes = Class.query.filter_by(teacher_id=teacher.id).all()
    assigned_class = assigned_classes[0] if assigned_classes else None

    my_assignments = Assignment.query.filter_by(teacher_id=teacher.id).all()
    my_plans_count = teacher.lesson_plans.__len__()

    student_count = (
        Student.query.filter_by(class_id=assigned_class.id).count()
        if assigned_class else 0
    )
    graded = sum(1 for a in my_assignments for s in a.scores if s.score is not None)

    return render_template(
        'teacher/dashboard.html', teacher=teacher,
        assigned_class=assigned_class,
        assigned_classes=assigned_classes,
        student_count=student_count,
        assignment_count=len(my_assignments),
        plan_count=my_plans_count,
        graded_count=graded,
    )


@teacher_bp.route('/class/<int:class_id>')
@login_required
def class_detail(class_id):
    teacher, denied = _require_teacher()
    if denied:
        return denied

    cls = Class.query.get_or_404(class_id)
    # a teacher may only open a class they are the class teacher of
    if cls.teacher_id != teacher.id:
        return _forbidden()

    students = Student.query.filter_by(class_id=class_id).order_by(Student.name).all()
    return render_template(
        'teacher/class_detail.html', cls=cls, students=students, teacher=teacher
    )
