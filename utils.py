"""Small helpers shared by all the route files."""
from datetime import datetime
from functools import wraps

from flask import abort, redirect, url_for
from flask_login import current_user, login_required

from models import ACTIVE, Booking, BookingLog, ExaminerProfile, Slot, User, db


def role_required(role, approved_only=True):
    """@role_required('admin') = must be logged in AND have that role.
    Examiners must also be approved by the admin (unless approved_only=False)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if current_user.role != role:
                abort(403)
            if role == 'examiner' and approved_only and not current_user.is_approved:
                return redirect(url_for('examiner.pending'))
            return view(*args, **kwargs)
        return login_required(wrapped)
    return decorator


def parse_date(text):
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def parse_time(text):
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).time()
        except (TypeError, ValueError):
            pass
    return None


def to_number(text, kind=float):
    try:
        return kind(text)
    except (TypeError, ValueError):
        return None


def approved_examiners():
    return (User.query.join(ExaminerProfile)
            .filter(User.role == 'examiner', ExaminerProfile.status == 'Approved')
            .order_by(User.name).all())


def log_booking(booking, action, note=''):
    db.session.add(BookingLog(booking=booking, action=action, note=note))


def refresh_slot(slot):
    """Recount seats and set the slot status. Call after ANY booking change."""
    taken = Booking.query.filter(Booking.slot_id == slot.id, Booking.status.in_(ACTIVE)).count()
    slot.available_seats = max(slot.capacity - taken, 0)
    if slot.status == 'Cancelled':
        return
    active = Booking.query.filter(Booking.slot_id == slot.id, Booking.status.in_(ACTIVE)).all()
    if active and all(b.status == 'Completed' for b in active):
        slot.status = 'Completed'
    elif slot.available_seats == 0:
        slot.status = 'Full'          # capacity reached -> slot closes automatically
    else:
        slot.status = 'Available'


def examiner_clash(examiner_id, day, start, end, ignore_id=None):
    """Return an error message if the examiner already has an overlapping slot that day."""
    query = Slot.query.filter(Slot.examiner_id == examiner_id, Slot.date == day,
                              Slot.status != 'Cancelled',
                              Slot.start_time < end, Slot.end_time > start)
    if ignore_id:
        query = query.filter(Slot.id != ignore_id)
    other = query.first()
    if other:
        return (f'This examiner already has a slot from {other.start_time:%H:%M} '
                f'to {other.end_time:%H:%M} on that day.')
    return None


def compute_total(exam, marks):
    """marks = {rubric_id: marks_given}.
    Each criterion becomes a fraction (given / max), is weighted by its weightage,
    then scaled to the exam's maximum marks."""
    rubrics = exam.rubrics
    weights = {r.id: r.weightage or 0 for r in rubrics}
    if sum(weights.values()) <= 0:               # no weightages entered -> equal weight
        weights = {r.id: 1 for r in rubrics}
    total_weight = sum(weights.values())
    score = sum(marks[r.id] / r.max_marks * weights[r.id] for r in rubrics)
    return round(score / total_weight * exam.max_marks, 2)
