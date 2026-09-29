"""Tests covering auth, role gates and the ownership rules.

The previous smoke test only asserted "302 or 403", which passed even while
the result-lookup IDOR was live. These exercise real logins and assert on the
specific behaviour that matters.
"""
import os
import unittest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from models import User, Student, Teacher, Class, Assignment, LessonPlan


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

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

    def set_password(self, teacher_name, password):
        """Force a known password on a teacher, since the real one is only
        ever shown once in a flash message."""
        from werkzeug.security import generate_password_hash
        with self.app.app_context():
            teacher = Teacher.query.filter(
                Teacher.name == teacher_name
            ).first()
            teacher.user.password_hash = generate_password_hash(password)
            db.session.commit()
            return teacher.email


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
    def _post(self, title='Homework 1', subject='Mathematics', class_id=None):
        return self.client.post(
            '/assignments/add',
            data={
                'title': title,
                'subject': subject,
                'class_id': str(class_id or self.class_a_id),
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
        self.assertIn('Temporary password', body)
        self.assertIn('Staff ID', body)

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

    def test_classless_teacher_can_own_lesson_plans(self):
        """No class blocks class assignments, but not lesson plans."""
        self.login('admin@test.com', 'adminpass')
        self._add('Grace Bursar', '08031234567')
        email = self.set_password('Grace Bursar', 'knownpass123')
        self.logout()
        self.login(email, 'knownpass123')

        self.assertEqual(self.client.get('/lessons/').status_code, 200)

        response = self.client.get('/assignments/add', follow_redirects=True)
        self.assertIn(
            'not assigned to a class', response.get_data(as_text=True)
        )

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
