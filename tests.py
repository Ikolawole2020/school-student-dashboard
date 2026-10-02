"""Tests covering auth, role gates and the ownership rules.

The previous smoke test only asserted "302 or 403", which passed even while
the result-lookup IDOR was live. These exercise real logins and assert on the
specific behaviour that matters.

IMPORTANT: every test runs against a throwaway SQLite file. Earlier versions
of this file called create_app() with the default database URI and then ran
db.drop_all(), which wiped the real instance/starlight.db. DATABASE_URL is
therefore set below *before* app.config is imported, so the production
database is never opened.
"""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

# point at a throwaway database before config.py is imported
_TEST_DB = os.path.join(tempfile.gettempdir(), 'starlight_test.db')
os.environ['DATABASE_URL'] = f'sqlite:///{_TEST_DB}'

from werkzeug.security import generate_password_hash

from app import create_app, app
from extensions import db
from models import (
    User, Student, Teacher, Class, Assignment, LessonPlan,
    AttendanceRecord, Holiday, Post, PostImage, Testimonial, Result,
)

_REAL_DB_MARKER = os.path.join('instance', 'starlight.db')


def assert_safe_to_destroy(app):
    """Guard against ever running db.drop_all() against the real database.

    During development a scratch script called create_app() with the default
    URI and dropped every table, wiping live data. Anything that destroys the
    database must call this first.
    """
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    if _REAL_DB_MARKER in uri or 'instance' in uri:
        raise RuntimeError(
            f'Refusing to run: {uri} is the real database. '
            f'Set DATABASE_URL to a throwaway file first.'
        )
    if not uri.endswith('_test.db'):
        raise RuntimeError(
            f'Refusing to run: tests must use a *_test.db database, got {uri}'
        )


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False

        self.client = self.app.test_client()
        assert_safe_to_destroy(self.app)

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            self.class_a = Class(class_name='JSS1')
            self.class_b = Class(class_name='JSS2')
            db.session.add_all([self.class_a, self.class_b])
            db.session.flush()

            # two teachers, each owning one class
            self.teacher_a = self._make_teacher('Ada Teacher', self.class_a)
            self.teacher_b = self._make_teacher('Bode Teacher', self.class_b)

            # two students, one per class
            self.student_a = self._make_student('Amy Student', self.class_a)
            self.student_b = self._make_student('Ben Student', self.class_b)

            self.admin = User(
                email='admin@test.com',
                password_hash=generate_password_hash('adminpass'),
                role='admin',
            )
            db.session.add(self.admin)
            db.session.commit()

            # Capture plain values now: the ORM objects become detached once
            # this app context exits, so tests must not touch their
            # attributes afterwards.
            self.class_a_id = self.class_a.id
            self.class_b_id = self.class_b.id
            self.teacher_a_id = self.teacher_a.id
            self.teacher_b_id = self.teacher_b.id
            self.student_a_id = self.student_a.id
            self.student_b_id = self.student_b.id
            self.student_a_public_id = self.student_a.student_public_id
            self.student_b_public_id = self.student_b.student_public_id

    def _make_teacher(self, name, cls):
        user = User(
            email=f'{name.split()[0].lower()}@test.com',
            password_hash=generate_password_hash('teachpass'),
            role='teacher',
        )
        db.session.add(user)
        db.session.flush()
        teacher = Teacher(
            user_id=user.id, staff_id=name.split()[0].lower(),
            name=name, email=user.email, class_name=cls.class_name,
        )
        db.session.add(teacher)
        db.session.flush()
        cls.teacher_id = teacher.id
        return teacher

    def _make_student(self, name, cls):
        user = User(
            email=f'{name.split()[0].lower()}s@test.com',
            password_hash=generate_password_hash('studpass'),
            role='student',
        )
        db.session.add(user)
        db.session.flush()
        student = Student(
            user_id=user.id, student_public_id=name.split()[0].lower() + 's',
            name=name, email=user.email, gender='Female', class_id=cls.id,
        )
        db.session.add(student)
        db.session.flush()
        return student

    def login(self, email, password):
        """Log in as the given account. Returns the response."""
        return self.client.post(
            '/auth/login',
            data={'email': email, 'password': password},
            follow_redirects=False,
        )

    def logout(self):
        self.client.get('/auth/logout')

    def set_password(self, teacher_name, password, clear_first_login_flag=True):
        """Force a known password on a teacher, since the real one is only
        ever shown once in a flash message.

        Clears must_change_password by default, so tests that just need to act
        as a settled user are not bounced to the password screen. Tests about
        the first-login rule pass clear_first_login_flag=False.
        """
        from werkzeug.security import generate_password_hash
        with self.app.app_context():
            teacher = Teacher.query.filter(
                Teacher.name == teacher_name
            ).first()
            teacher.user.password_hash = generate_password_hash(password)
            if clear_first_login_flag:
                teacher.user.must_change_password = False
            db.session.commit()
            return teacher.email

    def complete_first_login(self, password='myownpassword'):
        """Get past the forced password change the way a real user would."""
        return self.client.post(
            '/auth/change-password',
            data={
                'current_password': 'knownpass123',
                'new_password': password,
                'confirm_password': password,
            },
            follow_redirects=True,
        )


class TestPublicAndAuth(BaseCase):
    def test_home_is_public(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_check_result_requires_login(self):
        self.assertEqual(self.client.get('/check-result').status_code, 302)

    def test_login_redirects_by_role(self):
        cases = [
            ('admin@test.com', 'adminpass', '/admin/dashboard'),
            ('ada@test.com', 'teachpass', '/teacher/dashboard'),
            ('amys@test.com', 'studpass', '/student/dashboard'),
        ]
        for email, password, expected in cases:
            self.client.get('/auth/logout')
            response = self.login(email, password)
            self.assertEqual(response.status_code, 302, email)
            # a teacher must never be sent to an admin-only page
            self.assertTrue(
                response.headers['Location'].endswith(expected),
                f'{email} landed on {response.headers["Location"]}',
            )

    def test_change_password(self):
        self.login('amys@test.com', 'studpass')
        response = self.client.post(
            '/auth/change-password',
            data={
                'current_password': 'studpass',
                'new_password': 'brandnew1',
                'confirm_password': 'brandnew1',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.client.get('/auth/logout')
        self.assertEqual(self.login('amys@test.com', 'studpass').status_code, 200)
        self.assertEqual(self.login('amys@test.com', 'brandnew1').status_code, 302)

    def test_deactivated_account_cannot_log_in(self):
        with self.app.app_context():
            user = User.query.filter_by(email='amys@test.com').first()
            user.is_active = False
            db.session.commit()
        response = self.login('amys@test.com', 'studpass', )
        self.assertEqual(response.status_code, 200)
        self.assertIn('deactivated', response.get_data(as_text=True))


class TestResultOwnership(BaseCase):
    """The IDOR this suite exists to prevent."""

    def test_student_cannot_read_another_students_result(self):
        self.login('amys@test.com', 'studpass')
        response = self.client.post(
            '/check-result',
            data={
                'student_id': self.student_b_public_id,
                'class_name': 'JSS2',
                'term': 'Term 1',
            },
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertIn('only view your own result', body)
        self.assertNotIn('Ben Student', body)

    def test_student_can_read_own_result(self):
        self.login('amys@test.com', 'studpass')
        response = self.client.post(
            '/check-result',
            data={
                'student_id': self.student_a_public_id,
                'class_name': 'JSS1',
                'term': 'Term 1',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('Amy Student', response.get_data(as_text=True))

    def test_admin_may_look_up_any_student(self):
        self.login('admin@test.com', 'adminpass')
        response = self.client.post(
            '/check-result',
            data={
                'student_id': self.student_b_public_id,
                'class_name': 'JSS2',
                'term': 'Term 1',
            },
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('only view your own result', body)


class TestAssignments(BaseCase):
    def _post(self, title='Homework 1', subject='Mathematics', class_name='JSS1'):
        return self.client.post(
            '/assignments/add',
            data={
                'title': title,
                'subject': subject,
                # class is free text now, not a dropdown of the teacher's class
                'class_name': class_name,
                'description': 'Page 4, questions 1-10',
                'max_score': '20',
            },
            follow_redirects=True,
        )

    def _score_of(self, assignment_id, student_id):
        from models import AssignmentScore
        with self.app.app_context():
            row = AssignmentScore.query.filter_by(
                assignment_id=assignment_id, student_id=student_id
            ).first()
            return row.score if row else None

    def test_teacher_posts_assignment_to_own_class(self):
        self.login('ada@test.com', 'teachpass')
        response = self._post()
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Assignment.query.count(), 1)

    def test_student_sees_own_class_assignment(self):
        self.login('ada@test.com', 'teachpass')
        self._post(title='Fractions work')
        self.client.get('/auth/logout')

        self.login('amys@test.com', 'studpass')
        body = self.client.get('/assignments/').get_data(as_text=True)
        self.assertIn('Fractions work', body)

    def test_student_cannot_see_other_class_assignment(self):
        self.login('ada@test.com', 'teachpass')
        self._post(title='JSS1 Only Work')
        with self.app.app_context():
            assignment_id = Assignment.query.first().id
        self.client.get('/auth/logout')

        self.login('bens@test.com', 'studpass')
        body = self.client.get('/assignments/').get_data(as_text=True)
        self.assertNotIn('JSS1 Only Work', body)
        self.assertEqual(
            self.client.get(f'/assignments/{assignment_id}').status_code, 403
        )

    def test_teacher_records_scores_and_student_sees_them(self):
        self.login('ada@test.com', 'teachpass')
        self._post()
        with self.app.app_context():
            assignment_id = Assignment.query.first().id
            amy_id = self.student_a_id

        response = self.client.post(
            f'/assignments/{assignment_id}/scores',
            data={f'score_{amy_id}': '18', f'feedback_{amy_id}': 'Well done'},
            follow_redirects=True,
        )
        self.assertIn('Saved 1 score', response.get_data(as_text=True))

        self.client.get('/auth/logout')
        self.login('amys@test.com', 'studpass')
        body = self.client.get(f'/assignments/{assignment_id}').get_data(as_text=True)
        self.assertIn('18.0', body)
        self.assertIn('Well done', body)

    def test_blank_row_does_not_wipe_existing_score(self):
        """Partial entry must never destroy marks already recorded."""
        self.login('ada@test.com', 'teachpass')
        self._post()
        with self.app.app_context():
            assignment_id = Assignment.query.first().id
            amy_id = self.student_a_id

        self.client.post(
            f'/assignments/{assignment_id}/scores',
            data={f'score_{amy_id}': '15'}, follow_redirects=True,
        )
        # a later save that touches nothing must leave the mark intact
        self.client.post(
            f'/assignments/{assignment_id}/scores',
            data={}, follow_redirects=True,
        )
        self.assertEqual(self._score_of(assignment_id, amy_id), 15.0)

    def test_score_above_maximum_is_rejected(self):
        self.login('ada@test.com', 'teachpass')
        self._post()
        with self.app.app_context():
            assignment_id = Assignment.query.first().id
            amy_id = self.student_a_id

        response = self.client.post(
            f'/assignments/{assignment_id}/scores',
            data={f'score_{amy_id}': '500'}, follow_redirects=True,
        )
        self.assertIn('between 0 and 20', response.get_data(as_text=True))
        self.assertIsNone(self._score_of(assignment_id, amy_id))

    def test_student_cannot_post_assignments(self):
        self.login('amys@test.com', 'studpass')
        self.assertEqual(self.client.get('/assignments/add').status_code, 403)


class TestLessonPlans(BaseCase):
    def _make_plan(self, title='Week 1: Fractions'):
        return self.client.post(
            '/lessons/add',
            data={
                'title': title,
                'subject': 'Mathematics',
                'class_id': str(self.class_a_id),
                'week_of': '2026-01-05',
                'objectives': 'Students understand numerators.',
                'activities': 'Group work and board work.',
            },
            follow_redirects=True,
        )

    def test_teacher_creates_own_plan(self):
        self.login('ada@test.com', 'teachpass')
        response = self._make_plan()
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(LessonPlan.query.count(), 1)
            plan = LessonPlan.query.first()
            self.assertEqual(plan.teacher_id, self.teacher_a_id)

    def test_teacher_sees_own_plan(self):
        self.login('ada@test.com', 'teachpass')
        self._make_plan(title='My Plan')
        body = self.client.get('/lessons/').get_data(as_text=True)
        self.assertIn('My Plan', body)

    def test_teacher_cannot_see_another_teachers_plan(self):
        self.login('ada@test.com', 'teachpass')
        self._make_plan(title='Ada Secret Plan')
        with self.app.app_context():
            plan_id = LessonPlan.query.first().id
        self.client.get('/auth/logout')

        self.login('bode@test.com', 'teachpass')
        body = self.client.get('/lessons/').get_data(as_text=True)
        self.assertNotIn('Ada Secret Plan', body)
        # direct access must be refused too
        self.assertEqual(self.client.get(f'/lessons/{plan_id}').status_code, 403)
        self.assertEqual(
            self.client.get(f'/lessons/{plan_id}/edit').status_code, 403
        )

    def test_teacher_cannot_delete_another_teachers_plan(self):
        self.login('ada@test.com', 'teachpass')
        self._make_plan()
        with self.app.app_context():
            plan_id = LessonPlan.query.first().id
        self.client.get('/auth/logout')

        self.login('bode@test.com', 'teachpass')
        self.client.post(f'/lessons/{plan_id}/delete', follow_redirects=True)
        with self.app.app_context():
            self.assertEqual(LessonPlan.query.count(), 1)

    def test_admin_sees_every_plan(self):
        self.login('ada@test.com', 'teachpass')
        self._make_plan(title='Ada Plan')
        self.client.get('/auth/logout')

        self.login('bode@test.com', 'teachpass')
        self._make_plan(title='Bode Plan')
        self.client.get('/auth/logout')

        self.login('admin@test.com', 'adminpass')
        body = self.client.get('/lessons/').get_data(as_text=True)
        self.assertIn('Ada Plan', body)
        self.assertIn('Bode Plan', body)

    def test_teacher_cannot_edit_someone_elses_plan(self):
        self.login('ada@test.com', 'teachpass')
        self._make_plan()
        with self.app.app_context():
            plan_id = LessonPlan.query.first().id
        self.client.get('/auth/logout')

        self.login('bode@test.com', 'teachpass')
        response = self.client.post(
            f'/lessons/{plan_id}/edit',
            data={'title': 'Hijacked', 'subject': 'Mathematics'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertNotEqual(LessonPlan.query.first().title, 'Hijacked')

    def test_student_cannot_reach_lesson_plans(self):
        self.login('amys@test.com', 'studpass')
        self.assertEqual(self.client.get('/lessons/').status_code, 403)


class TestTeachersWithoutClass(BaseCase):
    """Non-teaching staff (bursars, cooks, admin officers) may be added with
    no class assigned. A class can be given later from the edit page."""

    def _add(self, name, phone, class_name=''):
        return self.client.post(
            '/admin/teachers/add',
            data={'name': name, 'phone': phone, 'class_name': class_name},
            follow_redirects=True,
        )

    def test_add_teacher_with_blank_class(self):
        self.login('admin@test.com', 'adminpass')
        body = self._add('Grace Bursar', '08031234567').get_data(as_text=True)
        self.assertIn('Grace Bursar', body)
        with self.app.app_context():
            teacher = Teacher.query.filter_by(name='Grace Bursar').first()
            self.assertIsNotNone(teacher)
            self.assertIsNone(teacher.class_name)
            # staff ID and email are generated automatically
            self.assertTrue(teacher.staff_id)
            self.assertIn('@', teacher.email)

    def test_generated_credentials_shown_once(self):
        self.login('admin@test.com', 'adminpass')
        body = self._add('Peter Cook', '08031234568').get_data(as_text=True)
        # staff ID and email are generated; the password is derived from the
        # name and reported alongside them
        self.assertIn('Staff ID', body)
        self.assertIn('petsmc', body)  # first three letters: "pet" + "smc"

    def test_no_plaintext_password_stored(self):
        self.login('admin@test.com', 'adminpass')
        self._add('Peter Cook', '08031234568')
        with self.app.app_context():
            teacher = Teacher.query.filter_by(name='Peter Cook').first()
            self.assertFalse(hasattr(teacher, 'password'))
            self.assertTrue(teacher.user.password_hash)

    def test_classless_teacher_lands_on_teacher_dashboard(self):
        self.login('admin@test.com', 'adminpass')
        self._add('Grace Bursar', '08031234567')
        email = self.set_password('Grace Bursar', 'knownpass123')
        self.logout()

        response = self.login(email, 'knownpass123')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers['Location'].endswith('/teacher/dashboard')
        )

    def test_classless_teacher_can_use_both_hubs(self):
        """Class is free text on assignments, so a teacher without an assigned
        class is not blocked from posting work or writing lesson plans."""
        self.login('admin@test.com', 'adminpass')
        self._add('Grace Bursar', '08031234567')
        email = self.set_password('Grace Bursar', 'knownpass123')
        self.logout()
        self.login(email, 'knownpass123')

        self.assertEqual(self.client.get('/lessons/').status_code, 200)
        self.assertEqual(self.client.get('/lessons/add').status_code, 200)
        self.assertEqual(self.client.get('/assignments/add').status_code, 200)

        response = self.client.post(
            '/assignments/add',
            data={
                'title': 'Cover the register',
                'subject': 'Administration',
                'class_name': 'JSS1',
                'max_score': '10',
            },
            follow_redirects=True,
        )
        self.assertIn('Assignment posted', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Assignment.query.count(), 1)

    def test_class_can_be_assigned_later(self):
        self.login('admin@test.com', 'adminpass')
        self._add('Grace Bursar', '08031234567')
        with self.app.app_context():
            teacher_id = Teacher.query.filter_by(
                name='Grace Bursar'
            ).first().id

        response = self.client.post(
            f'/admin/teachers/{teacher_id}/edit',
            data={
                'name': 'Grace Bursar',
                'staff_id': 'gracebursar',
                'email': 'gracebursar@smc.com',
                'phone': '08031234567',
                'gender': 'Female',
                'class_name': 'JSS2',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            teacher = Teacher.query.get(teacher_id)
            self.assertEqual(teacher.class_name, 'JSS2')


class TestLessonPlanImagesAndFreeText(BaseCase):
    """Class/subject are typed by the teacher, and any number of images can
    be attached to a plan."""

    def _png(self, name='sheet.png'):
        import io
        data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc'
            b'\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return (io.BytesIO(data), name)

    def _create(self, title='Week 1', subject='Agricultural Science',
                class_name='JSS1', images=None):
        data = {
            'title': title, 'subject': subject, 'class_name': class_name,
            'objectives': 'Students learn plant propagation.',
        }
        if images:
            data['images'] = images
        return self.client.post('/lessons/add', data=data, follow_redirects=True)

    def test_teacher_types_any_class_not_in_the_class_table(self):
        self.login('ada@test.com', 'teachpass')
        self._create(class_name='Year 8 Extension B')
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(
                title='Week 1'
            ).first()
            self.assertIsNotNone(plan)
            self.assertEqual(plan.class_name, 'Year 8 Extension B')
            # no matching Class row, so the FK stays empty
            self.assertIsNone(plan.class_id)

    def test_matching_class_name_also_links_the_foreign_key(self):
        self.login('ada@test.com', 'teachpass')
        self._create(class_name='JSS1')
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertEqual(plan.class_name, 'JSS1')
            self.assertEqual(plan.class_id, self.class_a_id)

    def test_class_can_be_left_blank(self):
        self.login('ada@test.com', 'teachpass')
        self._create(class_name='')
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertIsNone(plan.class_name)
            self.assertIsNone(plan.class_id)

    def test_single_image_is_attached(self):
        self.login('ada@test.com', 'teachpass')
        response = self._create(images=[self._png('one.png')])
        self.assertIn('1 image(s) attached', response.get_data(as_text=True))
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertEqual(len(plan.images), 1)

    def test_multiple_images_are_attached_at_once(self):
        self.login('ada@test.com', 'teachpass')
        response = self._create(images=[
            self._png('a.png'), self._png('b.png'), self._png('c.png'),
        ])
        self.assertIn('3 image(s) attached', response.get_data(as_text=True))
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertEqual(len(plan.images), 3)

    def test_images_add_to_existing_ones_on_edit(self):
        self.login('ada@test.com', 'teachpass')
        self._create(images=[self._png('one.png')])
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            plan_id = plan.id

        # add two more through the edit form
        self.client.post(
            f'/lessons/{plan_id}/edit',
            data={
                'title': 'Week 1', 'subject': 'Agricultural Science',
                'class_name': 'JSS1',
                'images': [self._png('d.png'), self._png('e.png')],
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        with self.app.app_context():
            plan = LessonPlan.query.get(plan_id)
            # the original image is not replaced
            self.assertEqual(len(plan.images), 3)

    def test_disallowed_file_type_is_ignored(self):
        self.login('ada@test.com', 'teachpass')
        self._create(images=[self._png('evil.exe')])
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertIsNotNone(plan)
            self.assertEqual(len(plan.images), 0)

    def test_images_appear_on_the_detail_page(self):
        self.login('ada@test.com', 'teachpass')
        self._create(images=[self._png('a.png'), self._png('b.png')])
        with self.app.app_context():
            plan_id = LessonPlan.query.filter_by(title='Week 1').first().id

        body = self.client.get(f'/lessons/{plan_id}').get_data(as_text=True)
        self.assertIn('Attached images', body)
        self.assertIn('/uploads/', body)

    def test_author_can_delete_an_image(self):
        import os
        self.login('ada@test.com', 'teachpass')
        self._create(images=[self._png('a.png'), self._png('b.png')])
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            image_id = plan.images[0].id
            filename = plan.images[0].filename

        self.client.post(
            f'/lessons/images/{image_id}/delete', follow_redirects=True
        )
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertEqual(len(plan.images), 1)

        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(
            os.path.isfile(os.path.join(app_root, 'uploads', filename))
        )

    def test_other_teacher_cannot_delete_an_image(self):
        self.login('ada@test.com', 'teachpass')
        self._create(images=[self._png('a.png')])
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            image_id = plan.images[0].id
        self.client.get('/auth/logout')

        self.login('bode@test.com', 'teachpass')
        self.assertEqual(
            self.client.post(f'/lessons/images/{image_id}/delete').status_code,
            403,
        )
        with self.app.app_context():
            plan = LessonPlan.query.filter_by(title='Week 1').first()
            self.assertEqual(len(plan.images), 1)


class TestDerivedStaffPassword(BaseCase):
    """Teacher passwords are derived from the name, never stored."""

    def test_rule(self):
        from utils import derive_staff_password
        self.assertEqual(derive_staff_password('Ada Teacher'), 'adasmc')
        self.assertEqual(derive_staff_password('Grace Chukwu'), 'grasmc')
        self.assertEqual(derive_staff_password('Chidi'), 'chismc')
        # short names fall back rather than crashing
        self.assertEqual(derive_staff_password('Bo'), 'bosmc')
        # surname changes do not change the password
        self.assertEqual(
            derive_staff_password('Ada Obi'), derive_staff_password('Ada Bello')
        )

    def test_teacher_is_created_with_derived_password(self):
        from werkzeug.security import check_password_hash
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher = Teacher.query.filter_by(name='Ada Obi').first()
            self.assertIsNotNone(teacher)
            self.assertTrue(
                check_password_hash(teacher.user.password_hash, 'ada smc'.replace(' ', ''))
            )

    def test_teacher_can_log_in_with_derived_password(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Grace Chukwu', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            email = Teacher.query.filter_by(name='Grace Chukwu').first().email
        self.logout()
        response = self.login(email, 'grasmc')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers['Location'].endswith('/teacher/dashboard')
        )

    def test_dashboard_shows_password_without_storing_it(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        body = self.client.get('/admin/dashboard').get_data(as_text=True)
        self.assertIn('Staff login details', body)
        self.assertIn('adasmc', body)

    def test_no_plaintext_password_column_on_teacher(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher = Teacher.query.filter_by(name='Ada Obi').first()
            # the model must not carry a plaintext password field at all
            self.assertNotIn('password', teacher.__table__.columns)
            self.assertFalse(hasattr(teacher, 'password'))

    def test_reset_restores_derived_password(self):
        from werkzeug.security import check_password_hash
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher_id = Teacher.query.filter_by(name='Ada Obi').first().id
            # change it to something else first
            t = Teacher.query.get(teacher_id)
            from werkzeug.security import generate_password_hash
            t.user.password_hash = generate_password_hash('changed999')

        self.client.post(f'/admin/teachers/{teacher_id}/reset-password')
        with self.app.app_context():
            t = Teacher.query.get(teacher_id)
            self.assertTrue(check_password_hash(t.user.password_hash, 'adasmc'))

    def test_admin_sets_teacher_password_of_own_choice(self):
        """The admin types the password instead of getting a random one."""
        from werkzeug.security import check_password_hash
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher_id = Teacher.query.filter_by(name='Ada Obi').first().id

        r = self.client.post(
            f'/admin/teachers/{teacher_id}/set-password',
            data={'new_password': 'chosen123', 'confirm_password': 'chosen123',
                  'must_change': 'y'},
        )
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            t = Teacher.query.get(teacher_id)
            self.assertTrue(check_password_hash(t.user.password_hash, 'chosen123'))
            # ticked -> must change at first login
            self.assertTrue(t.user.must_change_password)

    def test_unticked_checkbox_does_not_force_password_change(self):
        """A browser omits an unticked checkbox, so it must read as off."""
        from werkzeug.security import check_password_hash
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher_id = Teacher.query.filter_by(name='Ada Obi').first().id
        self.client.post(
            f'/admin/teachers/{teacher_id}/set-password',
            data={'new_password': 'chosen123', 'confirm_password': 'chosen123'},
        )
        with self.app.app_context():
            t = Teacher.query.get(teacher_id)
            self.assertTrue(check_password_hash(t.user.password_hash, 'chosen123'))
            self.assertFalse(t.user.must_change_password)

    def test_admin_can_skip_forcing_password_change(self):
        from werkzeug.security import check_password_hash
        self.login('admin@test.com', 'adminpass')
        with self.app.app_context():
            student_id = Student.query.first().id
        self.client.post(
            f'/admin/students/{student_id}/set-password',
            data={'new_password': 'plain123', 'confirm_password': 'plain123'},
        )
        with self.app.app_context():
            s = Student.query.get(student_id)
            self.assertTrue(check_password_hash(s.user.password_hash, 'plain123'))
            self.assertFalse(s.user.must_change_password)

    def test_set_password_rejects_short_and_mismatched(self):
        self.login('admin@test.com', 'adminpass')
        with self.app.app_context():
            student_id = Student.query.first().id
        r = self.client.post(
            f'/admin/students/{student_id}/set-password',
            data={'new_password': 'abc', 'confirm_password': 'abc'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('at least 6', r.get_data(as_text=True).lower())

        r = self.client.post(
            f'/admin/students/{student_id}/set-password',
            data={'new_password': 'abcdef1', 'confirm_password': 'different1'},
        )
        self.assertIn('match', r.get_data(as_text=True).lower())

    def test_teacher_cannot_set_someone_elses_password(self):
        from werkzeug.security import check_password_hash
        with self.app.app_context():
            student_id = Student.query.first().id
        self.login('teacher1@test.com', 'teachpass')
        r = self.client.post(
            f'/admin/students/{student_id}/set-password',
            data={'new_password': 'hacked123', 'confirm_password': 'hacked123'},
        )
        self.assertIn(r.status_code, (302, 403))
        with self.app.app_context():
            s = Student.query.get(student_id)
            self.assertFalse(check_password_hash(s.user.password_hash, 'hacked123'))


class TestPartialTerm3Promotion(BaseCase):
    """The school promotes on Term 3 as soon as any result is saved.

    A completeness requirement left students stuck in their old class whenever
    a subject was still outstanding, which the school does not want.
    """

    def _jss1_student(self):
        with self.app.app_context():
            student = Student.query.filter_by(class_id=1).first()
            if student is None:
                student = Student.query.first()
            return student.id, student.class_rel.class_name

    def _save(self, student_id, class_name, term, subjects):
        from subjects import get_subjects_for_class
        available = get_subjects_for_class(class_name, None)
        data = {'student_id': student_id, 'class_name': class_name, 'term': term}
        for subject in available[:subjects]:
            key = subject.replace(' ', '_')
            data[f'test_{key}'] = '30'
            data[f'exam_{key}'] = '50'
        return self.client.post('/admin/results/save', data=data)

    def _class_of(self, student_id):
        with self.app.app_context():
            return db.session.get(Student, student_id).class_rel.class_name

    def test_promotes_with_a_single_subject_entered(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 3', 1)
        self.assertNotEqual(self._class_of(sid), class_name)

    def test_promotes_with_five_of_thirteen_subjects(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 3', 5)
        self.assertNotEqual(self._class_of(sid), class_name)

    def test_promotes_with_twelve_of_thirteen_subjects(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 3', 12)
        self.assertNotEqual(self._class_of(sid), class_name)

    def test_other_terms_do_not_promote(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 1', 12)
        self._save(sid, class_name, 'Term 2', 12)
        self.assertEqual(self._class_of(sid), class_name)

    def test_partial_results_are_kept_after_promotion(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 3', 5)
        with self.app.app_context():
            saved = Result.query.filter_by(
                student_id=sid, class_name=class_name, term='Term 3'
            ).count()
        self.assertEqual(saved, 5)

    def test_no_double_promotion_on_resave(self):
        self.login('admin@test.com', 'adminpass')
        sid, class_name = self._jss1_student()
        self._save(sid, class_name, 'Term 3', 3)
        after_first = self._class_of(sid)
        self._save(sid, class_name, 'Term 3', 3)
        self.assertEqual(self._class_of(sid), after_first)


class TestResultSummary(BaseCase):
    """The average/total summary shown on every results view."""

    def _seed(self, marks):
        with self.app.app_context():
            student = Student.query.first()
            for subject, total in marks:
                db.session.add(Result(
                    student_id=student.id, subject=subject,
                    class_name='JSS1', term='Term 1',
                    test_score=30, exam_score=total - 30,
                    total_score=total, percentage=total, grade='B',
                ))
            db.session.commit()
            return student.id, student.student_public_id

    def test_admin_profile_shows_average_and_total(self):
        sid, _ = self._seed([('Mathematics', 80), ('English Language', 60)])
        self.login('admin@test.com', 'adminpass')
        r = self.client.get(f'/admin/students/{sid}?class_name=JSS1&term=Term 1')
        body = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Result Summary', body)
        self.assertIn('70.00%', body)   # (80+60)/2
        self.assertIn('140', body)       # total score
        self.assertIn('Best:', body)
        self.assertIn('Lowest:', body)

    def test_student_results_page_shows_average(self):
        _, public_id = self._seed([('Mathematics', 90), ('Basic Science', 70)])
        with self.app.app_context():
            email = Student.query.first().user.email
        self.login(email, 'studpass')
        r = self.client.get('/student/results?class_name=JSS1&term=Term 1')
        body = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Result Summary', body)
        self.assertIn('80.00%', body)   # (90+70)/2

    def test_summary_does_not_crash_with_no_results(self):
        self.login('admin@test.com', 'adminpass')
        with self.app.app_context():
            sid = Student.query.first().id
        r = self.client.get(f'/admin/students/{sid}?class_name=JSS1&term=Term 2')
        self.assertEqual(r.status_code, 200)


class TestSummaryGradeMatchesSubjects(BaseCase):
    """The "Average Grade" card must use the same bands as subject rows.

    An earlier version of the summary card re-declared the grade bands in the
    template and got them wrong (70% and above showed as D, and an E band that
    does not exist in this school). A student with all A's was shown a D.
    """

    def _summary_grade(self, marks):
        from utils import grade_for
        import re
        with self.app.app_context():
            student = Student.query.first()
            db.session.query(Result).delete()
            for subject, total in marks:
                db.session.add(Result(
                    student_id=student.id, subject=subject,
                    class_name='JSS1', term='Term 1',
                    test_score=30, exam_score=total - 30,
                    total_score=total, percentage=total, grade=grade_for(total),
                ))
            db.session.commit()
            sid = student.id
        self.login('admin@test.com', 'adminpass')
        body = self.client.get(
            f'/admin/students/{sid}?class_name=JSS1&term=Term 1'
        ).get_data(as_text=True)
        match = re.search(r'summary-value[^>]*>\s*([A-F])\s*<', body)
        self.assertIsNotNone(match, 'Average Grade tile not found')
        return match.group(1)

    def test_all_a_subjects_gives_average_grade_a(self):
        shown = self._summary_grade([
            ('Mathematics', 95), ('English Language', 92),
            ('Basic Science', 88), ('Social Studies', 90),
        ])
        self.assertEqual(shown, 'A')

    def test_grade_bands_match_the_school_scale(self):
        cases = [
            ([('Mathematics', 72), ('English Language', 68)], 'A'),  # avg 70
            ([('Mathematics', 65), ('English Language', 62)], 'B'),  # avg 63.5
            ([('Mathematics', 52), ('English Language', 50)], 'C'),  # avg 51
            ([('Mathematics', 47), ('English Language', 46)], 'D'),  # avg 46.5
            ([('Mathematics', 30), ('English Language', 25)], 'F'),
        ]
        for marks, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self._summary_grade(marks), expected)

    def test_never_shows_a_grade_beyond_d_or_f(self):
        """The school has no E band, so the summary must never show one."""
        for marks, _ in [
            ([('Mathematics', 95)], None),
            ([('Mathematics', 30)], None),
        ]:
            grade = self._summary_grade(marks)
            self.assertIn(grade, 'ABCDF')


class TestAttendance(BaseCase):
    """Teachers mark a daily register; students see only their own record."""

    def _mark(self, when, statuses, class_id=None):
        data = {'record_date': when.isoformat()}
        for sid, status in statuses.items():
            data[f'status_{sid}'] = status
        return self.client.post(
            f'/attendance/register/{class_id or self.class_a_id}',
            data=data, follow_redirects=True,
        )

    def test_teacher_can_mark_attendance(self):
        self.login('ada@test.com', 'teachpass')
        response = self._mark(date.today(), {self.student_a_id: 'present'})
        self.assertIn('Register saved', response.get_data(as_text=True))
        with self.app.app_context():
            rows = AttendanceRecord.query.all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'present')
            self.assertEqual(rows[0].class_id, self.class_a_id)

    def test_remark_is_saved(self):
        self.login('ada@test.com', 'teachpass')
        self.client.post(
            f'/attendance/register/{self.class_a_id}',
            data={
                'record_date': date.today().isoformat(),
                f'status_{self.student_a_id}': 'absent',
                f'remark_{self.student_a_id}': 'Medical appointment',
            },
            follow_redirects=True,
        )
        with self.app.app_context():
            row = AttendanceRecord.query.filter_by(
                student_id=self.student_a_id
            ).first()
            self.assertEqual(row.remark, 'Medical appointment')

    def test_marking_twice_updates_rather_than_duplicates(self):
        self.login('ada@test.com', 'teachpass')
        self._mark(date.today(), {self.student_a_id: 'absent'})
        self._mark(date.today(), {self.student_a_id: 'present'})
        with self.app.app_context():
            rows = AttendanceRecord.query.filter_by(
                student_id=self.student_a_id
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'present')

    def test_untouched_students_keep_their_previous_mark(self):
        """Correcting one pupil must not wipe the rest of the register."""
        with self.app.app_context():
            # a second student in the same class, so both are on the register
            u = User(email='zoe@test.com',
                     password_hash=generate_password_hash('studpass'),
                     role='student')
            db.session.add(u)
            db.session.flush()
            other = Student(
                user_id=u.id, student_public_id='zoes', name='Zoe Second',
                email='zoe@test.com', gender='Female', class_id=self.class_a_id,
            )
            db.session.add(other)
            db.session.commit()
            other_id = other.id

        self.login('ada@test.com', 'teachpass')
        self._mark(date.today(), {
            self.student_a_id: 'present', other_id: 'late',
        })
        # second pass mentions only the first student
        self.client.post(
            f'/attendance/register/{self.class_a_id}',
            data={
                'record_date': date.today().isoformat(),
                f'status_{self.student_a_id}': 'absent',
            },
            follow_redirects=True,
        )
        with self.app.app_context():
            untouched = AttendanceRecord.query.filter_by(
                student_id=other_id
            ).first()
            self.assertIsNotNone(untouched)
            self.assertEqual(untouched.status, 'late')

    def test_teacher_cannot_mark_another_class(self):
        self.login('ada@test.com', 'teachpass')
        response = self.client.get(
            f'/attendance/register/{self.class_b_id}'
        )
        self.assertEqual(response.status_code, 403)

    def test_student_sees_own_attendance_only(self):
        self.login('ada@test.com', 'teachpass')
        self._mark(date.today(), {self.student_a_id: 'absent'})
        self.logout()

        self.login('amys@test.com', 'studpass')
        body = self.client.get('/attendance/my').get_data(as_text=True)
        self.assertIn('Amy', body)
        # a student has no register page
        self.assertEqual(
            self.client.get(f'/attendance/register/{self.class_a_id}').status_code,
            403,
        )

    def test_summary_counts_late_and_excused_as_in_school(self):
        from utils import attendance_summary

        class R:
            def __init__(self, s):
                self.status = s
        summary = attendance_summary([R('present'), R('absent'), R('late'), R('excused')])
        self.assertEqual(summary['counts']['absent'], 1)
        self.assertEqual(summary['total'], 4)
        self.assertEqual(summary['in_school'], 3)
        self.assertEqual(summary['percentage'], 75.0)

    def test_admin_can_mark_any_class(self):
        self.login('admin@test.com', 'adminpass')
        response = self._mark(
            date.today(), {self.student_b_id: 'present'}, class_id=self.class_b_id
        )
        self.assertEqual(response.status_code, 200)


class TestHolidays(BaseCase):
    def test_admin_can_add_holiday_with_description(self):
        self.login('admin@test.com', 'adminpass')
        response = self.client.post(
            '/attendance/holidays/add',
            data={
                'name': 'Nigeria Independence Day',
                'holiday_date': '2026-10-01',
                'is_public': 'y',
                'description': 'School closed all day.',
            },
            follow_redirects=True,
        )
        self.assertIn('Nigeria Independence Day', response.get_data(as_text=True))
        with self.app.app_context():
            h = Holiday.query.first()
            self.assertEqual(h.name, 'Nigeria Independence Day')
            self.assertTrue(h.is_public)
            self.assertEqual(h.description, 'School closed all day.')

    def test_teacher_can_view_holidays(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/attendance/holidays/add',
            data={'name': 'Mid-Term Break', 'holiday_date': '2026-08-05',
                  'description': 'A week off.'},
            follow_redirects=True,
        )
        self.logout()
        self.login('ada@test.com', 'teachpass')
        self.assertEqual(
            self.client.get('/attendance/holidays').status_code, 200
        )

    def test_teacher_cannot_create_holiday(self):
        self.login('ada@test.com', 'teachpass')
        self.assertEqual(
            self.client.get('/attendance/holidays/add').status_code, 403
        )

    def test_holiday_warns_on_the_register_page(self):
        self.login('admin@test.com', 'adminpass')
        today = date.today().isoformat()
        self.client.post(
            '/attendance/holidays/add',
            data={'name': 'Test Holiday', 'holiday_date': today,
                  'description': 'Closed.'},
            follow_redirects=True,
        )
        body = self.client.get(
            f'/attendance/register/{self.class_a_id}'
        ).get_data(as_text=True)
        self.assertIn('Test Holiday', body)


class TestFirstLoginPassword(BaseCase):
    """A school-issued password must be replaced before normal use."""

    def test_teacher_is_forced_to_change_password(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            teacher = Teacher.query.filter_by(name='Ada Obi').first()
            self.assertTrue(teacher.user.must_change_password)
            email = teacher.email
        self.logout()

        self.login(email, 'adasmc')
        # every page redirects to the change-password screen
        for path in ('/teacher/dashboard', '/lessons/', '/assignments/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertIn('change-password', response.headers['Location'])

    def test_changing_the_password_releases_the_account(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            email = Teacher.query.filter_by(name='Ada Obi').first().email
        self.logout()
        self.login(email, 'adasmc')

        self.client.post(
            '/auth/change-password',
            data={
                'current_password': 'adasmc',
                'new_password': 'myownsecret',
                'confirm_password': 'myownsecret',
            },
            follow_redirects=True,
        )
        with self.app.app_context():
            user = User.query.filter_by(email=email).first()
            self.assertFalse(user.must_change_password)
        # now the dashboard is reachable
        self.assertEqual(
            self.client.get('/teacher/dashboard').status_code, 200
        )

    def test_logout_is_always_reachable_while_forced(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/teachers/add',
            data={'name': 'Ada Obi', 'phone': '08031234567', 'class_name': ''},
            follow_redirects=True,
        )
        with self.app.app_context():
            email = Teacher.query.filter_by(name='Ada Obi').first().email
        self.logout()
        self.login(email, 'adasmc')
        # the change-password page itself must not redirect to itself
        self.assertEqual(
            self.client.get('/auth/change-password').status_code, 200
        )

    def test_self_registration_is_not_forced(self):
        """A student who types their own password should not be nagged."""
        self.client.post(
            '/auth/register-student',
            data={
                'name': 'Chidi Nwosu', 'gender': 'Male', 'class_name': 'JSS1',
                'department': '', 'guardian_phone': '08099887766',
                'password': 'myownpassword',
            },
            follow_redirects=True,
        )
        self.login('chidinwosu@smc.com', 'myownpassword')
        self.assertEqual(
            self.client.get('/student/dashboard').status_code, 200
        )


class TestNewsAndTestimonials(BaseCase):
    """Admin-managed public content: news, announcements and testimonials."""

    def _post_news(self, **over):
        data = {
            'title': 'Our pupils win the science quiz',
            'category': 'news',
            'body': 'Three pupils represented the school and came first.',
            'author': 'The Principal',
            'is_published': 'y',
        }
        data.update(over)
        return self.client.post(
            '/admin/news/add', data=data, follow_redirects=True
        )

    def test_admin_can_publish_a_post(self):
        self.login('admin@test.com', 'adminpass')
        response = self._post_news()
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            post = Post.query.first()
            self.assertIsNotNone(post)
            self.assertTrue(post.is_published)
            self.assertEqual(post.slug, 'our-pupils-win-the-science-quiz')

    def test_published_post_is_public(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news()
        self.logout()

        anon = app.test_client()
        listing = anon.get('/news').get_data(as_text=True)
        self.assertIn('Our pupils win the science quiz', listing)
        detail = anon.get('/news/our-pupils-win-the-science-quiz')
        self.assertEqual(detail.status_code, 200)

    def test_draft_post_is_hidden_from_the_public(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news(title='Secret plans', is_published=None)
        self.logout()

        anon = app.test_client()
        self.assertNotIn(
            'Secret plans', anon.get('/news').get_data(as_text=True)
        )
        self.assertEqual(anon.get('/news/secret-plans').status_code, 404)

    def test_toggle_publishes_and_hides(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news()
        with self.app.app_context():
            post_id = Post.query.first().id

        self.client.post(f'/admin/news/{post_id}/toggle')
        with self.app.app_context():
            self.assertFalse(Post.query.get(post_id).is_published)
        self.client.post(f'/admin/news/{post_id}/toggle')
        with self.app.app_context():
            self.assertTrue(Post.query.get(post_id).is_published)

    def test_duplicate_titles_get_distinct_slugs(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news(title='Sports Day')
        self._post_news(title='Sports Day')
        with self.app.app_context():
            slugs = {p.slug for p in Post.query.all()}
            self.assertEqual(len(slugs), 2)
            self.assertIn('sports-day', slugs)
            self.assertIn('sports-day-2', slugs)

    def test_teacher_cannot_manage_news(self):
        self.login('ada@test.com', 'teachpass')
        self.assertEqual(self.client.get('/admin/news').status_code, 403)
        self.assertEqual(
            self.client.post(
                '/admin/news/add', data={'title': 'x', 'body': 'y', 'category': 'news'}
            ).status_code,
            403,
        )

    def test_student_can_read_news_but_not_manage(self):
        self.login('amys@test.com', 'studpass')
        self.assertEqual(self.client.get('/news').status_code, 200)
        self.assertEqual(self.client.get('/admin/news').status_code, 403)

    def test_news_appears_on_the_home_page(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news()
        self.logout()
        anon = app.test_client()
        self.assertIn(
            'Our pupils win the science quiz',
            anon.get('/').get_data(as_text=True),
        )

    def test_admin_can_add_testimonial(self):
        self.login('admin@test.com', 'adminpass')
        response = self.client.post(
            '/admin/testimonials/add',
            data={
                'name': 'Mrs Adebayo', 'role': 'Parent',
                'quote': 'My child has grown so much here.',
                'rating': '5', 'is_published': 'y', 'sort_order': '0',
            },
            follow_redirects=True,
        )
        self.assertIn('Mrs Adebayo', response.get_data(as_text=True))
        self.logout()
        anon = app.test_client()
        self.assertIn(
            'My child has grown so much here.',
            anon.get('/').get_data(as_text=True),
        )

    def test_hidden_testimonial_is_not_public(self):
        self.login('admin@test.com', 'adminpass')
        self.client.post(
            '/admin/testimonials/add',
            data={'name': 'Hidden Person', 'role': 'Parent',
                  'quote': 'Should not appear.', 'rating': '5', 'sort_order': '0'},
            follow_redirects=True,
        )
        with self.app.app_context():
            tid = Testimonial.query.first().id
        self.client.post(f'/admin/testimonials/{tid}/delete')
        self.logout()
        anon = app.test_client()
        self.assertNotIn(
            'Should not appear.', anon.get('/').get_data(as_text=True)
        )

    def test_teacher_cannot_manage_testimonials(self):
        self.login('ada@test.com', 'teachpass')
        self.assertEqual(
            self.client.get('/admin/testimonials').status_code, 403
        )

    def test_delete_post_removes_it(self):
        self.login('admin@test.com', 'adminpass')
        self._post_news()
        with self.app.app_context():
            post_id = Post.query.first().id
        self.client.post(f'/admin/news/{post_id}/delete')
        with self.app.app_context():
            self.assertEqual(Post.query.count(), 0)
