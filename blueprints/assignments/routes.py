# blueprints/assignments/routes.py
"""Assignment hub.

Students read assignments posted for their class. Teachers and admins post
assignments and record scores.
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import Assignment, AssignmentScore, Student, Teacher, Class
from forms import AssignmentForm
from subjects import all_subjects
from utils import is_admin, is_teacher, current_student
from . import assignments_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _can_post():
    return is_admin() or is_teacher()


def _teacher_row():
    return Teacher.query.filter_by(user_id=current_user.id).first() if is_teacher() else None


def _teacher_owns(assignment, teacher):
    """Admins may touch anything; a teacher may only touch their own posts."""
    if teacher is None:
        return True
    return assignment.teacher_id == teacher.id


@assignments_bp.route('/')
@login_required
def index():
    subject = request.args.get('subject', '').strip()
    class_filter = request.args.get('class_id', '').strip()
    query = Assignment.query
    teacher = _teacher_row()

    if current_user.role == 'student':
        student = current_student()
        if not student or not student.class_id:
            assignments, classes = [], []
        else:
            query = query.filter_by(class_id=student.class_id)
            classes = [student.class_rel] if student.class_rel else []
        assignments = []
        if student and student.class_id:
            assignments = query.order_by(
                Assignment.due_date.is_(None), Assignment.due_date.asc(),
                Assignment.created_at.desc(),
            ).all()
    elif is_teacher():
        # A teacher sees only assignments posted to their own class
        allowed = [c.id for c in Class.query.filter_by(teacher_id=teacher.id).all()] if teacher else []
        classes = Class.query.filter(Class.id.in_(allowed)).all() if allowed else []
        assignments = []
        if allowed:
            assignments = Assignment.query.filter(
                Assignment.class_id.in_(allowed)
            ).order_by(
                Assignment.due_date.is_(None), Assignment.due_date.asc(),
                Assignment.created_at.desc(),
            ).all()
    else:  # admin
        classes = Class.query.order_by(Class.class_name.asc()).all()
        assignments = query.order_by(
            Assignment.due_date.is_(None), Assignment.due_date.asc(),
            Assignment.created_at.desc(),
        ).all()

    if subject:
        assignments = [a for a in assignments if subject.lower() in a.subject.lower()]
    if class_filter and is_admin():
        assignments = [a for a in assignments if str(a.class_id) == class_filter]

    return render_template(
        'assignments/index.html', assignments=assignments,
        subjects=all_subjects(), classes=classes, subject=subject,
        class_filter=class_filter, is_poster=_can_post(),
    )


@assignments_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not _can_post():
        return _forbidden()
    form = AssignmentForm()
    teacher = _teacher_row()

    if teacher:
        # a teacher can only post to the class they are class teacher of
        own = Class.query.filter_by(teacher_id=teacher.id).all()
        if not own:
            flash(
                'You are not assigned to a class yet, so you cannot post an '
                'assignment.', 'warning'
            )
            return redirect(url_for('assignments.index'))
        form.class_id.choices = [(c.id, c.class_name) for c in own]

    if form.validate_on_submit():
        db.session.add(Assignment(
            title=form.title.data.strip(),
            subject=form.subject.data.strip(),
            class_id=form.class_id.data,
            description=(form.description.data or '').strip() or None,
            due_date=form.due_date.data,
            max_score=form.max_score.data or 100.0,
            teacher_id=teacher.id if teacher else None,
        ))
        db.session.commit()
        flash('Assignment posted.', 'success')
        return redirect(url_for('assignments.index'))

    return render_template(
        'assignments/form.html', form=form, assignment=None, subjects=all_subjects()
    )


@assignments_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not _can_post():
        return _forbidden()
    assignment = db.get_or_404(Assignment, id)
    teacher = _teacher_row()
    if not _teacher_owns(assignment, teacher):
        return _forbidden()

    form = AssignmentForm(obj=assignment)
    if teacher:
        own = Class.query.filter_by(teacher_id=teacher.id).all()
        form.class_id.choices = [(c.id, c.class_name) for c in own]

    if form.validate_on_submit():
        assignment.title = form.title.data.strip()
        assignment.subject = form.subject.data.strip()
        assignment.class_id = form.class_id.data
        assignment.description = (form.description.data or '').strip() or None
        assignment.due_date = form.due_date.data
        assignment.max_score = form.max_score.data or 100.0
        db.session.commit()
        flash('Assignment updated.', 'success')
        return redirect(url_for('assignments.index'))

    return render_template(
        'assignments/form.html', form=form, assignment=assignment,
        subjects=all_subjects(),
    )


@assignments_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not _can_post():
        return _forbidden()
    assignment = db.get_or_404(Assignment, id)
    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()
    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted.', 'info')
    return redirect(url_for('assignments.index'))


@assignments_bp.route('/<int:id>')
@login_required
def detail(id):
    assignment = db.get_or_404(Assignment, id)

    if current_user.role == 'student':
        student = current_student()
        # a student may only open an assignment posted for their own class
        if not student or student.class_id != assignment.class_id:
            return _forbidden()
        score_row = AssignmentScore.query.filter_by(
            assignment_id=assignment.id, student_id=student.id
        ).first()
        return render_template(
            'assignments/detail.html', assignment=assignment,
            score_row=score_row, students=None, existing=None, is_poster=False,
        )

    if not _can_post():
        return _forbidden()
    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()

    students = Student.query.filter_by(class_id=assignment.class_id).order_by(Student.name).all()
    existing = {s.student_id: s for s in assignment.scores}
    return render_template(
        'assignments/detail.html', assignment=assignment, score_row=None,
        students=students, existing=existing, is_poster=True,
    )


@assignments_bp.route('/<int:id>/scores', methods=['POST'])
@login_required
def save_scores(id):
    """Record assignment scores.

    Deliberately forgiving, mirroring how exam results already behave: blank
    cells are skipped so a teacher can enter scores for the students who
    actually sat the assignment and leave the rest alone. A student is only
    recorded as absent when the "absent" box is ticked.
    """
    if not _can_post():
        return _forbidden()
    assignment = db.get_or_404(Assignment, id)
    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()

    students = Student.query.filter_by(class_id=assignment.class_id).all()
    max_score = assignment.max_score or 100.0
    saved = 0

    for student in students:
        raw = request.form.get(f'score_{student.id}', '').strip()
        feedback = (request.form.get(f'feedback_{student.id}', '') or '').strip()[:300]
        absent = request.form.get(f'absent_{student.id}') == 'on'
        row = AssignmentScore.query.filter_by(
            assignment_id=assignment.id, student_id=student.id
        ).first()

        # untouched cell - leave whatever was stored before
        if raw == '' and not absent:
            continue

        if absent or raw == '':
            if row:
                row.score, row.feedback = None, feedback or None
            else:
                db.session.add(AssignmentScore(
                    assignment_id=assignment.id, student_id=student.id,
                    score=None, feedback=feedback or None,
                ))
            continue

        try:
            value = float(raw)
        except ValueError:
            flash(f'{student.name}: "{raw}" is not a number.', 'danger')
            continue
        if value < 0 or value > max_score:
            flash(f'{student.name}: score must be between 0 and {max_score:g}.', 'danger')
            continue

        if row:
            row.score, row.feedback = value, feedback or None
        else:
            db.session.add(AssignmentScore(
                assignment_id=assignment.id, student_id=student.id,
                score=value, feedback=feedback or None,
            ))
        saved += 1

    db.session.commit()
    if saved:
        flash(f'Saved {saved} score{"" if saved == 1 else "s"}.', 'success')
    else:
        flash('No scores were changed.', 'info')
    return redirect(url_for('assignments.detail', id=assignment.id))
