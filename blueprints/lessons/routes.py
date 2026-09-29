# blueprints/lessons/routes.py
"""Weekly lesson plans.

A teacher manages only their own plans. An admin can read every plan in the
school and may create plans on a teacher's behalf.
"""
from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from extensions import db
from models import LessonPlan, Teacher, Class
from forms import LessonPlanForm
from subjects import all_subjects
from utils import is_admin, is_teacher, save_upload, delete_upload
from . import lessons_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _teacher_row():
    return Teacher.query.filter_by(user_id=current_user.id).first() if is_teacher() else None


def _visible_plans(teacher):
    """Admins see every plan; a teacher sees only their own."""
    query = LessonPlan.query
    if not is_admin():
        query = query.filter_by(teacher_id=teacher.id if teacher else -1)
    return query.order_by(
        LessonPlan.week_of.is_(None),
        LessonPlan.week_of.desc(),
        LessonPlan.created_at.desc(),
    ).all()


def _can_edit(plan, teacher):
    """Only the plan's author, or an admin, may modify it."""
    if is_admin():
        return True
    return bool(teacher) and plan.teacher_id == teacher.id


@lessons_bp.route('/')
@login_required
def index():
    if not (is_admin() or is_teacher()):
        return _forbidden()

    teacher = _teacher_row()
    plans = _visible_plans(teacher)
    subject = request.args.get('subject', '').strip()
    teacher_filter = request.args.get('teacher_id', '').strip()

    if subject:
        plans = [p for p in plans if subject.lower() in p.subject.lower()]
    if teacher_filter and is_admin():
        plans = [p for p in plans if str(p.teacher_id) == teacher_filter]

    return render_template(
        'lessons/index.html', plans=plans, subjects=all_subjects(),
        teachers=Teacher.query.order_by(Teacher.name).all() if is_admin() else [],
        subject=subject, teacher_filter=teacher_filter, is_admin=is_admin(),
    )


def _link_class(plan, class_name):
    """Store the typed class name and, when it matches a real class, the FK too."""
    name = (class_name or '').strip()
    plan.class_name = name or None
    plan.class_id = None
    if name:
        from models import Class
        cls = Class.query.filter(Class.class_name.ilike(name)).first()
        if cls:
            plan.class_id = cls.id


def _attach_images(plan, files):
    """Save every uploaded image against the plan. Returns how many landed.

    Adding images never replaces what is already attached, so a teacher can
    come back and add a second worksheet later.
    """
    if not files:
        return 0
    from models import LessonPlanImage
    saved = 0
    for file in files:
        stored = save_upload(file, prefix=f'plan{plan.id}')
        if not stored:
            continue
        db.session.add(LessonPlanImage(
            lesson_plan_id=plan.id, filename=stored
        ))
        saved += 1
    return saved


@lessons_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not (is_admin() or is_teacher()):
        return _forbidden()

    form = LessonPlanForm()
    # an admin may file a plan under any teacher; a teacher always owns theirs
    form_owner = None
    if is_admin():
        owner_id = request.form.get('teacher_id', '').strip()
        if owner_id:
            form_owner = Teacher.query.get(int(owner_id))
            if not form_owner:
                flash('That teacher was not found.', 'danger')
                return redirect(url_for('lessons.index'))

    if form.validate_on_submit():
        teacher = form_owner or _teacher_row()
        if not teacher:
            flash('Teacher record not found for this account.', 'danger')
            return redirect(url_for('lessons.index'))

        plan = LessonPlan(
            title=form.title.data.strip(),
            subject=form.subject.data.strip(),
            teacher_id=teacher.id,
            week_of=form.week_of.data,
            objectives=(form.objectives.data or '').strip() or None,
            activities=(form.activities.data or '').strip() or None,
            resources=(form.resources.data or '').strip() or None,
            homework=(form.homework.data or '').strip() or None,
        )
        _link_class(plan, form.class_name.data)
        db.session.add(plan)
        # flush so the plan has an id to hang the images off
        db.session.flush()

        added = _attach_images(plan, form.images.data)
        db.session.commit()

        flash(
            f'Lesson plan saved.'
            + (f' {added} image(s) attached.' if added else ''),
            'success',
        )
        return redirect(url_for('lessons.detail', id=plan.id))

    return render_template(
        'lessons/form.html', form=form, plan=None, teachers=_admin_teachers(),
    )


def _admin_teachers():
    """Teacher picker shown to admins, who may file a plan for any teacher."""
    return Teacher.query.order_by(Teacher.name).all() if is_admin() else []


@lessons_bp.route('/<int:id>')
@login_required
def detail(id):
    if not (is_admin() or is_teacher()):
        return _forbidden()
    plan = db.get_or_404(LessonPlan, id)
    teacher = _teacher_row()
    # a teacher must not be able to read another teacher's plan
    if not is_admin() and (not teacher or plan.teacher_id != teacher.id):
        return _forbidden()
    return render_template(
        'lessons/detail.html', plan=plan, can_edit=_can_edit(plan, teacher)
    )


@lessons_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not (is_admin() or is_teacher()):
        return _forbidden()
    plan = db.get_or_404(LessonPlan, id)
    if not _can_edit(plan, _teacher_row()):
        return _forbidden()

    form = LessonPlanForm(obj=plan)
    if form.validate_on_submit():
        plan.title = form.title.data.strip()
        plan.subject = form.subject.data.strip()
        _link_class(plan, form.class_name.data)
        plan.week_of = form.week_of.data
        plan.objectives = (form.objectives.data or '').strip() or None
        plan.activities = (form.activities.data or '').strip() or None
        plan.resources = (form.resources.data or '').strip() or None
        plan.homework = (form.homework.data or '').strip() or None
        # newly uploaded images are added alongside the existing ones
        added = _attach_images(plan, form.images.data)
        db.session.commit()
        flash(
            'Lesson plan updated.'
            + (f' {added} image(s) attached.' if added else ''),
            'success',
        )
        return redirect(url_for('lessons.detail', id=plan.id))

    return render_template(
        'lessons/form.html', form=form, plan=plan, teachers=_admin_teachers(),
    )


@lessons_bp.route('/images/<int:image_id>/delete', methods=['POST'])
@login_required
def delete_image(image_id):
    """Remove one attached image. Only the plan's author or an admin may."""
    if not (is_admin() or is_teacher()):
        return _forbidden()

    from models import LessonPlanImage
    image = db.session.get(LessonPlanImage, image_id)
    if image is None:
        abort(404)
    plan = image.lesson_plan
    if not _can_edit(plan, _teacher_row()):
        return _forbidden()

    delete_upload(image.filename)
    db.session.delete(image)
    db.session.commit()
    flash('Image removed.', 'info')
    return redirect(url_for('lessons.detail', id=plan.id))


@lessons_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not (is_admin() or is_teacher()):
        return _forbidden()
    plan = db.get_or_404(LessonPlan, id)
    if not _can_edit(plan, _teacher_row()):
        return _forbidden()
    db.session.delete(plan)
    db.session.commit()
    flash('Lesson plan deleted.', 'info')
    return redirect(url_for('lessons.index'))
