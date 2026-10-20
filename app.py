"""Examination Management Portal - run with:  python app.py"""
import os
from datetime import date

from flask import Flask, redirect, render_template, url_for
from flask_login import LoginManager, current_user

from admin import admin
from auth import auth
from examiner import examiner
from models import EXAM_STATUSES, EXAM_TYPES, User, db
from student import student


def create_app():
    app = Flask(__name__)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key')
    db_file = os.environ.get('EMP_DB_PATH', os.path.join(app.instance_path, 'emp.db'))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_file
    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    for bp in (auth, admin, examiner, student):
        app.register_blueprint(bp)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for(f'{current_user.role}.dashboard'))
        return redirect(url_for('auth.login'))

    # ---- template helpers ----
    @app.context_processor
    def inject_globals():
        return dict(EXAM_TYPES=EXAM_TYPES, EXAM_STATUSES=EXAM_STATUSES, today=date.today())

    @app.template_filter('datefmt')
    def datefmt(value):
        return value.strftime('%d %b %Y') if value else ''

    @app.template_filter('timefmt')
    def timefmt(value):
        return value.strftime('%I:%M %p') if value else ''

    @app.template_filter('dtfmt')
    def dtfmt(value):
        return value.strftime('%d %b %Y, %I:%M %p') if value else ''

    @app.template_filter('num')
    def num(value):
        return '' if value is None else '%g' % value

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('error.html', code=403,
                               message="You don't have permission to open this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', code=404, message='That page does not exist.'), 404

    # ---- create the database + the one pre-existing admin (no admin registration) ----
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role='admin').first():
            admin_user = User(name='Administrator', email='admin@emp.com', role='admin')
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            db.session.commit()
    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
