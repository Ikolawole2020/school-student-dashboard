# blueprints/content/routes.py
"""Public content: news, announcements and testimonials.

Anyone can read published posts. Only an admin can create or edit them.
"""
from datetime import datetime

from flask import (
    render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from extensions import db
from models import Post, PostImage, Testimonial
from forms import PostForm, TestimonialForm, CATEGORY_ICONS, CATEGORY_COLOURS
from utils import is_admin, save_upload, delete_upload, slugify
from . import content_bp


def _forbidden():
    return render_template('errors/403.html'), 403


def _require_admin():
    if not is_admin():
        return _forbidden()
    return None


def _attach_images(post, files):
    """Save gallery images, appending to whatever is already there."""
    if not files:
        return 0
    saved = 0
    for file in files:
        stored = save_upload(file, prefix=f'post{post.id}')
        if not stored:
            continue
        db.session.add(PostImage(post_id=post.id, filename=stored))
        saved += 1
    return saved


# ------------------------------------------------------------- public pages

@content_bp.route('/news')
def index():
    """The public news and announcements listing."""
    page = request.args.get('page', 1, type=int)
    per_page = 6

    query = Post.query.filter_by(is_published=True)

    category = request.args.get('category', '').strip()
    if category:
        query = query.filter_by(category=category)

    search = request.args.get('q', '').strip()
    if search:
        query = query.filter(
            Post.title.ilike(f'%{search}%') | Post.body.ilike(f'%{search}%')
        )

    pagination = query.order_by(Post.published_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        'content/index.html', posts=pagination.items,
        pagination=pagination, category=category, search=search,
        categories=[c for c, _ in CATEGORY_COLOURS.items()],
        icons=CATEGORY_ICONS, colours=CATEGORY_COLOURS,
    )


@content_bp.route('/news/<slug>')
def detail(slug):
    post = Post.query.filter_by(slug=slug, is_published=True).first_or_404()
    post.views = (post.views or 0) + 1
    db.session.commit()

    related = (
        Post.query.filter(Post.category == post.category, Post.id != post.id,
                          Post.is_published.is_(True))
        .order_by(Post.published_at.desc()).limit(3).all()
    )
    return render_template(
        'content/detail.html', post=post, related=related,
        icons=CATEGORY_ICONS, colours=CATEGORY_COLOURS,
    )


# ------------------------------------------------------------ admin: posts

@content_bp.route('/admin/news')
@login_required
def admin_posts():
    denied = _require_admin()
    if denied:
        return denied

    posts = Post.query.order_by(Post.published_at.desc()).all()
    return render_template(
        'content/admin_posts.html', posts=posts,
        icons=CATEGORY_ICONS, colours=CATEGORY_COLOURS,
    )


@content_bp.route('/admin/news/add', methods=['GET', 'POST'])
@login_required
def admin_add_post():
    denied = _require_admin()
    if denied:
        return denied

    form = PostForm()
    if form.validate_on_submit():
        post = Post(
            title=form.title.data.strip(),
            slug=slugify(form.title.data),
            summary=(form.summary.data or '').strip() or None,
            body=form.body.data,
            category=form.category.data,
            author=(form.author.data or '').strip() or None,
            is_published=bool(form.is_published.data),
            is_featured=bool(form.is_featured.data),
        )
        if form.cover_image.data and form.cover_image.data.filename:
            post.cover_image = save_upload(form.cover_image.data, prefix='cover')
        db.session.add(post)
        db.session.flush()  # need the id before attaching gallery images

        added = _attach_images(post, form.images.data)
        db.session.commit()
        flash(
            f'Post saved.'
            + (f' {added} gallery image(s) added.' if added else ''),
            'success',
        )
        return redirect(url_for('content.detail', slug=post.slug))

    return render_template('content/post_form.html', form=form, post=None)


@content_bp.route('/admin/news/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_post(id):
    denied = _require_admin()
    if denied:
        return denied

    post = db.session.get(Post, id) or abort(404)
    form = PostForm(obj=post)

    if form.validate_on_submit():
        post.title = form.title.data.strip()
        post.slug = slugify(form.title.data)
        post.summary = (form.summary.data or '').strip() or None
        post.body = form.body.data
        post.category = form.category.data
        post.author = (form.author.data or '').strip() or None
        post.is_published = bool(form.is_published.data)
        post.is_featured = bool(form.is_featured.data)

        if form.cover_image.data and form.cover_image.data.filename:
            new_cover = save_upload(form.cover_image.data, prefix='cover')
            if new_cover:
                delete_upload(post.cover_image)
                post.cover_image = new_cover

        added = _attach_images(post, form.images.data)
        db.session.commit()
        flash(
            f'Post updated.'
            + (f' {added} gallery image(s) added.' if added else ''),
            'success',
        )
        return redirect(url_for('content.detail', slug=post.slug))

    return render_template('content/post_form.html', form=form, post=post)


@content_bp.route('/admin/news/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_post(id):
    denied = _require_admin()
    if denied:
        return denied

    post = db.session.get(Post, id) or abort(404)
    delete_upload(post.cover_image)
    for image in post.images:
        delete_upload(image.filename)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'info')
    return redirect(url_for('content.admin_posts'))


@content_bp.route('/admin/news/<int:id>/toggle', methods=['POST'])
@login_required
def admin_toggle_post(id):
    """Quick publish / unpublish from the list."""
    denied = _require_admin()
    if denied:
        return denied

    post = db.session.get(Post, id) or abort(404)
    post.is_published = not post.is_published
    db.session.commit()
    flash(
        f'"{post.title}" is now '
        f'{"live on the public page" if post.is_published else "hidden"}.',
        'info',
    )
    return redirect(url_for('content.admin_posts'))


@content_bp.route('/admin/news/images/<int:image_id>/delete', methods=['POST'])
@login_required
def admin_delete_post_image(image_id):
    denied = _require_admin()
    if denied:
        return denied

    image = db.session.get(PostImage, image_id) or abort(404)
    post = image.post
    delete_upload(image.filename)
    db.session.delete(image)
    db.session.commit()
    flash('Image removed from the post.', 'info')
    return redirect(url_for('content.admin_edit_post', id=post.id))


# -------------------------------------------------------- admin: testimonials

@content_bp.route('/admin/testimonials')
@login_required
def admin_testimonials():
    denied = _require_admin()
    if denied:
        return denied

    rows = (
        Testimonial.query.order_by(
            Testimonial.sort_order.asc(), Testimonial.created_at.desc()
        ).all()
    )
    return render_template('content/admin_testimonials.html', testimonials=rows)


@content_bp.route('/admin/testimonials/add', methods=['GET', 'POST'])
@login_required
def admin_add_testimonial():
    denied = _require_admin()
    if denied:
        return denied

    form = TestimonialForm()
    if form.validate_on_submit():
        t = Testimonial(
            name=form.name.data.strip(),
            role=form.role.data,
            quote=form.quote.data.strip(),
            rating=form.rating.data or 5,
            is_published=bool(form.is_published.data),
            sort_order=form.sort_order.data or 0,
        )
        if form.avatar.data and form.avatar.data.filename:
            t.avatar = save_upload(form.avatar.data, prefix='tst')
        db.session.add(t)
        db.session.commit()
        flash('Testimonial saved.', 'success')
        return redirect(url_for('content.admin_testimonials'))

    return render_template(
        'content/testimonial_form.html', form=form, testimonial=None
    )


@content_bp.route('/admin/testimonials/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_testimonial(id):
    denied = _require_admin()
    if denied:
        return denied

    t = db.session.get(Testimonial, id) or abort(404)
    form = TestimonialForm(obj=t)

    if form.validate_on_submit():
        t.name = form.name.data.strip()
        t.role = form.role.data
        t.quote = form.quote.data.strip()
        t.rating = form.rating.data or 5
        t.is_published = bool(form.is_published.data)
        t.sort_order = form.sort_order.data or 0

        if form.avatar.data and form.avatar.data.filename:
            new_avatar = save_upload(form.avatar.data, prefix='tst')
            if new_avatar:
                delete_upload(t.avatar)
                t.avatar = new_avatar

        db.session.commit()
        flash('Testimonial updated.', 'success')
        return redirect(url_for('content.admin_testimonials'))

    return render_template(
        'content/testimonial_form.html', form=form, testimonial=t
    )


@content_bp.route('/admin/testimonials/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_testimonial(id):
    denied = _require_admin()
    if denied:
        return denied

    t = db.session.get(Testimonial, id) or abort(404)
    delete_upload(t.avatar)
    db.session.delete(t)
    db.session.commit()
    flash('Testimonial deleted.', 'info')
    return redirect(url_for('content.admin_testimonials'))
