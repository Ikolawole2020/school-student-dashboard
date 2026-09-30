# models.py
from datetime import datetime
from flask_login import UserMixin
from extensions import db

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='student')  # 'admin','teacher','student'
    is_active = db.Column(db.Boolean, default=True)
    # Set when an account is created with a school-issued password (derived
    # from the name, or generated). The user must replace it before they can
    # reach the rest of the app.
    must_change_password = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_public_id = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    profile_picture = db.Column(db.String(200))
    dob = db.Column(db.Date)
    gender = db.Column(db.String(10), nullable=False)
    guardian_phone = db.Column(db.String(20))
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    email = db.Column(db.String(120), unique=True)
    user = db.relationship('User', backref='student_profile')
    class_rel = db.relationship('Class', backref='class_students', overlaps="student_class,class_students")

class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.Date)
    # nullable because the add-teacher form only asks for name, phone and
    # class; gender is filled in later from the edit form if it is known
    gender = db.Column(db.String(10))
    class_name = db.Column(db.String(50))
    profile_picture = db.Column(db.String(200))
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    user = db.relationship('User', backref='teacher_profile')

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50), unique=True, nullable=False)  # e.g. "JSS1A", "SS2B"
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    description = db.Column(db.String(200))
    teacher = db.relationship('Teacher', backref='class_teacher')
    # viewonly: student.class_id is written directly by the routes, and
    # Student.class_rel is the relationship used for reading. Without
    # viewonly, SQLAlchemy warns that two relationships both write the FK.
    students = db.relationship(
        'Student', backref='student_class', viewonly=True, overlaps="class_rel"
    )

class SeniorStudent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    department = db.Column(db.String(50))  # "Science", "Arts", "Commercial"
    student = db.relationship('Student', backref='senior_profile')

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)  # e.g. "JSS1"
    term = db.Column(db.String(10), nullable=False)  # e.g. "Term 1"
    subject = db.Column(db.String(80), nullable=False)
    test_score = db.Column(db.Float, nullable=False, default=0)
    exam_score = db.Column(db.Float, nullable=False, default=0)
    total_score = db.Column(db.Float, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(5), nullable=False)
    student = db.relationship('Student', backref='results')

class Assignment(db.Model):
    """An assignment posted by a teacher.

    class_name is free text so a teacher can post to any class they teach,
    including one not yet created in the Class table. class_id is filled in
    too when the typed name matches a real class, which keeps the student
    "my assignments" view and class filtering working.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    subject = db.Column(db.String(80), nullable=False)
    class_name = db.Column(db.String(50))
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    max_score = db.Column(db.Float, default=100.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class_rel = db.relationship('Class', backref='assignments')
    teacher = db.relationship('Teacher', backref='assignments')
    scores = db.relationship(
        'AssignmentScore', backref='assignment', cascade='all, delete-orphan'
    )
    media = db.relationship(
        'AssignmentMedia', backref='assignment', cascade='all, delete-orphan'
    )


class AssignmentMedia(db.Model):
    """Media attached to an assignment by the teacher.

    Not every assignment can be explained in words - some need a photo of a
    question on the board, a diagram, or a scanned sheet.
    """
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey('assignment.id'), nullable=False
    )
    filename = db.Column(db.String(200), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class AssignmentSubmission(db.Model):
    """A student's answer to an assignment, uploaded as images.

    One row per student per assignment; the images themselves live in
    AssignmentSubmissionFile.
    """
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey('assignment.id'), nullable=False
    )
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    note = db.Column(db.String(500))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignment = db.relationship('Assignment', backref='submissions')
    student = db.relationship('Student', backref='assignment_submissions')
    files = db.relationship(
        'AssignmentSubmissionFile', backref='submission',
        cascade='all, delete-orphan',
    )


class AssignmentSubmissionFile(db.Model):
    """One image in a student's submitted answer."""
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(
        db.Integer, db.ForeignKey('assignment_submission.id'), nullable=False
    )
    filename = db.Column(db.String(200), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class AttendanceRecord(db.Model):
    """One student's attendance on one day, for one class.

    Unique per (student, date) so a register is never double-counted; marking
    again simply updates the status.
    """
    __table_args__ = (
        db.UniqueConstraint('student_id', 'record_date', name='uq_attendance_student_day'),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    record_date = db.Column(db.Date, nullable=False)
    # 'present' | 'absent' | 'late' | 'excused'
    status = db.Column(db.String(10), default='present', nullable=False)
    remark = db.Column(db.String(200))
    marked_by = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('Student', backref='attendance_records')
    class_rel = db.relationship('Class', backref='attendance_records')
    marker = db.relationship('Teacher', backref='attendance_marked')


class Holiday(db.Model):
    """A school holiday, public or internal.

    Stored once so the calendar, dashboards and the attendance register can all
    refer to the same record instead of each inventing its own.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    holiday_date = db.Column(db.Date, nullable=False)
    # True for national/public holidays, False for school-internal closures
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_upcoming(self):
        from datetime import date
        return self.holiday_date >= date.today()

class AssignmentScore(db.Model):
    """A single student's score for one assignment. Nullable so a student
    who did not sit the assignment simply has no row."""
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey('assignment.id'), nullable=False
    )
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    score = db.Column(db.Float, nullable=True)
    feedback = db.Column(db.String(300))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = db.relationship('Student', backref='assignment_scores')

class LessonPlan(db.Model):
    """A weekly lesson plan. A teacher owns their own plans; admins see all.

    class_name is stored as free text because teachers may plan for a class
    that is not yet set up in the Class table. When the typed name matches an
    existing class, class_id is also filled in so the plan can be filtered and
    displayed alongside real class records.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    class_name = db.Column(db.String(50))
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    week_of = db.Column(db.Date, nullable=True)
    objectives = db.Column(db.Text)
    activities = db.Column(db.Text)
    resources = db.Column(db.Text)
    homework = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class_rel = db.relationship('Class', backref='lesson_plans')
    teacher = db.relationship('Teacher', backref='lesson_plans')
    images = db.relationship(
        'LessonPlanImage', backref='lesson_plan', cascade='all, delete-orphan'
    )


class LessonPlanImage(db.Model):
    """An image attached to a lesson plan - worksheets, diagrams, and so on.

    Kept in a child table rather than a column so a plan can carry any number
    of images.
    """
    id = db.Column(db.Integer, primary_key=True)
    lesson_plan_id = db.Column(
        db.Integer, db.ForeignKey('lesson_plan.id'), nullable=False
    )
    filename = db.Column(db.String(200), nullable=False)
    caption = db.Column(db.String(150))


class Post(db.Model):
    """A news post or announcement shown on the public school page.

    Drafts stay hidden until published_at is set, so an admin can write ahead
    of time and the post appears on its scheduled day.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    summary = db.Column(db.String(300))
    body = db.Column(db.Text)
    # 'news' | 'announcement' | 'event' | 'achievement'
    category = db.Column(db.String(20), default='news', nullable=False)
    cover_image = db.Column(db.String(200))
    author = db.Column(db.String(120))
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    views = db.Column(db.Integer, default=0, nullable=False)
    published_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images = db.relationship(
        'PostImage', backref='post', cascade='all, delete-orphan',
        order_by='PostImage.id',
    )

    @property
    def reading_minutes(self):
        words = len((self.body or '').split())
        return max(1, round(words / 200))

    @property
    def preview(self):
        """First ~40 words, for card summaries."""
        return ' '.join((self.body or '').split()[:40])


class PostImage(db.Model):
    """A gallery image inside a post."""
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    caption = db.Column(db.String(150))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Testimonial(db.Model):
    """A quote from a parent, student or staff member, shown on the home page."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    # 'Parent' | 'Student' | 'Teacher' | 'Alumnus'
    role = db.Column(db.String(40), default='Parent', nullable=False)
    quote = db.Column(db.Text, nullable=False)
    avatar = db.Column(db.String(200))
    rating = db.Column(db.Integer, default=5, nullable=False)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def stars(self):
        return range(max(0, min(5, self.rating or 5)))

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
