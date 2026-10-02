# blueprints/admin/routes.py
"""Admin panel - admin only.

Teachers reach assignments and lesson plans through their own blueprints,
which enforce per-teacher ownership.
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Student, Teacher, Result, SeniorStudent, Class,
    LessonPlan, Assignment,
)
from forms import (
    AdminAddStudentForm, AdminEditStudentForm, AdminEditTeacherForm,
    TeacherForm, ResultForm, SeniorDeptForm, ClassForm, ViewResultForm,
    TERM_CHOICES,
)
from subjects import get_subjects_for_class
from utils import (
    is_admin, save_upload, delete_upload, slugify_name,
    unique_staff_id, unique_email, generate_password, grade_for,
    derive_staff_password,
)
from . import admin_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _require_admin():
    if not is_admin():
        return _forbidden()
    return None


def _teacher_choices():
    return [(0, '-- No class teacher --')] + [
        (t.id, t.name) for t in Teacher.query.order_by(Teacher.name).all()
    ]


# --------------------------------------------------------------- progression

PROMOTION_MAP = {
    'Creche': 'KG', 'KG': 'Nursery 1', 'Nursery 1': 'Nursery 2',
    'Nursery 2': 'Basic 1', 'Basic 1': 'Basic 2', 'Basic 2': 'Basic 3',
    'Basic 3': 'Basic 4', 'Basic 4': 'Basic 5', 'Basic 5': 'JSS1',
    'JSS1': 'JSS2', 'JSS2': 'JSS3', 'JSS3': 'SS1',
    'SS1': 'SS2', 'SS2': 'SS3', 'SS3': None,
}

DEMOTION_MAP = {
    'Creche': None, 'KG': 'Creche', 'Nursery 1': 'KG', 'Nursery 2': 'Nursery 1',
    'Basic 1': 'Nursery 2', 'Basic 2': 'Basic 1', 'Basic 3': 'Basic 2',
    'Basic 4': 'Basic 3', 'Basic 5': 'Basic 4', 'JSS1': 'Basic 5',
    'JSS2': 'JSS1', 'JSS3': 'JSS2', 'SS1': 'JSS3', 'SS2': 'SS1', 'SS3': 'SS2',
}


def _class_id_named(name):
    if not name:
        return None
    cls = Class.query.filter(Class.class_name.ilike(name.strip())).first()
    return cls.id if cls else None


def get_next_class(current_class_name):
    """Class ID above the given one, or None at the top of the ladder."""
    return _class_id_named(PROMOTION_MAP.get(current_class_name))


def get_previous_class(current_class_name):
    """Class ID below the given one, or None at the bottom of the ladder."""
    return _class_id_named(DEMOTION_MAP.get(current_class_name))


def _ensure_senior(student):
    if not SeniorStudent.query.filter_by(student_id=student.id).first():
        db.session.add(SeniorStudent(student_id=student.id, department=None))


# ----------------------------------------------------------------- dashboard

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    denied = _require_admin()
    if denied:
        return denied

    counts = {
        'students': Student.query.count(),
        'teachers': Teacher.query.count(),
        'classes': Class.query.count(),
        'seniors': SeniorStudent.query.count(),
        'assignments': Assignment.query.count(),
        'lesson_plans': LessonPlan.query.count(),
    }
    # students sitting in no class at all - usually a data-entry gap
    unassigned = Student.query.filter(Student.class_id.is_(None)).count()

    # Staff log-in details, recomputed from each name on every load so no
    # plaintext password is ever written to the database.
    staff = [
        {
            'id': t.id,
            'name': t.name,
            'staff_id': t.staff_id,
            'email': t.email,
            'class_name': t.class_name,
            'password': derive_staff_password(t.name),
        }
        for t in Teacher.query.order_by(Teacher.name).all()
    ]

    return render_template(
        'admin/dashboard.html', counts=counts, unassigned=unassigned,
        staff=staff,
    )


# ------------------------------------------------------------------ students

@admin_bp.route('/students')
@login_required
def students():
    denied = _require_admin()
    if denied:
        return denied

    search = request.args.get('search', '').strip()
    query = Student.query
    if search:
        query = query.filter(
            Student.name.ilike(f'%{search}%')
            | Student.student_public_id.ilike(f'%{search}%')
            | Student.guardian_phone.ilike(f'%{search}%')
        )
    rows = query.order_by(Student.name.asc()).all()
    return render_template('admin/students.html', students=rows, search=search)


@admin_bp.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    denied = _require_admin()
    if denied:
        return denied

    form = AdminAddStudentForm()

    if request.method == 'POST' and form.name.data:
        base = slugify_name(form.name.data)
        form.student_public_id.data = base
        form.email.data = f'{base}@smc.com'

    if form.validate_on_submit():
        public_id = form.student_public_id.data.strip()
        email = form.email.data.strip().lower()

        if Student.query.filter_by(student_public_id=public_id).first():
            flash('A student with that ID already exists.', 'warning')
            return render_template('admin/add_student.html', form=form)

        if User.query.filter_by(email=email).first():
            email = unique_email(public_id)
            form.email.data = email

        # the plaintext password is only shown in this flash message; the
        # Student model no longer has a password column at all
        init_password = form.password.data or generate_password()

        user = User(
            email=email,
            password_hash=generate_password_hash(init_password),
            role='student',
            # only when the school generated the password, not when the
            # student typed their own at registration
            must_change_password=(not form.password.data),
        )
        db.session.add(user)
        db.session.flush()

        class_obj = Class.query.filter(
            Class.class_name.ilike(form.class_name.data.strip())
        ).first()

        student = Student(
            user_id=user.id,
            student_public_id=public_id,
            name=form.name.data.strip(),
            dob=form.dob.data,
            gender=form.gender.data.strip(),
            class_id=class_obj.id if class_obj else None,
            email=email,
            guardian_phone=(form.guardian_phone.data or '').strip() or None,
            profile_picture=save_upload(
                request.files.get('profile_picture'), prefix=public_id
            ),
        )
        db.session.add(student)
        db.session.flush()

        if class_obj and class_obj.class_name.upper().startswith('SS') and form.department.data:
            db.session.add(SeniorStudent(
                student_id=student.id, department=form.department.data.strip()
            ))

        db.session.commit()
        flash(
            f'{student.name} added. Login: {email}  |  '
            f'Temporary password: {init_password}',
            'success',
        )
        return redirect(url_for('admin.students'))

    return render_template('admin/add_student.html', form=form)


@admin_bp.route('/students/<int:id>')
@login_required
def student_profile(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    form = ViewResultForm()

    class_param = request.args.get('class_name')
    term_param = request.args.get('term')
    filtered_results = None
    if class_param and term_param:
        filtered_results = Result.query.filter_by(
            student_id=student.id, class_name=class_param, term=term_param
        ).all()

    rows = Assignment.query.filter_by(class_id=student.class_id).all() if student.class_id else []
    scores = {s.assignment_id: s for s in student.assignment_scores}

    return render_template(
        'admin/student_profile.html', student=student, form=form,
        filtered_results=filtered_results, assignments=rows,
        assignment_scores=scores,
    )


@admin_bp.route('/students/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    class_name = student.class_rel.class_name if student.class_rel else None
    form = AdminEditStudentForm(obj=student)
    # obj= does not populate the non-model class_name field, so preselect it
    if form.class_name.data != class_name:
        form.class_name.data = class_name

    if form.validate_on_submit():
        clash = User.query.filter(
            User.email == form.email.data.strip(), User.id != student.user_id
        ).first()
        if clash:
            flash('That email address is already used by another account.', 'danger')
            return render_template('admin/edit_student.html', form=form, student=student)

        student.name = form.name.data.strip()
        student.dob = form.dob.data
        student.gender = form.gender.data.strip()
        student.email = form.email.data.strip()
        student.guardian_phone = (form.guardian_phone.data or '').strip() or None

        if student.user:
            student.user.email = student.email

        stored = save_upload(
            request.files.get('profile_picture'), prefix=student.student_public_id
        )
        if stored:
            delete_upload(student.profile_picture)
            student.profile_picture = stored

        # keep the student's class in step with the Class table
        chosen = (form.class_name.data or '').strip()
        if chosen:
            cls = Class.query.filter(Class.class_name.ilike(chosen)).first()
            student.class_id = cls.id if cls else None

        # a senior leaving the SS classes should lose their department record
        if student.class_rel and not student.class_rel.class_name.upper().startswith('SS'):
            if student.senior_profile:
                db.session.delete(student.senior_profile[0])
        elif student.class_rel and form.department.data:
            existing = student.senior_profile[0] if student.senior_profile else None
            if existing:
                existing.department = form.department.data.strip()
            else:
                db.session.add(SeniorStudent(
                    student_id=student.id, department=form.department.data.strip()
                ))

        db.session.commit()
        flash('Student updated.', 'success')
        return redirect(url_for('admin.students'))

    return render_template(
        'admin/edit_student.html', form=form, student=student
    )


@admin_bp.route('/students/<int:id>/delete', methods=['POST'])
@login_required
def delete_student(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    for r in student.results:
        db.session.delete(r)
    for s in student.assignment_scores:
        db.session.delete(s)
    if student.senior_profile:
        db.session.delete(student.senior_profile[0])
    delete_upload(student.profile_picture)
    user = db.session.get(User, student.user_id)
    db.session.delete(student)
    if user:
        db.session.delete(user)
    db.session.commit()
    flash(f'{student.name} deleted.', 'info')
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/reset-password', methods=['POST'])
@login_required
def reset_student_password(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    if not student.user:
        flash('This student has no linked login account.', 'danger')
        return redirect(url_for('admin.students'))

    new_password = generate_password()
    student.user.password_hash = generate_password_hash(new_password)
    student.user.must_change_password = True
    db.session.commit()
    flash(
        f'Password reset for {student.name}. '
        f'New temporary password: {new_password}',
        'success',
    )
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/promote', methods=['POST'])
@login_required
def promote_student(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    if not student.class_rel:
        flash('This student is not assigned to a class.', 'warning')
        return redirect(url_for('admin.students'))

    current = student.class_rel.class_name
    next_id = get_next_class(current)
    if not next_id:
        flash(f'{student.name} has already completed {current}.', 'info')
        return redirect(url_for('admin.students'))

    student.class_id = next_id
    promoted = db.session.get(Class, next_id)
    if promoted and promoted.class_name.upper().startswith('SS'):
        _ensure_senior(student)
    db.session.commit()
    flash(
        f'{student.name} promoted from {current} to {promoted.class_name}.',
        'success',
    )
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/<int:id>/demote', methods=['POST'])
@login_required
def demote_student(id):
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(id)
    if not student.class_rel:
        flash('This student is not assigned to any class.', 'warning')
        return redirect(url_for('admin.classes'))

    current = student.class_rel.class_name
    previous_id = get_previous_class(current)
    if not previous_id:
        flash(
            f'{student.name} is already in the lowest class ({current}).',
            'warning',
        )
        return redirect(url_for('admin.class_detail', id=student.class_id))

    student.class_id = previous_id
    # drop the senior record once the student leaves the SS classes
    if student.senior_profile and not current.upper().startswith('SS'):
        db.session.delete(student.senior_profile[0])
    db.session.commit()
    flash(f'{student.name} demoted from {current}.', 'success')
    return redirect(url_for('admin.class_detail', id=student.class_id))


# ------------------------------------------------------------------ teachers

@admin_bp.route('/teachers')
@login_required
def teachers():
    denied = _require_admin()
    if denied:
        return denied

    search = request.args.get('search', '').strip()
    query = Teacher.query
    if search:
        query = query.filter(
            Teacher.name.ilike(f'%{search}%')
            | Teacher.staff_id.ilike(f'%{search}%')
            | Teacher.phone.ilike(f'%{search}%')
        )
    rows = query.order_by(Teacher.name.asc()).all()
    return render_template('admin/teachers.html', teachers=rows, search=search)


@admin_bp.route('/teachers/add', methods=['GET', 'POST'])
@login_required
def add_teacher():
    """Add a teacher with only name, phone number and class.

    Staff ID, email and login password are all generated here, so the admin
    never has to invent them. The generated credentials are shown once in
    the confirmation message.
    """
    denied = _require_admin()
    if denied:
        return denied

    form = TeacherForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        staff_id = unique_staff_id(name)
        email = unique_email(name)
        # deterministic, so it can be shown to the teacher on demand without
        # ever storing it in the database
        init_password = derive_staff_password(name)

        # class is optional - non-teaching staff simply leave it blank
        chosen = (form.class_name.data or '').strip()
        cls = (
            Class.query.filter(Class.class_name.ilike(chosen)).first()
            if chosen else None
        )

        user = User(
            email=email,
            password_hash=generate_password_hash(init_password),
            role='teacher',
            # the name-derived password is temporary; the teacher picks their own
            must_change_password=True,
        )
        db.session.add(user)
        db.session.flush()

        teacher = Teacher(
            user_id=user.id,
            staff_id=staff_id,
            name=name,
            gender='',
            email=email,
            phone=form.phone.data.strip(),
            class_name=cls.class_name if cls else None,
            profile_picture=save_upload(
                request.files.get('profile_picture'), prefix=staff_id
            ),
        )
        db.session.add(teacher)
        db.session.flush()

        # make them class teacher of the class they were added with
        if cls and cls.teacher_id is None:
            cls.teacher_id = teacher.id

        db.session.commit()
        flash(
            f'{name} added. Login: {email}  |  Staff ID: {staff_id}  |  '
            f'Password: {init_password}',
            'success',
        )
        return redirect(url_for('admin.teachers'))

    return render_template('admin/add_teacher.html', form=form)


@admin_bp.route('/teachers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_teacher(id):
    denied = _require_admin()
    if denied:
        return denied

    teacher = Teacher.query.get_or_404(id)
    form = AdminEditTeacherForm(obj=teacher)
    if teacher.class_name and form.class_name.data != teacher.class_name:
        form.class_name.data = teacher.class_name

    if form.validate_on_submit():
        clash = User.query.filter(
            User.email == form.email.data.strip(), User.id != teacher.user_id
        ).first()
        if clash:
            flash('That email address is already in use.', 'danger')
            return render_template('admin/edit_teacher.html', form=form, teacher=teacher)

        teacher.name = form.name.data.strip()
        teacher.staff_id = form.staff_id.data.strip()
        teacher.email = form.email.data.strip()
        teacher.phone = (form.phone.data or '').strip() or None
        teacher.dob = form.dob.data
        teacher.gender = (form.gender.data or '').strip() or None
        # keep the denormalised class name in step with the Class table so
        # a teacher listed against a class still shows it after an edit
        chosen = (form.class_name.data or '').strip()
        if chosen:
            cls = Class.query.filter(
                Class.class_name.ilike(chosen)
            ).first()
            teacher.class_name = cls.class_name if cls else chosen
        else:
            teacher.class_name = None

        if teacher.user:
            teacher.user.email = teacher.email

        stored = save_upload(
            request.files.get('profile_picture'), prefix=teacher.staff_id
        )
        if stored:
            delete_upload(teacher.profile_picture)
            teacher.profile_picture = stored

        db.session.commit()
        flash('Teacher updated.', 'success')
        return redirect(url_for('admin.teachers'))

    return render_template(
        'admin/edit_teacher.html', form=form, teacher=teacher
    )


@admin_bp.route('/teachers/<int:id>/delete', methods=['POST'])
@login_required
def delete_teacher(id):
    denied = _require_admin()
    if denied:
        return denied

    teacher = Teacher.query.get_or_404(id)

    # free up their class and remove the lesson plans they owned
    for cls in Class.query.filter_by(teacher_id=teacher.id).all():
        cls.teacher_id = None
    for plan in LessonPlan.query.filter_by(teacher_id=teacher.id).all():
        db.session.delete(plan)
    delete_upload(teacher.profile_picture)

    user = db.session.get(User, teacher.user_id)
    db.session.delete(teacher)
    if user:
        db.session.delete(user)
    db.session.commit()
    flash(f'{teacher.name} deleted.', 'info')
    return redirect(url_for('admin.teachers'))


@admin_bp.route('/teachers/<int:id>/reset-password', methods=['POST'])
@login_required
def reset_teacher_password(id):
    denied = _require_admin()
    if denied:
        return denied

    teacher = Teacher.query.get_or_404(id)
    if not teacher.user:
        flash('This teacher has no linked login account.', 'danger')
        return redirect(url_for('admin.teachers'))

    new_password = derive_staff_password(teacher.name)
    teacher.user.password_hash = generate_password_hash(new_password)
    # a reset puts them back on the school-issued password
    teacher.user.must_change_password = True
    db.session.commit()
    flash(
        f'Password reset for {teacher.name}. '
        f'Their password is now: {new_password}',
        'success',
    )
    return redirect(url_for('admin.teachers'))


# ------------------------------------------------------------------- classes

@admin_bp.route('/classes')
@login_required
def classes():
    denied = _require_admin()
    if denied:
        return denied

    rows = Class.query.all()
    # display in promotion order rather than alphabetically, so JSS2 lands
    # between JSS1 and JSS3 instead of after SS3
    order = list(PROMOTION_MAP.keys())
    rows.sort(key=lambda c: (order.index(c.class_name) if c.class_name in order else 99,
                             c.class_name))
    return render_template('admin/classes.html', classes=rows)


@admin_bp.route('/classes/add', methods=['GET', 'POST'])
@login_required
def add_class():
    denied = _require_admin()
    if denied:
        return denied

    form = ClassForm()
    form.teacher_id.choices = _teacher_choices()

    if form.validate_on_submit():
        if Class.query.filter(
            Class.class_name.ilike(form.class_name.data.strip())
        ).first():
            flash('A class with that name already exists.', 'warning')
            return render_template('admin/add_class.html', form=form)

        teacher_id = form.teacher_id.data if form.teacher_id.data != 0 else None
        if teacher_id and Class.query.filter_by(teacher_id=teacher_id).first():
            flash('That teacher is already assigned to another class.', 'warning')
            return render_template('admin/add_class.html', form=form)

        db.session.add(Class(
            class_name=form.class_name.data.strip(),
            teacher_id=teacher_id,
            description=(form.description.data or '').strip() or None,
        ))
        db.session.commit()
        flash('Class added.', 'success')
        return redirect(url_for('admin.classes'))

    return render_template('admin/add_class.html', form=form)


@admin_bp.route('/classes/<int:id>')
@login_required
def class_detail(id):
    denied = _require_admin()
    if denied:
        return denied

    cls = Class.query.get_or_404(id)
    rows = Student.query.filter_by(class_id=id).order_by(Student.name.asc()).all()
    return render_template('admin/class_detail.html', cls=cls, students=rows)


@admin_bp.route('/classes/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_class(id):
    denied = _require_admin()
    if denied:
        return denied

    cls = Class.query.get_or_404(id)
    form = ClassForm(obj=cls)
    form.teacher_id.choices = _teacher_choices()

    if form.validate_on_submit():
        existing = Class.query.filter(
            Class.class_name.ilike(form.class_name.data.strip()), Class.id != id
        ).first()
        if existing:
            flash('A class with that name already exists.', 'warning')
            return render_template('admin/edit_class.html', form=form, cls=cls)

        teacher_id = form.teacher_id.data if form.teacher_id.data != 0 else None
        if teacher_id:
            taken = Class.query.filter_by(teacher_id=teacher_id).first()
            if taken and taken.id != id:
                flash('That teacher is already assigned to another class.', 'warning')
                return render_template('admin/edit_class.html', form=form, cls=cls)

        cls.class_name = form.class_name.data.strip()
        cls.teacher_id = teacher_id
        cls.description = (form.description.data or '').strip() or None
        db.session.commit()
        flash('Class updated.', 'success')
        return redirect(url_for('admin.classes'))

    return render_template('admin/edit_class.html', form=form, cls=cls)


@admin_bp.route('/classes/<int:id>/delete', methods=['POST'])
@login_required
def delete_class(id):
    denied = _require_admin()
    if denied:
        return denied

    cls = Class.query.get_or_404(id)
    for student in Student.query.filter_by(class_id=id).all():
        student.class_id = None
    # detach anything else pointing here so no orphan rows are left behind
    for assignment in Assignment.query.filter_by(class_id=id).all():
        db.session.delete(assignment)
    for plan in LessonPlan.query.filter_by(class_id=id).all():
        plan.class_id = None
    db.session.delete(cls)
    db.session.commit()
    flash(f'{cls.class_name} deleted. Its students are now unassigned.', 'info')
    return redirect(url_for('admin.classes'))


# ------------------------------------------------------------------- results

@admin_bp.route('/results')
@login_required
def manage_results():
    denied = _require_admin()
    if denied:
        return denied

    search = request.args.get('search', '').strip()
    query = Student.query
    if search:
        query = query.filter(
            Student.name.ilike(f'%{search}%')
            | Student.student_public_id.ilike(f'%{search}%')
        )
    rows = query.order_by(Student.name.asc()).all()
    return render_template('admin/results.html', students=rows, search=search)


@admin_bp.route('/results/add/<int:student_id>', methods=['GET', 'POST'])
@login_required
def add_result(student_id):
    """Pick a term first, then enter the marks for that term.

    Previously this jumped straight to the subject entry page, so there was
    no way to choose which term you were entering - you landed on a blank
    form with no term selector at all. The term is now a required first step,
    carried in the URL so a given term is bookmarkable and re-openable.
    """
    denied = _require_admin()
    if denied:
        return denied

    student = Student.query.get_or_404(student_id)

    if not student.class_rel:
        flash('Assign this student to a class before entering results.', 'warning')
        return redirect(url_for('admin.students'))

    department = None
    if student.senior_profile:
        department = student.senior_profile[0].department

    class_name = student.class_rel.class_name
    subjects = get_subjects_for_class(class_name, department)

    # every term that already has a result for this student, with progress
    term_rows = []
    for term_value, _ in TERM_CHOICES:
        done = Result.query.filter_by(
            student_id=student.id, term=term_value
        ).count()
        term_rows.append({'term': term_value, 'done': done, 'total': len(subjects)})

    form = ResultForm()
    if form.validate_on_submit():
        chosen_term = (form.term.data or '').strip()
        if not chosen_term:
            flash('Choose a term first.', 'warning')
            return render_template(
                'admin/add_result.html', form=form, student=student,
                subjects=None, term=None, existing=[], term_rows=term_rows,
                subjects_count=len(subjects), class_name=class_name,
            )
        return redirect(url_for(
            'admin.add_result', student_id=student.id, term=chosen_term
        ))

    chosen_term = (request.args.get('term') or '').strip()
    if not chosen_term:
        # first step: choose the term
        form.class_name.data = class_name
        return render_template(
            'admin/add_result.html', form=form, student=student,
            subjects=None, term=None, existing=[], term_rows=term_rows,
            subjects_count=len(subjects), class_name=class_name,
        )

    # second step: enter the marks for the chosen term, pre-filled with
    # anything already recorded so nothing is typed twice
    existing = Result.query.filter_by(
        student_id=student.id, class_name=class_name, term=chosen_term
    ).all()
    existing_by_subject = {r.subject: r for r in existing}
    form.term.data = chosen_term
    form.class_name.data = class_name

    return render_template(
        'admin/add_result.html', form=form, student=student,
        subjects=subjects, term=chosen_term, existing=existing,
        existing_by_subject=existing_by_subject,
        term_rows=term_rows, subjects_count=len(subjects), class_name=class_name,
    )


def _maybe_promote(student, class_name, term, department):
    """Promote at the end of Term 3, but only once every subject for the
    class has a stored result.

    Partial entry is still fully supported - it simply does not promote anyone.
    """
    current_class = student.class_rel.class_name if student.class_rel else ''
    required = get_subjects_for_class(current_class, department)

    # count marks against the class the student is actually sitting in, so a
    # re-save after promotion cannot re-trigger or double-count
    stored = Result.query.filter_by(
        student_id=student.id, class_name=current_class, term=term
    ).count()

    if not required:
        flash(
            f'No subjects are defined for {current_class}, so there is nothing '
            f'to promote on. Add subjects to the class first.',
            'warning',
        )
        return False

    if stored < len(required):
        flash(
            f'End of Term 3: {stored} of {len(required)} subjects recorded. '
            f'No promotion yet - keep entering the remaining subjects.',
            'info',
        )
        return False

    next_name = PROMOTION_MAP.get(current_class)
    if not next_name:
        _ensure_senior(student)
        db.session.commit()
        flash(f'{student.name} has completed SS3 and graduated.', 'info')
        return False

    next_cls = Class.query.filter(Class.class_name.ilike(next_name.strip())).first()
    if not next_cls:
        # the class does not exist yet - do NOT silently move the student
        # somewhere unintended
        flash(
            f'{student.name} finished {current_class}, but the next class '
            f'"{next_name}" has not been created yet. '
            f'Create the class, then promote the student.',
            'warning',
        )
        return False

    if student.class_id == next_cls.id:
        # already promoted by an earlier save in this same term
        return False

    old_name = current_class
    student.class_id = next_cls.id

    # a senior record only belongs to SS1-SS3; drop it when leaving that band
    if DEMOTION_MAP.get(next_name) != 'JSS3' and student.senior_profile:
        for profile in student.senior_profile:
            db.session.delete(profile)

    db.session.commit()
    flash(
        f'{student.name} has been promoted from {old_name} to {next_name}.',
        'success',
    )
    return True


@admin_bp.route('/results/save', methods=['POST'])
@login_required
def save_results():
    """Save exam results for one student.

    Partial entry is intentional and preserved: a blank cell means "no mark
    entered for this subject yet", so a student who sat only some exams still
    gets results for the subjects they did complete. Subjects that already
    have a row are updated in place; nothing is ever deleted.
    """
    denied = _require_admin()
    if denied:
        return denied

    student_id = request.form.get('student_id')
    class_name = (request.form.get('class_name') or '').strip()
    term = (request.form.get('term') or '').strip()

    student = Student.query.get_or_404(student_id)

    department = None
    if student.senior_profile:
        department = student.senior_profile[0].department

    subjects = get_subjects_for_class(
        student.class_rel.class_name if student.class_rel else '', department
    )

    saved_subjects = []
    errors = []

    for subject in subjects:
        key = subject.replace(' ', '_')
        test_value = (request.form.get(f'test_{key}') or '').strip()
        exam_value = (request.form.get(f'exam_{key}') or '').strip()

        # blank cell -> skip, leaving any previously saved mark untouched
        if not test_value or not exam_value:
            continue

        try:
            test_score = float(test_value)
            exam_score = float(exam_value)
        except ValueError:
            errors.append(f'{subject}: scores must be numbers.')
            continue

        if not (0 <= test_score <= 100) or not (0 <= exam_score <= 100):
            errors.append(f'{subject}: each score must be between 0 and 100.')
            continue

        total = test_score + exam_score
        if total > 100:
            errors.append(f'{subject}: test + exam cannot exceed 100.')
            continue

        row = Result.query.filter_by(
            student_id=student.id, subject=subject,
            class_name=class_name, term=term,
        ).first()

        if row:
            row.test_score = test_score
            row.exam_score = exam_score
            row.total_score = total
            row.percentage = total
            row.grade = grade_for(total)
        else:
            db.session.add(Result(
                student_id=student.id, subject=subject,
                test_score=test_score, exam_score=exam_score,
                total_score=total, percentage=total,
                grade=grade_for(total), class_name=class_name, term=term,
            ))
        saved_subjects.append(subject)

    for message in errors:
        flash(message, 'danger')

    if not saved_subjects:
        flash('No new results were saved.', 'warning')
        return redirect(url_for('admin.student_profile', id=student.id))

    db.session.commit()

    if term == 'Term 3' and student.class_rel:
        _maybe_promote(student, class_name, term, department)

    flash(
        f'Saved {len(saved_subjects)} subject(s): {", ".join(saved_subjects)}.',
        'success',
    )
    return redirect(url_for('admin.student_profile', id=student.id))


# -------------------------------------------------------- senior departments

@admin_bp.route('/seniors', methods=['GET', 'POST'])
@login_required
def seniors():
    denied = _require_admin()
    if denied:
        return denied

    form = SeniorDeptForm()
    rows = (
        SeniorStudent.query.join(Student).join(Class)
        .filter(Class.class_name.like('SS%')).all()
    )

    if form.validate_on_submit():
        stu = Student.query.filter_by(
            student_public_id=form.student_public_id.data.strip()
        ).first()
        if not stu:
            flash('Student ID not found.', 'warning')
            return render_template('admin/seniors.html', form=form, seniors=rows)
        if not stu.class_rel or not stu.class_rel.class_name.upper().startswith('SS'):
            flash('Only SS1-SS3 students can be assigned a department.', 'danger')
            return render_template('admin/seniors.html', form=form, seniors=rows)

        existing = SeniorStudent.query.filter_by(student_id=stu.id).first()
        if existing:
            existing.department = form.department.data
        else:
            db.session.add(SeniorStudent(
                student_id=stu.id, department=form.department.data
            ))
        db.session.commit()
        flash('Senior department saved.', 'success')
        return redirect(url_for('admin.seniors'))

    return render_template('admin/seniors.html', form=form, seniors=rows)
