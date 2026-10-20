"""Database tables (Flask-SQLAlchemy). Every class below = one table."""
from datetime import date, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

EXAM_TYPES = ['Viva', 'Practical', 'Project Demo', 'Assessment']
EXAM_STATUSES = ['Draft', 'Slot Creation', 'Booking Open', 'Closed', 'Completed']
ACTIVE = ('Booked', 'Completed')  # booking statuses that still occupy a seat

# Many-to-many: which examiners are assigned to which examination
exam_examiners = db.Table(
    'exam_examiners',
    db.Column('exam_id', db.Integer, db.ForeignKey('exam.id'), primary_key=True),
    db.Column('examiner_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
)


class User(UserMixin, db.Model):
    """One table for all three roles: admin / examiner / student."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    contact = db.Column(db.String(20))
    roll_no = db.Column(db.String(30))  # students only
    created_at = db.Column(db.DateTime, default=datetime.now)

    examiner_profile = db.relationship('ExaminerProfile', back_populates='user',
                                       uselist=False, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_approved(self):
        """Admins and students are always 'approved'; examiners need the admin's OK."""
        if self.role != 'examiner':
            return True
        return bool(self.examiner_profile and self.examiner_profile.status == 'Approved')


class ExaminerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    department = db.Column(db.String(100))
    status = db.Column(db.String(20), default='Pending')  # Pending / Approved / Deactivated

    user = db.relationship('User', back_populates='examiner_profile')


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    department = db.Column(db.String(100))
    status = db.Column(db.String(20), default='Active')  # Active / Inactive

    exams = db.relationship('Exam', back_populates='course')


class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    exam_type = db.Column(db.String(30), nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # minutes
    max_marks = db.Column(db.Float, nullable=False)
    slot_creation_start = db.Column(db.Date, nullable=False)
    slot_creation_end = db.Column(db.Date, nullable=False)
    booking_start = db.Column(db.Date, nullable=False)
    booking_end = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Draft', nullable=False)
    instructions = db.Column(db.Text)

    course = db.relationship('Course', back_populates='exams')
    rubrics = db.relationship('Rubric', back_populates='exam', cascade='all, delete-orphan',
                              order_by='Rubric.id')
    slots = db.relationship('Slot', back_populates='exam', order_by='Slot.date')
    bookings = db.relationship('Booking', back_populates='exam')
    examiners = db.relationship('User', secondary=exam_examiners, backref='assigned_exams')

    # Two locks must both be "open": the admin's switch (status) AND the date window.
    @property
    def slot_creation_open(self):
        return (self.status == 'Slot Creation'
                and self.slot_creation_start <= date.today() <= self.slot_creation_end)

    @property
    def booking_open(self):
        return (self.status == 'Booking Open'
                and self.booking_start <= date.today() <= self.booking_end)

    @property
    def booking_started(self):
        return self.status in ('Booking Open', 'Closed', 'Completed')

    @property
    def total_weightage(self):
        return sum(r.weightage for r in self.rubrics)


class Rubric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    criterion = db.Column(db.String(150), nullable=False)
    max_marks = db.Column(db.Float, nullable=False)
    weightage = db.Column(db.Float, default=0)  # percentage
    description = db.Column(db.Text)

    exam = db.relationship('Exam', back_populates='rubrics')


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    available_seats = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='Available')  # Available / Full / Cancelled / Completed
    venue = db.Column(db.String(100))

    exam = db.relationship('Exam', back_populates='slots')
    examiner = db.relationship('User', foreign_keys=[examiner_id], backref='slots')
    bookings = db.relationship('Booking', back_populates='slot')

    @property
    def booked_count(self):
        return Booking.query.filter(Booking.slot_id == self.id, Booking.status.in_(ACTIVE)).count()


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('slot.id'), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='Booked')  # Booked / Cancelled / Completed
    cancelled_at = db.Column(db.DateTime)

    student = db.relationship('User', foreign_keys=[student_id], backref='bookings')
    slot = db.relationship('Slot', back_populates='bookings')
    exam = db.relationship('Exam', back_populates='bookings')
    evaluation = db.relationship('Evaluation', back_populates='booking', uselist=False)
    logs = db.relationship('BookingLog', back_populates='booking', order_by='BookingLog.id',
                           cascade='all, delete-orphan')


class BookingLog(db.Model):
    """Every booking / cancel / reschedule / evaluation is written here = full history."""
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now)

    booking = db.relationship('Booking', back_populates='logs')


class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), unique=True, nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_marks = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.Text)
    published = db.Column(db.Boolean, default=False)
    evaluated_at = db.Column(db.DateTime, default=datetime.now)

    booking = db.relationship('Booking', back_populates='evaluation')
    examiner = db.relationship('User', foreign_keys=[examiner_id])
    scores = db.relationship('EvaluationScore', back_populates='evaluation',
                             cascade='all, delete-orphan')


class EvaluationScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluation.id'), nullable=False)
    rubric_id = db.Column(db.Integer, db.ForeignKey('rubric.id'), nullable=False)
    marks = db.Column(db.Float, nullable=False)

    evaluation = db.relationship('Evaluation', back_populates='scores')
    rubric = db.relationship('Rubric')
