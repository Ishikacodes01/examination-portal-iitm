"""Login, logout, register and profile (shared by all roles)."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import ExaminerProfile, User, db

auth = Blueprint('auth', __name__)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(request.form.get('password', '')):
            flash('Wrong email or password.', 'danger')
        else:
            login_user(user)
            return redirect(url_for('index'))
    return render_template('login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    f = request.form
    if request.method == 'POST':
        role = f.get('role')
        name = f.get('name', '').strip()
        email = f.get('email', '').strip().lower()
        password = f.get('password', '')
        error = None
        if role not in ('student', 'examiner'):
            error = 'Please choose Student or Examiner.'
        elif not name or not email or len(password) < 6:
            error = 'Name, email and a password of at least 6 characters are required.'
        elif User.query.filter_by(email=email).first():
            error = 'That email is already registered.'
        elif role == 'examiner' and not f.get('department', '').strip():
            error = 'Department is required for examiners.'
        if error:
            flash(error, 'danger')
        else:
            user = User(name=name, email=email, role=role, contact=f.get('contact', '').strip())
            user.set_password(password)
            if role == 'student':
                user.roll_no = f.get('roll_no', '').strip()
            else:
                user.examiner_profile = ExaminerProfile(
                    department=f.get('department', '').strip(), status='Pending')
            db.session.add(user)
            db.session.commit()
            msg = 'Account created. Please sign in.'
            if role == 'examiner':
                msg += ' An admin must approve your account before you can use the dashboard.'
            flash(msg, 'success')
            return redirect(url_for('auth.login'))
    return render_template('register.html', f=f)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    u = current_user
    if request.method == 'POST':
        f = request.form
        name = f.get('name', '').strip()
        new_password = f.get('password', '')
        if not name:
            flash('Name cannot be empty.', 'danger')
        elif new_password and len(new_password) < 6:
            flash('A new password needs at least 6 characters.', 'danger')
        else:
            u.name = name
            u.contact = f.get('contact', '').strip()
            if u.role == 'student':
                u.roll_no = f.get('roll_no', '').strip()
            if u.role == 'examiner' and u.examiner_profile:
                u.examiner_profile.department = f.get('department', '').strip()
            if new_password:
                u.set_password(new_password)
            db.session.commit()
            flash('Profile updated.', 'success')
            return redirect(url_for('auth.profile'))
    return render_template('profile.html')
