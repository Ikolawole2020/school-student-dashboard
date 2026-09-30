# blueprints/attendance/routes.py
"""Daily attendance register and the school holiday calendar.

A teacher marks their own class. A student sees their own record. An admin can
mark any class and manage the holiday list.
"""
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import AttendanceRecord, Student, Class, Holiday
from forms import (
    AttendanceForm, HolidayForm, ATTENDANCE_STATUSES, ATTENDANCE_ICONS,
)
from utils import (
    is_admin, is_teacher, current_student, current_teacher,
    attendance_summary, holiday_on, upcoming_holidays,
)
from . import attendance_bp

VALID_STATUSES = {s for s, _ in ATTENDANCE_STATUSES}


def _forbidden():
    return render_template('errors/403.html'), 403


def _class_ids_teacher_may_use(teacher):
    if not teacher:
        return []
    return [c.id for c in Class.query.filter_by(teacher_id=teacher.id).all()]


def _parse_date(raw, fallback=None):
    if raw:
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            pass
    return fallback or date.today()


def _may_use_class(class_id, teacher):
    """Admins any class; a teacher only their own."""
    if is_admin():
        return True
    return class_id in _class_ids_teacher_may_use(teacher)


# ------------------------------------------------------------------ register

@attendance_bp.route('/')
@login_required
def index():
    """Landing page: pick a class and a date."""
    if not (is_admin() or is_teacher()):
        return redirect(url_for('attendance.my'))

    teacher = current_teacher()
    today = _parse_date(request.args.get('date'))
    if is_admin():
        classes = Class.query.order_by(Class.class_name).all()
    else:
        classes = (
            Class.query.filter_by(teacher_id=teacher.id)
            .order_by(Class.class_name).all()
            if teacher else []
        )
    return render_template(
        'attendance/index.html', classes=classes, teacher=teacher,
        today=today, holiday=holiday_on(today),
        upcoming=upcoming_holidays(6),
    )


@attendance_bp.route('/register/<int:class_id>', methods=['GET', 'POST'])
@login_required
def register(class_id):
    """Mark, or correct, one day's register for one class."""
    if not (is_admin() or is_teacher()):
        return _forbidden()
    teacher = current_teacher()
    if not _may_use_class(class_id, teacher):
        return _forbidden()

    cls = Class.query.get_or_404(class_id)
    students = Student.query.filter_by(class_id=class_id).order_by(
        Student.name
    ).all()

    form = AttendanceForm()
    chosen = _parse_date(request.values.get('record_date'))

    if request.method == 'POST' and form.validate_on_submit():
        chosen = form.record_date.data
        return _save_register(cls, students, chosen, teacher)

    holiday = holiday_on(chosen)
    existing = {
        r.student_id: r for r in AttendanceRecord.query.filter_by(
            class_id=class_id, record_date=chosen
        ).all()
    }
    # the previous day, offered as a starting point for a busy register
    yesterday = {
        r.student_id: r for r in AttendanceRecord.query.filter_by(
            class_id=class_id, record_date=chosen - timedelta(days=1)
        ).all()
    }

    return render_template(
        'attendance/register.html',
        cls=cls, students=students, form=form, chosen=chosen,
        existing=existing, yesterday=yesterday, holiday=holiday,
        statuses=ATTENDANCE_STATUSES, icons=ATTENDANCE_ICONS,
        summary=attendance_summary(list(existing.values())),
        marked_count=len(existing),
    )


def _save_register(cls, students, chosen, teacher):
    """Persist the register, leaving untouched students alone.

    Mirrors the forgiving behaviour of exam results: a student with nothing
    selected keeps whatever was already recorded, so a teacher can correct one
    pupil without re-entering the whole class.
    """
    saved = 0
    for student in students:
        status = (request.form.get(f'status_{student.id}') or '').strip()
        remark = (request.form.get(f'remark_{student.id}') or '').strip()[:200]
        if status not in VALID_STATUSES:
            continue

        row = AttendanceRecord.query.filter_by(
            student_id=student.id, record_date=chosen
        ).first()
        if row:
            row.status = status
            row.remark = remark or None
            row.class_id = cls.id
            row.marked_by = teacher.id if teacher else None
            row.marked_at = datetime.utcnow()
        else:
            db.session.add(AttendanceRecord(
                student_id=student.id, class_id=cls.id,
                record_date=chosen, status=status, remark=remark or None,
                marked_by=teacher.id if teacher else None,
            ))
        saved += 1

    db.session.commit()
    flash(
        f'Register saved for {cls.class_name} on '
        f'{chosen.strftime("%d %b %Y")} — {saved} student'
        f'{"" if saved == 1 else "s"}.',
        'success',
    )
    return redirect(url_for(
        'attendance.register', class_id=cls.id,
        record_date=chosen.isoformat(),
    ))



@attendance_bp.route('/delete/<int:class_id>', methods=['POST'])
@login_required
def delete_register(class_id):
    """Remove a whole day's register - useful when it was marked by mistake."""
    if not (is_admin() or is_teacher()):
        return _forbidden()
    if not _may_use_class(class_id, current_teacher()):
        return _forbidden()

    chosen = _parse_date(request.form.get('record_date'))
    rows = AttendanceRecord.query.filter_by(
        class_id=class_id, record_date=chosen
    ).all()
    for r in rows:
        db.session.delete(r)
    db.session.commit()
    flash(
        f'Cleared {len(rows)} record(s) for {chosen.strftime("%d %b %Y")}.',
        'info',
    )
    return redirect(url_for('attendance.register', class_id=class_id))


@attendance_bp.route('/my')
@login_required
def my():
    """A student's own attendance history."""
    if current_user.role != 'student':
        return _forbidden()
    student = current_student()
    if not student:
        flash('No student profile is linked to this account.', 'danger')
        return redirect(url_for('auth.logout'))

    since = _parse_date(
        request.args.get('since'), date.today() - timedelta(days=30)
    )
    records = (
        AttendanceRecord.query
        .filter_by(student_id=student.id)
        .filter(AttendanceRecord.record_date >= since)
        .order_by(AttendanceRecord.record_date.desc())
        .all()
    )
    return render_template(
        'attendance/my.html', student=student, records=records,
        summary=attendance_summary(records), since=since,
        icons=ATTENDANCE_ICONS,
    )


# ------------------------------------------------------------------ holidays

@attendance_bp.route('/holidays')
@login_required
def holidays():
    """The school holiday calendar, visible to every signed-in role."""
    rows = (
        Holiday.query.order_by(Holiday.holiday_date.asc()).all()
    )
    today = date.today()
    return render_template(
        'attendance/holidays.html', holidays=rows, today=today,
        holiday_on=holiday_on(today), can_manage=is_admin(),
    )


@attendance_bp.route('/holidays/add', methods=['GET', 'POST'])
@login_required
def add_holiday():
    if not is_admin():
        return _forbidden()
    form = HolidayForm()
    if form.validate_on_submit():
        db.session.add(Holiday(
            name=form.name.data.strip(),
            holiday_date=form.holiday_date.data,
            is_public=bool(form.is_public.data),
            description=(form.description.data or '').strip() or None,
        ))
        db.session.commit()
        flash('Holiday added to the calendar.', 'success')
        return redirect(url_for('attendance.holidays'))
    return render_template('attendance/holiday_form.html', form=form, holiday=None)


@attendance_bp.route('/holidays/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_holiday(id):
    if not is_admin():
        return _forbidden()
    holiday = db.session.get(Holiday, id) or abort(404)
    form = HolidayForm(obj=holiday)
    if form.validate_on_submit():
        holiday.name = form.name.data.strip()
        holiday.holiday_date = form.holiday_date.data
        holiday.is_public = bool(form.is_public.data)
        holiday.description = (form.description.data or '').strip() or None
        db.session.commit()
        flash('Holiday updated.', 'success')
        return redirect(url_for('attendance.holidays'))
    return render_template(
        'attendance/holiday_form.html', form=form, holiday=holiday
    )


@attendance_bp.route('/holidays/<int:id>/delete', methods=['POST'])
@login_required
def delete_holiday(id):
    if not is_admin():
        return _forbidden()
    holiday = db.session.get(Holiday, id) or abort(404)
    name = holiday.name
    db.session.delete(holiday)
    db.session.commit()
    flash(f'"{name}" removed from the calendar.', 'info')
    return redirect(url_for('attendance.holidays'))
