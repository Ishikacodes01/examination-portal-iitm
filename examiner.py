"""Everything an Examiner can do (only after the admin approves the account)."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import ACTIVE, Booking, Evaluation, EvaluationScore, Exam, Slot, db
from utils import (compute_total, examiner_clash, log_booking, parse_date, parse_time,
                   refresh_slot, role_required, to_number)

examiner = Blueprint('examiner', __name__, url_prefix='/examiner')
ex_only = role_required('examiner')


def my_slot_or_404(sid):
    """Examiners may only touch slots that belong to them."""
    slot = db.get_or_404(Slot, sid)
    if slot.examiner_id != current_user.id:
        abort(403)
    return slot


def read_slot_form(form):
    d = {
        'date': parse_date(form.get('date')),
        'start_time': parse_time(form.get('start_time')),
        'end_time': parse_time(form.get('end_time')),
        'capacity': to_number(form.get('capacity'), int),
        'venue': form.get('venue', '').strip(),
    }
    if d['date'] is None or d['start_time'] is None or d['end_time'] is None or not d['capacity']:
        return d, 'Date, start time, end time and capacity are required.'
    if d['date'] < date.today():
        return d, 'The slot date cannot be in the past.'
    if d['end_time'] <= d['start_time']:
        return d, 'End time must be after the start time.'
    if d['capacity'] < 1:
        return d, 'Capacity must be at least 1.'
    return d, None


@examiner.route('/pending')
@role_required('examiner', approved_only=False)
def pending():
    if current_user.is_approved:
        return redirect(url_for('examiner.dashboard'))
    return render_template('examiner/pending.html')


@examiner.route('/dashboard')
@ex_only
def dashboard():
    mine = Booking.query.join(Slot).filter(Slot.examiner_id == current_user.id)
    pending_list = (mine.filter(Booking.status == 'Booked')
                    .order_by(Slot.date, Slot.start_time).all())
    stats = [
        ('Assigned examinations', len(current_user.assigned_exams)),
        ('Slots created', Slot.query.filter_by(examiner_id=current_user.id).count()),
        ('Students booked', mine.filter(Booking.status.in_(ACTIVE)).count()),
        ('Pending evaluations', len(pending_list)),
    ]
    return render_template('examiner/dashboard.html', stats=stats, pending_list=pending_list,
                           exams=current_user.assigned_exams)


@examiner.route('/exams')
@ex_only
def exams():
    counts = {e.id: Slot.query.filter_by(exam_id=e.id, examiner_id=current_user.id).count()
              for e in current_user.assigned_exams}
    return render_template('examiner/exams.html', exams=current_user.assigned_exams, counts=counts)


@examiner.route('/exams/<int:eid>/slots', methods=['GET', 'POST'])
@ex_only
def exam_slots(eid):
    exam = db.get_or_404(Exam, eid)
    if current_user.id not in [u.id for u in exam.examiners]:
        abort(403)
    if request.method == 'POST':
        if not exam.slot_creation_open:
            flash('Slot creation is closed for this examination.', 'danger')
        else:
            data, error = read_slot_form(request.form)
            if not error:
                error = examiner_clash(current_user.id, data['date'], data['start_time'],
                                       data['end_time'])
            if error:
                flash(error, 'danger')
            else:
                db.session.add(Slot(exam_id=exam.id, examiner_id=current_user.id,
                                    available_seats=data['capacity'], status='Available', **data))
                db.session.commit()
                flash('Slot created.', 'success')
                return redirect(url_for('examiner.exam_slots', eid=eid))
    slots = (Slot.query.filter_by(exam_id=eid, examiner_id=current_user.id)
             .order_by(Slot.date, Slot.start_time).all())
    return render_template('examiner/exam_slots.html', exam=exam, slots=slots, f=request.form)


@examiner.route('/slots')
@ex_only
def slots():
    rows = (Slot.query.filter_by(examiner_id=current_user.id)
            .order_by(Slot.date, Slot.start_time).all())
    return render_template('examiner/slots.html', slots=rows)


@examiner.route('/slots/<int:sid>')
@ex_only
def slot_detail(sid):
    slot = my_slot_or_404(sid)
    bookings = [b for b in slot.bookings if b.status in ACTIVE]
    return render_template('examiner/slot_detail.html', slot=slot, bookings=bookings)


@examiner.route('/slots/<int:sid>/edit', methods=['GET', 'POST'])
@ex_only
def slot_edit(sid):
    slot = my_slot_or_404(sid)
    if slot.exam.booking_started or slot.status == 'Cancelled':
        flash('Slots can only be changed before booking starts.', 'warning')
        return redirect(url_for('examiner.slots'))
    if request.method == 'POST':
        f = request.form
        data, error = read_slot_form(f)
        if not error and data['capacity'] < slot.booked_count:
            error = 'Capacity cannot be lower than the students already booked.'
        if not error:
            error = examiner_clash(current_user.id, data['date'], data['start_time'],
                                   data['end_time'], ignore_id=slot.id)
        if error:
            flash(error, 'danger')
        else:
            for key, value in data.items():
                setattr(slot, key, value)
            db.session.flush()
            refresh_slot(slot)
            db.session.commit()
            flash('Slot updated.', 'success')
            return redirect(url_for('examiner.exam_slots', eid=slot.exam_id))
    else:
        f = {'date': slot.date, 'start_time': slot.start_time.strftime('%H:%M'),
             'end_time': slot.end_time.strftime('%H:%M'), 'capacity': slot.capacity,
             'venue': slot.venue}
    return render_template('examiner/slot_form.html', slot=slot, f=f)


@examiner.route('/slots/<int:sid>/delete', methods=['POST'])
@ex_only
def slot_delete(sid):
    slot = my_slot_or_404(sid)
    if slot.exam.booking_started:
        flash('Slots cannot be removed once booking has started.', 'warning')
    elif slot.booked_count:
        flash('Students are already booked in this slot.', 'warning')
    elif slot.bookings:               # only cancelled bookings -> keep history, mark cancelled
        slot.status = 'Cancelled'
        db.session.commit()
        flash('Slot cancelled.', 'success')
    else:
        db.session.delete(slot)
        db.session.commit()
        flash('Slot removed.', 'success')
    return redirect(url_for('examiner.exam_slots', eid=slot.exam_id))


@examiner.route('/evaluate/<int:bid>', methods=['GET', 'POST'])
@ex_only
def evaluate(bid):
    booking = db.get_or_404(Booking, bid)
    if booking.slot.examiner_id != current_user.id:       # only YOUR slots, YOUR students
        abort(403)
    if booking.status == 'Cancelled':
        flash('This booking was cancelled.', 'warning')
        return redirect(url_for('examiner.slots'))
    exam, rubrics, ev = booking.exam, booking.exam.rubrics, booking.evaluation
    if ev and ev.published:
        flash('Results are already published, so these marks are locked.', 'warning')
        return redirect(url_for('examiner.slot_detail', sid=booking.slot_id))
    old = {s.rubric_id: s.marks for s in ev.scores} if ev else {}

    if request.method == 'POST':
        marks, error, total = {}, None, None
        if rubrics:
            for r in rubrics:
                value = to_number(request.form.get(f'marks_{r.id}'))
                if value is None or value < 0 or value > r.max_marks:
                    error = f'Marks for "{r.criterion}" must be between 0 and {r.max_marks:g}.'
                    break
                marks[r.id] = value
            if not error:
                total = compute_total(exam, marks)
        else:
            total = to_number(request.form.get('total'))
            if total is None or total < 0 or total > exam.max_marks:
                error = f'Total marks must be between 0 and {exam.max_marks:g}.'
        if error:
            flash(error, 'danger')
        else:
            if not ev:
                ev = Evaluation(booking_id=booking.id)
                db.session.add(ev)
            ev.examiner_id = current_user.id
            ev.total_marks = total
            ev.remarks = request.form.get('remarks', '').strip()
            ev.evaluated_at = datetime.now()
            ev.scores = [EvaluationScore(rubric_id=rid, marks=m) for rid, m in marks.items()]
            booking.status = 'Completed'
            log_booking(booking, 'Evaluated', f'Marks saved: {total:g} / {exam.max_marks:g}')
            db.session.flush()
            refresh_slot(booking.slot)
            db.session.commit()
            flash('Marks and remarks saved.', 'success')
            return redirect(url_for('examiner.slot_detail', sid=booking.slot_id))
    return render_template('examiner/evaluate.html', booking=booking, exam=exam, rubrics=rubrics,
                           ev=ev, old=old, f=request.form)
