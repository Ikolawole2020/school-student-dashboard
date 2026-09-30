# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, SelectField, DateField,
    FloatField, FileField, TextAreaField, MultipleFileField, BooleanField,
    IntegerField,
)
from wtforms.validators import (
    DataRequired, Email, Length, Optional, NumberRange, Regexp, EqualTo,
)


class FileSize:
    """Rejects uploaded files larger than `max_size` bytes.

    WTForms 3.1 ships no FileSize validator, and Flask's MAX_CONTENT_LENGTH
    only guards the whole request. Applied per file so one oversized image
    cannot silently block an otherwise valid multi-file upload.
    """

    def __init__(self, max_size=4 * 1024 * 1024, message=None):
        self.max_size = max_size
        self.message = message or (
            f'Each image must be under {max_size // (1024 * 1024)}MB.'
        )

    def __call__(self, form, field):
        files = field.data or []
        if not isinstance(files, list):
            files = [files]
        for file in files:
            stream = getattr(file, 'stream', None)
            # read the stream length without consuming it
            length = getattr(stream, 'content_length', None)
            if length is None:
                length = getattr(file, 'content_length', 0)
            if length and length > self.max_size:
                raise ValueError(self.message)

CLASS_CHOICES = [
    ('Creche', 'Creche'),
    ('KG', 'KG'),
    ('Nursery 1', 'Nursery 1'), ('Nursery 2', 'Nursery 2'),
    ('Basic 1', 'Basic 1'), ('Basic 2', 'Basic 2'), ('Basic 3', 'Basic 3'),
    ('Basic 4', 'Basic 4'), ('Basic 5', 'Basic 5'),
    ('JSS1', 'JSS1'), ('JSS2', 'JSS2'), ('JSS3', 'JSS3'),
    ('SS1', 'SS1'), ('SS2', 'SS2'), ('SS3', 'SS3'),
]

DEPARTMENT_CHOICES = [
    ('', '-- Select Department --'),
    ('Science', 'Science'), ('Arts', 'Arts'), ('Commercial', 'Commercial'),
]

TERM_CHOICES = [
    ('Term 1', 'Term 1'), ('Term 2', 'Term 2'), ('Term 3', 'Term 3'),
]

# Nigerian-style numbers, tolerant of spaces, dashes and a +234 prefix.
PHONE_VALIDATOR = Regexp(
    r'^\+?234?[0-9\s\-()]{7,20}$|^0[0-9\s\-()]{7,15}$',
    message='Enter a valid phone number.',
)


def class_choices():
    """Read the Class table in the caller's existing app context.

    Earlier versions of this module called create_app() from inside each
    form's __init__ purely to populate choices. That rebuilt the whole
    application (and re-ran db.create_all()) on every form instantiation and
    created a circular import between app and forms. Routes always run inside
    an app context already, so this is all that is needed.
    """
    from models import Class
    return Class.query.order_by(Class.class_name.asc()).all()


class ClassChoicesMixin:
    """Populates SelectFields from the Class table on instantiation."""

    #: names of the SelectField attributes on this form to populate
    class_choice_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "-- Select Class --")] + [
            (c.class_name, c.class_name) for c in class_choices()
        ]
        for field_name in self.class_choice_fields:
            field = getattr(self, field_name)
            current = getattr(field, "data", None)
            field.choices = choices
            # preserve a still-valid selection after a failed re-submit
            if current and any(c[0] == current for c in choices):
                field.data = current


class ClassIdChoicesMixin:
    """Populates a SelectField from the Class table using class *IDs*.

    Needed for fields that store a foreign key (e.g. LessonPlanForm.class_id),
    as opposed to ClassChoicesMixin which supplies class *names* for the
    denormalised class_name columns.
    """

    class_id_choice_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(0, "-- Select Class --")] + [
            (c.id, c.class_name) for c in class_choices()
        ]
        for field_name in self.class_id_choice_fields:
            field = getattr(self, field_name)
            current = field.data
            field.choices = choices
            # The placeholder must be 0 rather than '' because coerce=int
            # raises ValueError on '' while WTForms renders the choices.
            # Optional fields treat 0 as "nothing selected".
            if not current:
                field.data = 0


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Login')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current password', validators=[DataRequired()])
    new_password = PasswordField(
        'New password',
        validators=[DataRequired(), Length(min=6, message='Use at least 6 characters.')],
    )
    confirm_password = PasswordField(
        'Confirm new password',
        validators=[DataRequired(), EqualTo('new_password', message='Passwords must match.')],
    )
    submit = SubmitField('Change password')



class StudentRegisterForm(FlaskForm):
    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    student_public_id = StringField('Student ID (Auto-generated)', render_kw={'readonly': True})
    dob = DateField('Date of birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    class_name = SelectField('Class', choices=CLASS_CHOICES, validators=[DataRequired()])
    department = SelectField('Department (for SS classes only)', choices=DEPARTMENT_CHOICES, validators=[Optional()])
    email = StringField('Email (Auto-generated)', render_kw={'readonly': True})
    guardian_phone = StringField(
        'Guardian phone number', validators=[Optional(), PHONE_VALIDATOR]
    )
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    profile_picture = FileField('Profile picture')
    submit = SubmitField('Register')


class AdminAddStudentForm(ClassChoicesMixin, FlaskForm):
    class_choice_fields = ('class_name',)

    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    student_public_id = StringField('Student ID (Auto-generated)', render_kw={'readonly': True})
    dob = DateField('Date of birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    class_name = SelectField('Class', choices=[], validators=[DataRequired()])
    department = SelectField('Department (for SS classes only)', choices=DEPARTMENT_CHOICES, validators=[Optional()])
    email = StringField('Email (Auto-generated)', render_kw={'readonly': True})
    guardian_phone = StringField('Guardian phone number', validators=[Optional(), PHONE_VALIDATOR])
    password = PasswordField('Initial password', validators=[Optional(), Length(min=6)])
    profile_picture = FileField('Profile picture')
    submit = SubmitField('Add student')


class AdminEditStudentForm(ClassChoicesMixin, FlaskForm):
    class_choice_fields = ('class_name',)

    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    student_public_id = StringField('Student ID', render_kw={'readonly': True})
    dob = DateField('Date of birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    class_name = SelectField('Class', choices=[], validators=[DataRequired()])
    department = SelectField('Department (for SS classes only)', choices=DEPARTMENT_CHOICES, validators=[Optional()])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    guardian_phone = StringField('Guardian phone number', validators=[Optional(), PHONE_VALIDATOR])
    profile_picture = FileField('Profile picture')
    submit = SubmitField('Update student')



class TeacherForm(ClassChoicesMixin, FlaskForm):
    """Deliberately minimal add-teacher form: name, phone number and class.

    Staff ID and email are derived from the name automatically and the account
    password is generated server-side, so an admin never has to invent them.

    Class is optional because plenty of staff do not manage a class (bursars,
    cooks, admin officers, substitutes). One can be assigned later from the
    edit form.
    """

    class_choice_fields = ('class_name',)

    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    phone = StringField('Phone number', validators=[DataRequired(), PHONE_VALIDATOR])
    class_name = SelectField(
        'Class (optional)', choices=[], validators=[Optional()]
    )
    submit = SubmitField('Add teacher')


class AdminEditTeacherForm(ClassChoicesMixin, FlaskForm):
    """Edit form for the full existing teacher record.

    Everything except name and email is optional, because the add-teacher form
    only collects a name and phone number.
    """

    class_choice_fields = ('class_name',)

    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    staff_id = StringField('Staff ID', validators=[DataRequired(), Length(max=20)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField('Phone number', validators=[Optional(), PHONE_VALIDATOR])
    dob = DateField('Date of birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField(
        'Gender',
        choices=[('', '-- Not specified --'), ('Male', 'Male'), ('Female', 'Female')],
        validators=[Optional()],
    )
    class_name = SelectField('Class', choices=[], validators=[Optional()])
    profile_picture = FileField('Profile picture')
    submit = SubmitField('Update teacher')



class ResultForm(ClassChoicesMixin, FlaskForm):
    class_choice_fields = ('class_name',)

    student_public_id = StringField('Student ID', validators=[DataRequired(), Length(max=20)])
    class_name = SelectField('Class', choices=[], validators=[DataRequired()])
    term = SelectField('Term', choices=TERM_CHOICES, validators=[DataRequired()])
    submit = SubmitField('Load Subjects')


class SubjectResultForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired(), Length(max=80)])
    test_score = FloatField('Test Score', validators=[Optional(), NumberRange(min=0, max=100)])
    exam_score = FloatField('Exam Score', validators=[Optional(), NumberRange(min=0, max=100)])


class SeniorDeptForm(FlaskForm):
    student_public_id = StringField('Student ID (SS1–SS3)', validators=[DataRequired(), Length(max=20)])
    department = SelectField('Department', choices=[
        ('Science', 'Science'), ('Arts', 'Arts'), ('Commercial', 'Commercial')
    ])
    submit = SubmitField('Set department')


class ClassForm(FlaskForm):
    class_name = StringField('Class Name', validators=[DataRequired(), Length(max=50)])
    teacher_id = SelectField('Class Teacher', coerce=int, validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Class')


class StudentProfileForm(FlaskForm):
    name = StringField('Full name', validators=[DataRequired(), Length(max=120)])
    dob = DateField('Date of birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    guardian_phone = StringField('Guardian phone number', validators=[Optional(), PHONE_VALIDATOR])
    profile_picture = FileField('Profile picture')
    submit = SubmitField('Update Profile')


class ViewResultForm(ClassChoicesMixin, FlaskForm):
    class_choice_fields = ('class_name',)

    class_name = SelectField('Class', choices=[], validators=[DataRequired()])
    term = SelectField('Term', choices=TERM_CHOICES, validators=[DataRequired()])
    submit = SubmitField('View Result')



# ------------------------------------------------------------- assignments

class AssignmentForm(FlaskForm):
    """Create/edit an assignment.

    Class and subject are plain text fields, not dropdowns: a teacher may need
    to post to a class that has not been created in the Class table yet, and
    not every subject in the school is in the built-in subject list.
    """

    title = StringField('Assignment title', validators=[DataRequired(), Length(max=150)])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=80)])
    class_name = StringField('Class', validators=[Optional(), Length(max=50)])
    description = TextAreaField('Instructions', validators=[Optional()])
    due_date = DateField('Due date', format='%Y-%m-%d', validators=[Optional()])
    max_score = FloatField(
        'Maximum score',
        default=100,
        validators=[Optional(), NumberRange(min=1, max=1000)],
    )
    media = MultipleFileField(
        'Attach images',
        validators=[Optional(), FileSize(max_size=4 * 1024 * 1024)],
    )
    submit = SubmitField('Save assignment')


class SubmissionForm(FlaskForm):
    """A student's answer, uploaded as one or more images."""

    note = TextAreaField('Note (optional)', validators=[Optional(), Length(max=500)])
    images = MultipleFileField(
        'Your answer',
        validators=[DataRequired(message='Please attach at least one image.')],
    )
    submit = SubmitField('Submit answer')


# --------------------------------------------------------------- attendance

ATTENDANCE_STATUSES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('late', 'Late'),
    ('excused', 'Excused'),
]

ATTENDANCE_ICONS = {
    'present': 'fa-user-check',
    'absent': 'fa-user-xmark',
    'late': 'fa-user-clock',
    'excused': 'fa-user-shield',
}


class AttendanceForm(FlaskForm):
    """One day's register for one class."""

    record_date = DateField(
        'Date', format='%Y-%m-%d', validators=[DataRequired()]
    )
    submit = SubmitField('Save register')


class HolidayForm(FlaskForm):
    """Create or edit a public holiday or school closure."""

    name = StringField(
        'Holiday name', validators=[DataRequired(), Length(max=120)]
    )
    holiday_date = DateField(
        'Date', format='%Y-%m-%d', validators=[DataRequired()]
    )
    is_public = BooleanField(
        'This is a public (national) holiday', default=True
    )
    description = TextAreaField(
        'Description', validators=[Optional(), Length(max=1000)]
    )
    submit = SubmitField('Save holiday')


# ------------------------------------------------------------------- content

POST_CATEGORIES = [
    ('news', 'News'),
    ('announcement', 'Announcement'),
    ('event', 'Event'),
    ('achievement', 'Achievement'),
]

CATEGORY_ICONS = {
    'news': 'fa-newspaper',
    'announcement': 'fa-bullhorn',
    'event': 'fa-calendar-day',
    'achievement': 'fa-trophy',
}

CATEGORY_COLOURS = {
    'news': 'bg-primary',
    'announcement': 'bg-danger',
    'event': 'bg-info',
    'achievement': 'bg-warning text-dark',
}

TESTIMONIAL_ROLES = ['Parent', 'Student', 'Teacher', 'Alumnus']


class PostForm(FlaskForm):
    """A news post or announcement for the public school page."""

    title = StringField('Title', validators=[DataRequired(), Length(max=160)])
    category = SelectField(
        'Category', choices=POST_CATEGORIES, default='news',
        validators=[DataRequired()],
    )
    summary = TextAreaField(
        'Short summary', validators=[Optional(), Length(max=300)]
    )
    body = TextAreaField(
        'Full story', validators=[DataRequired()]
    )
    author = StringField(
        'Author', validators=[Optional(), Length(max=120)]
    )
    cover_image = FileField('Cover image')
    images = MultipleFileField(
        'Gallery images',
        validators=[Optional(), FileSize(max_size=4 * 1024 * 1024)],
    )
    is_published = BooleanField('Published', default=True)
    is_featured = BooleanField('Feature this on the home page', default=False)
    submit = SubmitField('Save post')


class TestimonialForm(FlaskForm):
    """A quote from a parent, student or member of staff."""

    name = StringField('Name', validators=[DataRequired(), Length(max=120)])
    role = SelectField(
        'They are a', choices=[(r, r) for r in TESTIMONIAL_ROLES],
        default='Parent', validators=[DataRequired()],
    )
    quote = TextAreaField(
        'What they said', validators=[DataRequired(), Length(max=1000)]
    )
    avatar = FileField('Photo (optional)')
    rating = SelectField(
        'Rating', coerce=int, default=5,
        choices=[(5, '5 — Excellent'), (4, '4 — Good'), (3, '3 — Average'),
                 (2, '2 — Poor'), (1, '1 — Bad')],
        validators=[Optional()],
    )
    is_published = BooleanField('Show on the home page', default=True)
    sort_order = IntegerField(
        'Sort order', default=0, validators=[Optional()]
    )
    submit = SubmitField('Save testimonial')


class LessonPlanForm(FlaskForm):
    """Weekly lesson plan. Teachers own their own; admins may see all.

    Class and subject are deliberately plain text fields rather than dropdowns:
    a teacher should be able to type anything they are actually teaching without
    the form insisting it already exists in the Class table.
    """

    title = StringField('Lesson title', validators=[DataRequired(), Length(max=150)])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=80)])
    class_name = StringField('Class', validators=[Optional(), Length(max=50)])
    week_of = DateField('Week of', format='%Y-%m-%d', validators=[Optional()])
    objectives = TextAreaField('Learning objectives', validators=[Optional()])
    activities = TextAreaField('Class activities', validators=[Optional()])
    resources = TextAreaField('Teaching resources', validators=[Optional()])
    homework = TextAreaField('Homework', validators=[Optional()])
    images = MultipleFileField(
        'Images',
        validators=[Optional(), FileSize(max_size=4 * 1024 * 1024)],
    )
    submit = SubmitField('Save lesson plan')
