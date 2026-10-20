"""Everything a Student can do."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from models import ACTIVE, EXAM_TYPES, Booking, Course, Exam, Slot, db
from utils import log_booking, refresh_slot, role_required, to_number

student = Blueprint('student', __name__, url_prefix='/student')
stu_only = role_required('student')


def my_bookings():
    return Booking.query.filter_by(student_id=current_user.id).order_by(Booking.id.desc()).all()


@student.route('/dashboard')
@stu_only
def dashboard():
    today = date.today()
    mine = my_bookings()
    booked_exam_ids = {b.exam_id for b in mine if b.status in ACTIVE}
    bookable = [e for e in Exam.query.filter_by(status='Booking Open').all() if e.booking_open]
    available_exams = [e for e in bookable if e.id not in booked_exam_ids]
    open_slots = []
    if available_exams:
        open_slots = (Slot.query.filter(Slot.exam_id.in_([e.id for e in available_exams]),
                                        Slot.status == 'Available', Slot.date >= today)
                      .order_by(Slot.date, Slot.start_time).all())
    upcoming = sorted([b for b in mine if b.status == 'Booked' and b.slot.date >= today],
                      key=lambda b: (b.slot.date, b.slot.start_time))
    results = [b for b in mine if b.evaluation and b.evaluation.published]
    stats = [('Available examinations', len(available_exams)), ('Open slots', len(open_slots)),
             ('Upcoming examinations', len(upcoming)), ('Published results', len(results))]
    return render_template('student/dashboard.html', stats=stats, available_exams=available_exams,
                           open_slots=open_slots[:6], upcoming=upcoming, results=results[:5])


@student.route('/exams')
@stu_only
def exams():
    q = request.args.get('q', '').strip()
    etype = request.args.get('type', '')
    course_id = to_number(request.args.get('course_id'), int)
    only_open = bool(request.args.get('open'))
    query = Exam.query.join(Course).filter(Exam.status != 'Draft')
    if q:
        like = f'%{q}%'
        query = query.filter(or_(Exam.name.ilike(like), Course.code.ilike(like),
                                 Course.name.ilike(like)))
    if etype in EXAM_TYPES:
        query = query.filter(Exam.exam_type == etype)
    if course_id:
        query = query.filter(Exam.course_id == course_id)
    rows = query.order_by(Exam.booking_start).all()
    if only_open:
        rows = [e for e in rows if e.booking_open]
    booked_ids = {b.exam_id for b in my_bookings() if b.status in ACTIVE}
    return render_template('student/exams.html', exams=rows, booked_ids=booked_ids, q=q,
                           etype=etype, course_id=course_id, only_open=only_open,
                           courses=Course.query.order_by(Course.code).all())


@student.route('/exams/<int:eid>')
@stu_only
def exam_detail(eid):
    exam = db.get_or_404(Exam, eid)
    if exam.status == 'Draft':
        abort(404)
    slots = (Slot.query.filter(Slot.exam_id == eid, Slot.status != 'Cancelled')
             .order_by(Slot.date, Slot.start_time).all())
    current = Booking.query.filter(Booking.student_id == current_user.id, Booking.exam_id == eid,
                                   Booking.status.in_(ACTIVE)).first()
    return render_template('student/exam_detail.html', exam=exam, slots=slots, current=current)


@student.route('/slots/<int:sid>/book', methods=['POST'])
@stu_only
def book(sid):
    slot = db.get_or_404(Slot, sid)
    exam = slot.exam
    duplicate = Booking.query.filter(Booking.student_id == current_user.id,
                                     Booking.exam_id == exam.id,
                                     Booking.status.in_(ACTIVE)).first()
    if not exam.booking_open:
        flash('Booking is not open for this examination.', 'danger')
    elif duplicate:
        flash('You already have a booking for this examination.', 'warning')
    elif slot.date < date.today():
        flash('That slot is in the past.', 'danger')
    elif slot.status != 'Available' or slot.available_seats <= 0:
        flash('Sorry, that slot is full.', 'danger')
    else:
        booking = Booking(student_id=current_user.id, slot_id=slot.id, exam_id=exam.id)
        db.session.add(booking)
        db.session.flush()
        taken = Booking.query.filter(Booking.slot_id == slot.id,
                                     Booking.status.in_(ACTIVE)).count()
        if taken > slot.capacity:               # last safety net against overbooking
            db.session.rollback()
            flash('Sorry, that slot just filled up.', 'danger')
        else:
            log_booking(booking, 'Booked', f'Slot #{slot.id} on {slot.date}')
            refresh_slot(slot)                  # closes the slot if capacity is reached
            db.session.commit()
            flash('Slot booked!', 'success')
    return redirect(url_for('student.exam_detail', eid=exam.id))


@student.route('/bookings')
@stu_only
def bookings():
    return render_template('student/bookings.html', bookings=my_bookings())


@student.route('/bookings/<int:bid>/cancel', methods=['POST'])
@stu_only
def cancel(bid):
    booking = db.get_or_404(Booking, bid)
    if booking.student_id != current_user.id:
        abort(403)
    if booking.status != 'Booked':
        flash('Only active bookings can be cancelled.', 'warning')
    elif date.today() > booking.exam.booking_end:
        flash('The booking deadline has passed, so this booking can no longer be cancelled.',
              'danger')
    else:
        booking.status = 'Cancelled'
        booking.cancelled_at = datetime.now()
        log_booking(booking, 'Cancelled', 'Cancelled by the student')
        db.session.flush()
        refresh_slot(booking.slot)              # frees the seat (Full -> Available)
        db.session.commit()
        flash('Booking cancelled.', 'success')
    return redirect(url_for('student.bookings'))


@student.route('/results')
@stu_only
def results():
    rows = [b for b in my_bookings() if b.evaluation and b.evaluation.published]
    return render_template('student/results.html', bookings=rows)


@student.route('/results/<int:bid>')
@stu_only
def result_detail(bid):
    booking = db.get_or_404(Booking, bid)
    if booking.student_id != current_user.id or not (booking.evaluation and booking.evaluation.published):
        abort(404)
    return render_template('student/result_detail.html', booking=booking, ev=booking.evaluation)
