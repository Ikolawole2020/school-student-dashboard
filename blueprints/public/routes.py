# blueprints/public/routes.py
from flask import render_template, request, make_response, redirect, url_for, current_app, abort, Blueprint
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import Student, Result, Assignment
from utils import is_admin, is_teacher, current_student
from . import public_bp


@public_bp.route('/')
def home():
    """Public landing page.

    Surfaces the latest school news and a few testimonials, so a visitor sees
    the school is active without having to sign in.
    """
    from models import Post, Testimonial
    latest_assignments = (
        Assignment.query.order_by(Assignment.created_at.desc()).limit(3).all()
    )
    latest_posts = (
        Post.query.filter_by(is_published=True)
        .order_by(Post.published_at.desc()).limit(3).all()
    )
    testimonials = (
        Testimonial.query.filter_by(is_published=True)
        .order_by(Testimonial.sort_order.asc(), Testimonial.created_at.desc())
        .limit(3).all()
    )
    return render_template(
        'public/home.html',
        latest_assignments=latest_assignments,
        latest_posts=latest_posts,
        testimonials=testimonials,
    )


@public_bp.route('/check-result', methods=['GET', 'POST'])
@login_required
def check_result():
    """Result lookup.

    This used to accept any student ID typed into the form, so any logged-in
    account could read any other student's results. Students are now always
    scoped to their own record; only staff may look up another student.
    """
    student = None
    results = None
    class_name = None
    term = None
    error = None

    staff = is_admin() or is_teacher()

    if request.method == 'POST':
        sid = request.form.get('student_id', '').strip()
        class_name = request.form.get('class_name', '').strip()
        term = request.form.get('term', '').strip()

        if not staff:
            own = current_student()
            if not own:
                error = 'No student profile is linked to this account.'
            elif sid and sid != own.student_public_id:
                error = 'You can only view your own result.'
            else:
                student = own
        else:
            student = Student.query.filter_by(student_public_id=sid).first()
            if not student and sid:
                error = f'No student found with ID "{sid}".'

        if student and not error and class_name and term:
            results = Result.query.filter_by(
                student_id=student.id, class_name=class_name, term=term
            ).all()
            if not results:
                error = 'No results have been recorded for that class and term yet.'

    return render_template(
        'public/check_result.html', student=student, results=results,
        class_name=class_name, term=term, error=error, is_staff=staff,
    )

@public_bp.route('/download/result')
@login_required
def download_result():
    """Generate a downloadable HTML results page."""
    student_public_id = request.args.get('student_id', '').strip()
    class_name = request.args.get('class_name', '').strip()
    term = request.args.get('term', '').strip()
    
    # Determine the student
    is_staff = is_admin() or is_teacher()
    
    if is_staff:
        # Staff can download any student's results
        sid = request.args.get('student_id', '').strip()
        if sid:
            student = Student.query.filter_by(student_public_id=sid).first()
        else:
            student = Student.query.first()
        if not student:
            flash('No student found.', 'danger')
            return redirect(url_for('public.home'))
    else:
        # Students can only download their own results
        student = current_student()
        if not student or student.public_id != student_public_id:
            flash('You can only download your own results.', 'danger')
            return redirect(url_for('public.home'))
    
    # Get results for this student/class/term
    query = Result.query.filter_by(student_id=student.id)
    if class_name:
        query = query.filter_by(class_name=class_name)
    if term:
        query = query.filter_by(term=term)
    results = query.order_by(Result.class_name, Result.term, Result.subject).all()
    
    # Generate HTML content
    html_content = render_template(
        'partials/result_print.html',
        student=student,
        results=results,
        class_name=class_name,
        term=term,
    )
    
    # Return as downloadable HTML
    return make_response(html_content), 200, {
        'Content-Type': 'text/html',
        'Content-Disposition': f'attachment; filename=results_{student.public_id}_{class_name or "all"}_{term or "all"}.html'
    }


# Download route added to app directly - see app.py
# The URL is /download/result and is handled by the public blueprint logic
# But since app_bp isn't available here, we'll handle it differently
# Actually, let's just put this in the admin blueprint instead
# For now, redirect to home with a message
    """Generate a downloadable HTML results page."""
    student_public_id = request.args.get('student_id', '').strip()
    class_name = request.args.get('class_name', '').strip()
    term = request.args.get('term', '').strip()
    
    # Determine the student
    is_staff = is_admin() or is_teacher()
    
    if is_staff:
        # Staff can download any student's results
        sid = request.args.get('student_id', '').strip()
        if sid:
            student = Student.query.filter_by(student_public_id=sid).first()
        else:
            # Default to the first student if no ID provided
            student = Student.query.first()
        if not student:
            flash('No student found.', 'danger')
            return redirect(url_for('public.home'))
    else:
        # Students can only download their own results
        student = current_student()
        if not student or student.public_id != student_public_id:
            flash('You can only download your own results.', 'danger')
            return redirect(url_for('public.home'))
    
    # Get results for this student/class/term
    query = Result.query.filter_by(student_id=student.id)
    if class_name:
        query = query.filter_by(class_name=class_name)
    if term:
        query = query.filter_by(term=term)
    results = query.order_by(Result.class_name, Result.term, Result.subject).all()
    
    # Generate HTML content
    html_content = render_template(
        'partials/result_print.html',
        student=student,
        results=results,
        class_name=class_name,
        term=term,
    )
    
    # Return as downloadable HTML
    return make_response(html_content), 200, {
        'Content-Type': 'text/html',
        'Content-Disposition': f'attachment; filename=results_{student.public_id}_{class_name or "all"}_{term or "all"}.html'
    }



@public_bp.route('/search')
@login_required
def search():
    """Quick site search across students, teachers, classes and assignments.

    Results are scoped to what the signed-in role may see: a student only
    matches their own record, a teacher their class, an admin everything.
    """
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return render_template(
            'public/search.html', query=query, students=[], teachers=[],
            classes=[], assignments=[],
        )

    from models import Assignment, Teacher, Class
    from utils import is_admin, is_teacher, current_student

    like = f'%{query}%'
    students = []
    teachers = []
    assignments = []

    if is_admin():
        students = Student.query.filter(
            Student.name.ilike(like) | Student.student_public_id.ilike(like)
        ).order_by(Student.name).limit(25).all()
        teachers = Teacher.query.filter(
            Teacher.name.ilike(like) | Teacher.staff_id.ilike(like)
        ).order_by(Teacher.name).limit(25).all()
        assignments = Assignment.query.filter(
            Assignment.title.ilike(like) | Assignment.subject.ilike(like)
        ).order_by(Assignment.created_at.desc()).limit(25).all()
    elif is_teacher():
        teacher = Teacher.query.filter_by(user_id=current_user.id).first()
        if teacher:
            class_ids = [c.id for c in Class.query.filter_by(
                teacher_id=teacher.id
            ).all()]
            if class_ids:
                students = Student.query.filter(
                    Student.class_id.in_(class_ids)
                ).filter(
                    Student.name.ilike(like)
                    | Student.student_public_id.ilike(like)
                ).order_by(Student.name).limit(25).all()
            assignments = Assignment.query.filter(
                Assignment.teacher_id == teacher.id
            ).filter(
                Assignment.title.ilike(like) | Assignment.subject.ilike(like)
            ).order_by(Assignment.created_at.desc()).limit(25).all()
    else:
        me = current_student()
        if me and (
            me.name.lower() in query.lower()
            or me.student_public_id.lower() in query.lower()
        ):
            students = [me]

    classes = Class.query.filter(
        Class.class_name.ilike(like)
    ).order_by(Class.class_name).limit(25).all()

    return render_template(
        'public/search.html', query=query, students=students,
        teachers=teachers, classes=classes, assignments=assignments,
    )


@public_bp.route('/uploads/<path:filename>')
@login_required
def uploads(filename):
    """Serve a stored upload.

    send_from_directory already blocks traversal outside the upload folder;
    the extra check rejects anything that is not a plain basename.
    """
    if secure_filename(filename) != filename:
        abort(404)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
