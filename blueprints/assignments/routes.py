# blueprints/assignments/routes.py
"""Assignment hub.

Teachers and admins post assignments - with typed-in class and subject, plus
any number of attached images. Students see the work for their own class and
upload their answers back as images.
"""
from flask import (
    render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Assignment, AssignmentScore, AssignmentMedia, AssignmentSubmission,
    AssignmentSubmissionFile, Student, Teacher, Class,
)
from forms import AssignmentForm, SubmissionForm
from subjects import all_subjects
from utils import (
    is_admin, is_teacher, current_student, save_upload, delete_upload,
)
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


def _link_class(assignment, class_name):
    """Store the typed class name and, if it matches a real class, the FK too."""
    name = (class_name or '').strip()
    assignment.class_name = name or None
    assignment.class_id = None
    if name:
        cls = Class.query.filter(Class.class_name.ilike(name)).first()
        if cls:
            assignment.class_id = cls.id


def _attach_media(assignment, files):
    """Save images the teacher attached to the assignment."""
    if not files:
        return 0
    saved = 0
    for file in files:
        stored = save_upload(file, prefix=f'assign{assignment.id}')
        if not stored:
            continue
        db.session.add(AssignmentMedia(
            assignment_id=assignment.id, filename=stored
        ))
        saved += 1
    return saved


def _visible_query(teacher):
    """Assignments the current user is allowed to list."""
    query = Assignment.query
    if current_user.role == 'student':
        student = current_student()
        if not student or not student.class_id:
            return None, []
        return query.filter_by(class_id=student.class_id), [student.class_rel]

    if is_teacher():
        # a teacher sees their own posts plus anything aimed at their class
        if teacher:
            class_ids = [
                c.id for c in Class.query.filter_by(teacher_id=teacher.id).all()
            ]
            classes = Class.query.filter(Class.id.in_(class_ids)).all() if class_ids else []
            query = query.filter(
                db.or_(
                    Assignment.teacher_id == teacher.id,
                    Assignment.class_id.in_(class_ids) if class_ids else False,
                )
            )
            return query, classes
        return query.filter(Assignment.id.is_(None)), []

    return query, Class.query.order_by(Class.class_name.asc()).all()


def _ordered(query):
    return query.order_by(
        Assignment.due_date.is_(None), Assignment.due_date.asc(),
        Assignment.created_at.desc(),
    ).all()


@assignments_bp.route('/')
@login_required
def index():
    teacher = _teacher_row()
    query, classes = _visible_query(teacher)

    subject = request.args.get('subject', '').strip()
    class_filter = request.args.get('class_id', '').strip()

    if query is None:
        assignments = []
    else:
        assignments = _ordered(query)

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

    if form.validate_on_submit():
        assignment = Assignment(
            title=form.title.data.strip(),
            subject=form.subject.data.strip(),
            description=(form.description.data or '').strip() or None,
            due_date=form.due_date.data,
            max_score=form.max_score.data or 100.0,
            teacher_id=teacher.id if teacher else None,
        )
        _link_class(assignment, form.class_name.data)
        db.session.add(assignment)
        db.session.flush()  # need an id before saving files against it

        added = _attach_media(assignment, form.media.data)
        db.session.commit()

        flash(
            'Assignment posted.'
            + (f' {added} image(s) attached.' if added else ''),
            'success',
        )
        return redirect(url_for('assignments.detail', id=assignment.id))

    return render_template(
        'assignments/form.html', form=form, assignment=None,
        subjects=all_subjects(), classes=_class_suggestions(teacher),
    )


def _class_suggestions(teacher):
    """Existing class names offered as suggestions for the free-text field."""
    if is_admin():
        return Class.query.order_by(Class.class_name.asc()).all()
    if teacher:
        return Class.query.filter_by(teacher_id=teacher.id).order_by(
            Class.class_name.asc()
        ).all()
    return []



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

    if form.validate_on_submit():
        assignment.title = form.title.data.strip()
        assignment.subject = form.subject.data.strip()
        assignment.description = (form.description.data or '').strip() or None
        assignment.due_date = form.due_date.data
        assignment.max_score = form.max_score.data or 100.0
        _link_class(assignment, form.class_name.data)
        # newly uploaded media is added alongside what is already there
        added = _attach_media(assignment, form.media.data)
        db.session.commit()
        flash(
            'Assignment updated.'
            + (f' {added} image(s) attached.' if added else ''),
            'success',
        )
        return redirect(url_for('assignments.detail', id=assignment.id))

    return render_template(
        'assignments/form.html', form=form, assignment=assignment,
        subjects=all_subjects(), classes=_class_suggestions(teacher),
    )


@assignments_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not _can_post():
        return _forbidden()
    assignment = db.get_or_404(Assignment, id)
    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()
    _purge_files(assignment)
    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted.', 'info')
    return redirect(url_for('assignments.index'))


@assignments_bp.route('/media/<int:media_id>/delete', methods=['POST'])
@login_required
def delete_media(media_id):
    """Remove one image the teacher attached to the assignment."""
    if not _can_post():
        return _forbidden()
    media = db.session.get(AssignmentMedia, media_id)
    if media is None:
        abort(404)
    assignment = media.assignment
    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()
    delete_upload(media.filename)
    db.session.delete(media)
    db.session.commit()
    flash('Image removed.', 'info')
    return redirect(url_for('assignments.detail', id=assignment.id))


@assignments_bp.route('/<int:id>')
@login_required
def detail(id):
    assignment = db.get_or_404(Assignment, id)

    if current_user.role == 'student':
        student = current_student()
        # a student may only open work posted for their own class
        if not student or student.class_id != assignment.class_id:
            return _forbidden()
        submission = AssignmentSubmission.query.filter_by(
            assignment_id=assignment.id, student_id=student.id
        ).first()
        score_row = AssignmentScore.query.filter_by(
            assignment_id=assignment.id, student_id=student.id
        ).first()
        return render_template(
            'assignments/detail.html', assignment=assignment,
            submission=submission, submission_form=SubmissionForm(),
            score_row=score_row, students=None, existing=None,
            submissions=None, is_poster=False,
        )

    if not _can_post():
        return _forbidden()
    teacher = _teacher_row()
    if not _teacher_owns(assignment, teacher):
        return _forbidden()

    students = (
        Student.query.filter_by(class_id=assignment.class_id)
        .order_by(Student.name).all()
        if assignment.class_id else []
    )
    existing = {s.student_id: s for s in assignment.scores}
    submissions = {s.student_id: s for s in assignment.submissions}
    return render_template(
        'assignments/detail.html', assignment=assignment, submission=None,
        submission_form=None, score_row=None, students=students,
        existing=existing, submissions=submissions, is_poster=True,
    )


@assignments_bp.route('/<int:id>/submit', methods=['GET', 'POST'])
@login_required
def submit(id):
    """A student uploads their answer as images.

    Re-submitting replaces the previous attempt rather than piling up files;
    the note and the images are both updated in place.
    """
    if current_user.role != 'student':
        return _forbidden()
    student = current_student()
    assignment = db.get_or_404(Assignment, id)
    if not student or student.class_id != assignment.class_id:
        return _forbidden()

    existing = AssignmentSubmission.query.filter_by(
        assignment_id=assignment.id, student_id=student.id
    ).first()
    form = SubmissionForm(obj=existing)

    if form.validate_on_submit():
        stored = []
        for file in form.images.data or []:
            name = save_upload(file, prefix=f'sub{student.id}')
            if name:
                stored.append(name)

        if not stored:
            flash('No image was saved. Please use JPEG or PNG files.', 'danger')
            return render_template(
                'assignments/detail.html', assignment=assignment,
                submission=existing, submission_form=form,
                score_row=None, students=None, existing=None,
                submissions=None, is_poster=False,
            )

        submission = existing or AssignmentSubmission(
            assignment_id=assignment.id, student_id=student.id
        )
        submission.note = (form.note.data or '').strip() or None
        if existing is None:
            db.session.add(submission)
            db.session.flush()

        # clear the previous attempt's images before adding the new ones
        for old in list(submission.files):
            delete_upload(old.filename)
            db.session.delete(old)

        for name in stored:
            db.session.add(AssignmentSubmissionFile(
                submission_id=submission.id, filename=name
            ))

        db.session.commit()
        flash(
            f'Answer submitted ({len(stored)} image(s)). '
            'Your teacher can now see it.',
            'success',
        )
        return redirect(url_for('assignments.detail', id=assignment.id))

    return render_template(
        'assignments/detail.html', assignment=assignment,
        submission=existing, submission_form=form,
        score_row=None, students=None, existing=None,
        submissions=None, is_poster=False,
    )

    if not _teacher_owns(assignment, _teacher_row()):
        return _forbidden()
    delete_upload(media.filename)
    db.session.delete(media)
    db.session.commit()
    flash('Image removed.', 'info')
    return redirect(url_for('assignments.detail', id=assignment.id))


def _purge_files(assignment):
    """Remove every stored file belonging to an assignment."""
    for media in list(assignment.media):
        delete_upload(media.filename)
    for submission in list(assignment.submissions):
        for f in list(submission.files):
            delete_upload(f.filename)



@assignments_bp.route('/submission/<int:submission_id>/delete', methods=['POST'])
@login_required
def delete_submission(submission_id):
    """Remove a submitted answer. The owner, or a teacher of that class, may."""
    submission = db.session.get(AssignmentSubmission, submission_id)
    if submission is None:
        abort(404)

    if current_user.role == 'student':
        student = current_student()
        if not student or student.id != submission.student_id:
            return _forbidden()
    elif is_teacher():
        teacher = _teacher_row()
        own_class_ids = [
            c.id for c in Class.query.filter_by(teacher_id=teacher.id).all()
        ] if teacher else []
        allowed = teacher and (
            submission.assignment.teacher_id == teacher.id
            or submission.assignment.class_id in own_class_ids
        )
        if not allowed:
            return _forbidden()
    elif not is_admin():
        return _forbidden()

    assignment_id = submission.assignment_id
    for f in list(submission.files):
        delete_upload(f.filename)
    db.session.delete(submission)
    db.session.commit()
    flash('Submission deleted.', 'info')
    return redirect(url_for('assignments.detail', id=assignment_id))


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

    students = (
        Student.query.filter_by(class_id=assignment.class_id).all()
        if assignment.class_id else []
    )
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
