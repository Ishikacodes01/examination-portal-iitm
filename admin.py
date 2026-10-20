"""Everything the Admin can do."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from sqlalchemy.orm import aliased

from models import (EXAM_TYPES, Booking, Course, EvaluationScore, Exam, ExaminerProfile,
                    Rubric, Slot, User, db)
from utils import (approved_examiners, examiner_clash, log_booking, parse_date, refresh_slot,
                   role_required, to_number)

admin = Blueprint('admin', __name__, url_prefix='/admin')
admin_only = role_required('admin')

DATE_FIELDS = ['slot_creation_start', 'slot_creation_end', 'booking_start', 'booking_end']

# action -> (button label, statuses it is allowed from, new status)
TRANSITIONS = {
    'open_slots':    ('Open slot creation',  ('Draft', 'Closed'), 'Slot Creation'),
    'close_slots':   ('Close slot creation', ('Slot Creation',), 'Draft'),
    'open_booking':  ('Open student booking', ('Draft', 'Slot Creation', 'Closed'), 'Booking Open'),
    'close_booking': ('Close student booking', ('Booking Open',), 'Closed'),
    'complete':      ('Mark completed', ('Booking Open', 'Closed'), 'Completed'),
}


# ------------------------------------------------------------------ dashboard
@admin.route('/dashboard')
@admin_only
def dashboard():
    stats = [
        ('Courses', Course.query.count(), 'admin.courses'),
        ('Examinations', Exam.query.count(), 'admin.exams'),
        ('Examiners', User.query.filter_by(role='examiner').count(), 'admin.examiners'),
        ('Students', User.query.filter_by(role='student').count(), 'admin.students'),
        ('Exam slots', Slot.query.count(), 'admin.slots'),
        ('Bookings', Booking.query.count(), 'admin.bookings'),
    ]
    pending = ExaminerProfile.query.filter_by(status='Pending').count()
    recent = Booking.query.order_by(Booking.id.desc()).limit(8).all()
    return render_template('admin/dashboard.html', stats=stats, pending=pending, recent=recent)


# ------------------------------------------------------------------ courses
@admin.route('/courses')
@admin_only
def courses():
    return render_template('admin/courses.html', courses=Course.query.order_by(Course.code).all())


@admin.route('/courses/new', defaults={'cid': None}, methods=['GET', 'POST'])
@admin.route('/courses/<int:cid>/edit', methods=['GET', 'POST'])
@admin_only
def course_form(cid):
    course = db.get_or_404(Course, cid) if cid else None
    if request.method == 'POST':
        f = request.form
        code = f.get('code', '').strip().upper()
        name = f.get('name', '').strip()
        clash = Course.query.filter(Course.code == code,
                                    Course.id != (course.id if course else 0)).first()
        if not code or not name:
            flash('Course code and name are required.', 'danger')
        elif clash:
            flash('Another course already uses that code.', 'danger')
        else:
            if not course:
                course = Course()
                db.session.add(course)
            course.code, course.name = code, name
            course.description = f.get('description', '').strip()
            course.department = f.get('department', '').strip()
            course.status = f.get('status') if f.get('status') in ('Active', 'Inactive') else 'Active'
            db.session.commit()
            flash('Course saved.', 'success')
            return redirect(url_for('admin.courses'))
    else:
        f = ({'code': course.code, 'name': course.name, 'description': course.description,
              'department': course.department, 'status': course.status}
             if course else {'status': 'Active'})
    return render_template('admin/course_form.html', course=course, f=f)


@admin.route('/courses/<int:cid>/delete', methods=['POST'])
@admin_only
def course_delete(cid):
    course = db.get_or_404(Course, cid)
    if course.exams:
        flash('This course has examinations, so it cannot be deleted. Mark it Inactive instead.',
              'warning')
    else:
        db.session.delete(course)
        db.session.commit()
        flash('Course deleted.', 'success')
    return redirect(url_for('admin.courses'))


# ------------------------------------------------------------------ examinations
@admin.route('/exams')
@admin_only
def exams():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    query = Exam.query.join(Course)
    if q:
        like = f'%{q}%'
        query = query.filter(or_(Exam.name.ilike(like), Course.code.ilike(like),
                                 Course.name.ilike(like)))
    if status:
        query = query.filter(Exam.status == status)
    return render_template('admin/exams.html', exams=query.order_by(Exam.id.desc()).all(),
                           q=q, status=status)


def read_exam_form(form):
    d = {
        'course_id': to_number(form.get('course_id'), int),
        'name': form.get('name', '').strip(),
        'exam_type': form.get('exam_type'),
        'duration': to_number(form.get('duration'), int),
        'max_marks': to_number(form.get('max_marks')),
        'instructions': form.get('instructions', '').strip(),
    }
    for key in DATE_FIELDS:
        d[key] = parse_date(form.get(key))
    if not d['name'] or d['exam_type'] not in EXAM_TYPES:
        return d, 'Please enter a name and choose a valid examination type.'
    if not db.session.get(Course, d['course_id'] or 0):
        return d, 'Please choose a course.'
    if not d['duration'] or d['duration'] <= 0 or not d['max_marks'] or d['max_marks'] <= 0:
        return d, 'Duration and maximum marks must be positive numbers.'
    if any(d[key] is None for key in DATE_FIELDS):
        return d, 'All four timeline dates are required.'
    if d['slot_creation_end'] < d['slot_creation_start'] or d['booking_end'] < d['booking_start']:
        return d, 'An end date cannot be before its start date.'
    return d, None


@admin.route('/exams/new', defaults={'eid': None}, methods=['GET', 'POST'])
@admin.route('/exams/<int:eid>/edit', methods=['GET', 'POST'])
@admin_only
def exam_form(eid):
    exam = db.get_or_404(Exam, eid) if eid else None
    if request.method == 'POST':
        f = request.form
        data, error = read_exam_form(f)
        if error:
            flash(error, 'danger')
        else:
            if not exam:
                exam = Exam(status='Draft')
                db.session.add(exam)
            for key, value in data.items():
                setattr(exam, key, value)
            db.session.commit()
            flash('Examination saved.', 'success')
            return redirect(url_for('admin.exam_detail', eid=exam.id))
    else:
        keys = ['course_id', 'name', 'exam_type', 'duration', 'max_marks', 'instructions'] + DATE_FIELDS
        f = {k: getattr(exam, k) for k in keys} if exam else {}
    return render_template('admin/exam_form.html', exam=exam, f=f,
                           courses=Course.query.order_by(Course.code).all())


@admin.route('/exams/<int:eid>/delete', methods=['POST'])
@admin_only
def exam_delete(eid):
    exam = db.get_or_404(Exam, eid)
    if exam.slots:
        flash('This examination already has slots, so it cannot be deleted. '
              'Set it to Closed or Completed instead.', 'warning')
        return redirect(url_for('admin.exam_detail', eid=eid))
    db.session.delete(exam)
    db.session.commit()
    flash('Examination deleted.', 'success')
    return redirect(url_for('admin.exams'))


@admin.route('/exams/<int:eid>')
@admin_only
def exam_detail(eid):
    exam = db.get_or_404(Exam, eid)
    actions = [(key, t[0]) for key, t in TRANSITIONS.items() if exam.status in t[1]]
    assigned_ids = {u.id for u in exam.examiners}
    free_examiners = [u for u in approved_examiners() if u.id not in assigned_ids]
    slots = Slot.query.filter_by(exam_id=eid).order_by(Slot.date, Slot.start_time).all()
    bookings = Booking.query.filter_by(exam_id=eid).order_by(Booking.id.desc()).all()
    return render_template('admin/exam_detail.html', exam=exam, actions=actions,
                           free_examiners=free_examiners, slots=slots, bookings=bookings)


@admin.route('/exams/<int:eid>/status', methods=['POST'])
@admin_only
def exam_status(eid):
    exam = db.get_or_404(Exam, eid)
    transition = TRANSITIONS.get(request.form.get('action'))
    if not transition or exam.status not in transition[1]:
        flash('That change is not allowed right now.', 'danger')
    else:
        exam.status = transition[2]
        db.session.commit()
        flash(f'Status is now "{exam.status}".', 'success')
    return redirect(url_for('admin.exam_detail', eid=eid))


@admin.route('/exams/<int:eid>/assign', methods=['POST'])
@admin_only
def exam_assign(eid):
    exam = db.get_or_404(Exam, eid)
    user = db.session.get(User, to_number(request.form.get('examiner_id'), int) or 0)
    if user and user.role == 'examiner' and user.is_approved and user not in exam.examiners:
        exam.examiners.append(user)
        db.session.commit()
        flash(f'{user.name} is now assigned to this examination.', 'success')
    else:
        flash('Choose an approved examiner.', 'danger')
    return redirect(url_for('admin.exam_detail', eid=eid))


@admin.route('/exams/<int:eid>/unassign/<int:uid>', methods=['POST'])
@admin_only
def exam_unassign(eid, uid):
    exam = db.get_or_404(Exam, eid)
    user = db.get_or_404(User, uid)
    if Slot.query.filter_by(exam_id=eid, examiner_id=uid).first():
        flash('This examiner already has slots here. Change the slot examiner first.', 'warning')
    elif user in exam.examiners:
        exam.examiners.remove(user)
        db.session.commit()
        flash('Examiner removed from this examination.', 'success')
    return redirect(url_for('admin.exam_detail', eid=eid))


@admin.route('/exams/<int:eid>/publish', methods=['POST'])
@admin_only
def exam_publish(eid):
    exam = db.get_or_404(Exam, eid)
    count = 0
    for booking in exam.bookings:
        if booking.evaluation and not booking.evaluation.published:
            booking.evaluation.published = True
            count += 1
    db.session.commit()
    flash(f'{count} result(s) published.' if count else 'No new evaluated results to publish.',
          'success' if count else 'info')
    return redirect(url_for('admin.exam_detail', eid=eid))


# ------------------------------------------------------------------ rubrics
def read_rubric_form(form):
    criterion = form.get('criterion', '').strip()
    max_marks = to_number(form.get('max_marks'))
    weightage = to_number(form.get('weightage'))
    if not criterion or not max_marks or max_marks <= 0 or weightage is None or weightage < 0:
        return None, 'A criterion name, positive maximum marks and a weightage (0 or more) are required.'
    return dict(criterion=criterion, max_marks=max_marks, weightage=weightage,
                description=form.get('description', '').strip()), None


@admin.route('/exams/<int:eid>/rubrics', methods=['POST'])
@admin_only
def rubric_add(eid):
    exam = db.get_or_404(Exam, eid)
    data, error = read_rubric_form(request.form)
    if error:
        flash(error, 'danger')
    else:
        db.session.add(Rubric(exam_id=exam.id, **data))
        db.session.commit()
        flash('Rubric criterion added.', 'success')
    return redirect(url_for('admin.exam_detail', eid=eid, _anchor='rubrics'))


@admin.route('/rubrics/<int:rid>/update', methods=['POST'])
@admin_only
def rubric_update(rid):
    rubric = db.get_or_404(Rubric, rid)
    data, error = read_rubric_form(request.form)
    if EvaluationScore.query.filter_by(rubric_id=rid).first():
        flash('Marks were already given with this criterion, so it is locked.', 'warning')
    elif error:
        flash(error, 'danger')
    else:
        for key, value in data.items():
            setattr(rubric, key, value)
        db.session.commit()
        flash('Rubric criterion updated.', 'success')
    return redirect(url_for('admin.exam_detail', eid=rubric.exam_id, _anchor='rubrics'))


@admin.route('/rubrics/<int:rid>/delete', methods=['POST'])
@admin_only
def rubric_delete(rid):
    rubric = db.get_or_404(Rubric, rid)
    eid = rubric.exam_id
    if EvaluationScore.query.filter_by(rubric_id=rid).first():
        flash('Marks were already given with this criterion, so it cannot be deleted.', 'warning')
    else:
        db.session.delete(rubric)
        db.session.commit()
        flash('Rubric criterion deleted.', 'success')
    return redirect(url_for('admin.exam_detail', eid=eid, _anchor='rubrics'))


# ------------------------------------------------------------------ examiners & students
@admin.route('/examiners')
@admin_only
def examiners():
    status = request.args.get('status', '')
    query = User.query.filter_by(role='examiner').join(ExaminerProfile)
    if status:
        query = query.filter(ExaminerProfile.status == status)
    return render_template('admin/users.html', kind='examiners', status=status,
                           users=query.order_by(User.name).all())


@admin.route('/examiners/add', methods=['POST'])
@admin_only
def examiner_add():
    f = request.form
    name, email = f.get('name', '').strip(), f.get('email', '').strip().lower()
    if not name or not email or len(f.get('password', '')) < 6 or not f.get('department', '').strip():
        flash('Name, email, department and a password (6+ characters) are required.', 'danger')
    elif User.query.filter_by(email=email).first():
        flash('That email is already registered.', 'danger')
    else:
        user = User(name=name, email=email, role='examiner', contact=f.get('contact', '').strip())
        user.set_password(f['password'])
        user.examiner_profile = ExaminerProfile(department=f['department'].strip(), status='Approved')
        db.session.add(user)
        db.session.commit()
        flash('Examiner added and approved.', 'success')
    return redirect(url_for('admin.examiners'))


@admin.route('/examiners/<int:uid>/<action>', methods=['POST'])
@admin_only
def examiner_action(uid, action):
    new_status = {'approve': 'Approved', 'deactivate': 'Deactivated',
                  'reactivate': 'Approved'}.get(action)
    user = db.get_or_404(User, uid)
    if user.role != 'examiner' or not new_status:
        flash('Invalid request.', 'danger')
    else:
        user.examiner_profile.status = new_status
        db.session.commit()
        flash(f'{user.name} is now {new_status.lower()}.', 'success')
    return redirect(url_for('admin.examiners'))


@admin.route('/students')
@admin_only
def students():
    return render_template('admin/users.html', kind='students', status='',
                           users=User.query.filter_by(role='student').order_by(User.name).all())


# ------------------------------------------------------------------ slots & bookings
@admin.route('/slots')
@admin_only
def slots():
    exam_id = to_number(request.args.get('exam_id'), int)
    query = Slot.query
    if exam_id:
        query = query.filter_by(exam_id=exam_id)
    return render_template('admin/slots.html', exam_id=exam_id, examiners=approved_examiners(),
                           slots=query.order_by(Slot.date, Slot.start_time).all(),
                           exams=Exam.query.order_by(Exam.name).all())


@admin.route('/slots/<int:sid>/examiner', methods=['POST'])
@admin_only
def slot_examiner(sid):
    slot = db.get_or_404(Slot, sid)
    user = db.session.get(User, to_number(request.form.get('examiner_id'), int) or 0)
    if not user or user.role != 'examiner' or not user.is_approved:
        flash('Choose an approved examiner.', 'danger')
    else:
        clash = examiner_clash(user.id, slot.date, slot.start_time, slot.end_time, ignore_id=slot.id)
        if clash:
            flash(clash, 'danger')
        else:
            slot.examiner_id = user.id
            if user not in slot.exam.examiners:
                slot.exam.examiners.append(user)
            db.session.commit()
            flash(f'Slot #{slot.id} is now assigned to {user.name}.', 'success')
    return redirect(request.referrer or url_for('admin.slots'))


@admin.route('/bookings')
@admin_only
def bookings():
    exam_id = to_number(request.args.get('exam_id'), int)
    status = request.args.get('status', '')
    query = Booking.query
    if exam_id:
        query = query.filter_by(exam_id=exam_id)
    if status:
        query = query.filter_by(status=status)
    return render_template('admin/bookings.html', exam_id=exam_id, status=status,
                           bookings=query.order_by(Booking.id.desc()).all(),
                           exams=Exam.query.order_by(Exam.name).all())


@admin.route('/bookings/<int:bid>/reschedule', methods=['GET', 'POST'])
@admin_only
def booking_reschedule(bid):
    booking = db.get_or_404(Booking, bid)
    if booking.status != 'Booked':
        flash('Only active bookings can be rescheduled.', 'warning')
        return redirect(url_for('admin.bookings'))
    options = (Slot.query.filter(Slot.exam_id == booking.exam_id, Slot.id != booking.slot_id,
                                 Slot.status == 'Available', Slot.available_seats > 0)
               .order_by(Slot.date, Slot.start_time).all())
    if request.method == 'POST':
        new_slot = db.session.get(Slot, to_number(request.form.get('slot_id'), int) or 0)
        if not new_slot or new_slot not in options:
            flash('Choose one of the available slots.', 'danger')
        else:
            old_slot = booking.slot
            booking.slot_id = new_slot.id
            db.session.flush()
            refresh_slot(old_slot)
            refresh_slot(new_slot)
            log_booking(booking, 'Rescheduled',
                        f'Admin moved this booking from slot #{old_slot.id} ({old_slot.date}) '
                        f'to slot #{new_slot.id} ({new_slot.date}).')
            db.session.commit()
            flash('Booking rescheduled.', 'success')
            return redirect(url_for('admin.bookings'))
    return render_template('admin/reschedule.html', booking=booking, options=options)


# ------------------------------------------------------------------ search
@admin.route('/search')
@admin_only
def search():
    q = request.args.get('q', '').strip()
    kind = request.args.get('type', 'students')
    results = []
    if q:
        like = f'%{q}%'
        number = to_number(q, int)
        if kind in ('students', 'examiners'):
            conds = [User.name.ilike(like), User.email.ilike(like)]
            if number:
                conds.append(User.id == number)
            role = 'student' if kind == 'students' else 'examiner'
            results = User.query.filter(User.role == role, or_(*conds)).all()
        elif kind == 'exams':
            conds = [Exam.name.ilike(like), Course.code.ilike(like), Course.name.ilike(like)]
            if number:
                conds.append(Exam.id == number)
            results = Exam.query.join(Course).filter(or_(*conds)).all()
        elif kind == 'bookings':
            student = aliased(User)
            conds = [student.name.ilike(like), Exam.name.ilike(like)]
            if number:
                conds += [Booking.id == number, Booking.student_id == number]
            results = (Booking.query.join(student, Booking.student).join(Exam, Booking.exam)
                       .filter(or_(*conds)).order_by(Booking.id.desc()).all())
    return render_template('admin/search.html', q=q, kind=kind, results=results)
