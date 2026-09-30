"""One-off schema migration for the guardian phone column.

`db.create_all()` builds missing tables but never adds columns to tables
that already exist, so this upgrades an existing install. New installs get
the column straight from models.py and this script is a no-op for them.
"""
import os
import sqlite3

from app import create_app

app = create_app()

with app.app_context():
    db_path = os.path.join(app.instance_path, 'starlight.db')
    print(f'Database: {db_path}')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    existing = {
        row[1] for row in cursor.execute('PRAGMA table_info(student)').fetchall()
    }
    if 'guardian_phone' not in existing:
        cursor.execute('ALTER TABLE student ADD COLUMN guardian_phone VARCHAR(20)')
        print('Added student.guardian_phone')
    else:
        print('student.guardian_phone already present')

    # drop the plaintext password column if a previous install still has it
    if 'password' in existing:
        cursor.execute('ALTER TABLE student DROP COLUMN password')
        print('Dropped plaintext student.password column')
    else:
        print('student.password already absent')

    # teacher.gender is now nullable, because the add-teacher form no longer
    # asks for it. SQLite cannot relax NOT NULL with ALTER COLUMN, so the
    # table has to be rebuilt.
    teacher_cols = cursor.execute('PRAGMA table_info(teacher)').fetchall()
    gender_col = next((c for c in teacher_cols if c[1] == 'gender'), None)
    if gender_col and gender_col[3]:  # notnull flag set
        print('Rebuilding teacher table to make gender nullable...')
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('ALTER TABLE teacher RENAME TO teacher_old')
        cursor.execute("""
            CREATE TABLE teacher (
                id INTEGER NOT NULL PRIMARY KEY,
                staff_id VARCHAR(20) NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                dob DATE,
                gender VARCHAR(10),
                class_name VARCHAR(50),
                profile_picture VARCHAR(200),
                email VARCHAR(120) UNIQUE,
                phone VARCHAR(20),
                FOREIGN KEY(user_id) REFERENCES user (id)
            )
        """)
        cursor.execute("""
            INSERT INTO teacher
                (id, staff_id, user_id, name, dob, gender, class_name,
                 profile_picture, email, phone)
            SELECT id, staff_id, user_id, name, dob, gender, class_name,
                   profile_picture, email, phone
            FROM teacher_old
        """)
        cursor.execute('DROP TABLE teacher_old')
        cursor.execute('PRAGMA foreign_keys=ON')
        print('teacher.gender is now nullable')
    else:
        print('teacher.gender already nullable')

    # lesson_plan.class_name lets a teacher type a class that is not yet in
    # the Class table, instead of being forced to pick from a dropdown
    plan_cols = {
        row[1] for row in cursor.execute('PRAGMA table_info(lesson_plan)').fetchall()
    }
    if 'class_name' not in plan_cols:
        cursor.execute('ALTER TABLE lesson_plan ADD COLUMN class_name VARCHAR(50)')
        print('Added lesson_plan.class_name')
    else:
        print('lesson_plan.class_name already present')

    # assignment.class_name lets a teacher type a class that is not yet in the
    # Class table, instead of being forced to pick from a dropdown
    a_cols = {
        row[1] for row in cursor.execute('PRAGMA table_info(assignment)').fetchall()
    }
    if 'class_name' not in a_cols:
        cursor.execute('ALTER TABLE assignment ADD COLUMN class_name VARCHAR(50)')
        print('Added assignment.class_name')
    else:
        print('assignment.class_name already present')

    # class_id was NOT NULL before; it is now optional so an assignment can
    # target a class name that has not been created yet
    a_cols_info = cursor.execute('PRAGMA table_info(assignment)').fetchall()
    class_col = next((c for c in a_cols_info if c[1] == 'class_id'), None)
    if class_col and class_col[3]:  # notnull flag set
        print('Rebuilding assignment table to make class_id nullable...')
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('ALTER TABLE assignment RENAME TO assignment_old')
        cursor.execute("""
            CREATE TABLE assignment (
                id INTEGER NOT NULL PRIMARY KEY,
                title VARCHAR(150) NOT NULL,
                description TEXT,
                subject VARCHAR(80) NOT NULL,
                class_name VARCHAR(50),
                class_id INTEGER,
                teacher_id INTEGER,
                due_date DATE,
                max_score FLOAT NOT NULL,
                created_at DATETIME,
                FOREIGN KEY(class_id) REFERENCES class (id),
                FOREIGN KEY(teacher_id) REFERENCES teacher (id)
            )
        """)
        cursor.execute("""
            INSERT INTO assignment
                (id, title, description, subject, class_name, class_id,
                 teacher_id, due_date, max_score, created_at)
            SELECT a.id, a.title, a.description, a.subject,
                   COALESCE((SELECT c.class_name FROM class c
                             WHERE c.id = a.class_id), ''),
                   a.class_id, a.teacher_id, a.due_date, a.max_score, a.created_at
            FROM assignment_old a
        """)
        cursor.execute('DROP TABLE assignment_old')
        cursor.execute('PRAGMA foreign_keys=ON')
        print('assignment.class_id is now nullable')
    else:
        print('assignment.class_id already nullable')

    # clean up any table left behind by an interrupted rebuild
    stale = [
        r[0] for r in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE '%\\_old' ESCAPE '\\'"
        ).fetchall()
    ]
    for name in stale:
        cursor.execute(f'DROP TABLE IF EXISTS {name}')
        print(f'Dropped leftover table: {name}')

    # user.must_change_password forces a school-issued password to be replaced
    # at first login
    user_cols = {
        row[1] for row in cursor.execute('PRAGMA table_info(user)').fetchall()
    }
    if 'must_change_password' not in user_cols:
        cursor.execute(
            'ALTER TABLE user ADD COLUMN must_change_password BOOLEAN DEFAULT 0'
        )
        print('Added user.must_change_password')
    else:
        print('user.must_change_password already present')

    conn.commit()

    # create_all inside the app context has already made the new tables
    tables = {
        row[0] for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for name in (
        'assignment', 'assignment_score', 'assignment_media',
        'assignment_submission', 'assignment_submission_file',
        'lesson_plan', 'lesson_plan_image',
        'attendance_record', 'holiday',
    ):
        print(f'{name}: {"present" if name in tables else "MISSING"}')

    conn.close()

print('Migration complete.')
