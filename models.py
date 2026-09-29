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
    students = db.relationship('Student', backref='student_class', overlaps="class_rel")

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
    """An assignment posted by a teacher for a specific class."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    subject = db.Column(db.String(80), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    max_score = db.Column(db.Float, default=100.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class_rel = db.relationship('Class', backref='assignments')
    teacher = db.relationship('Teacher', backref='assignments')
    scores = db.relationship(
        'AssignmentScore', backref='assignment', cascade='all, delete-orphan'
    )

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
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
