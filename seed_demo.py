"""Optional: fills the database with sample data so you can demo quickly.
Run once with:  python seed_demo.py
(Delete instance/emp.db first if you want to start fresh.)"""
from datetime import date, time, timedelta

from app import app
from models import (Booking, Course, Exam, ExaminerProfile, Rubric, Slot, User, db)
from utils import log_booking, refresh_slot


def make_user(name, email, role, password, **extra):
    user = User(name=name, email=email, role=role, **extra)
    user.set_password(password)
    db.session.add(user)
    return user


with app.app_context():
    if Course.query.first():
        raise SystemExit('Demo data is already there.')
    today = date.today()
    day = lambda n: today + timedelta(days=n)

    cs101 = Course(code='CS101', name='Introduction to Programming', department='Computer Science')
    ds201 = Course(code='DS201', name='Data Structures', department='Computer Science')
    db.session.add_all([cs101, ds201])

    meera = make_user('Dr. Meera Rao', 'examiner1@emp.com', 'examiner', 'exam123', contact='9000000001')
    meera.examiner_profile = ExaminerProfile(department='Computer Science', status='Approved')
    arjun = make_user('Prof. Arjun Nair', 'examiner2@emp.com', 'examiner', 'exam123', contact='9000000002')
    arjun.examiner_profile = ExaminerProfile(department='Mathematics', status='Approved')
    waiting = make_user('Dr. Kavya Iyer', 'examiner3@emp.com', 'examiner', 'exam123')
    waiting.examiner_profile = ExaminerProfile(department='Physics', status='Pending')

    students = [make_user(f'Student {i}', f'student{i}@emp.com', 'student', 'stud123',
                          roll_no=f'21F100{i}') for i in (1, 2, 3)]

    viva = Exam(course=cs101, name='Python Viva', exam_type='Viva', duration=15, max_marks=20,
                slot_creation_start=day(-5), slot_creation_end=day(3),
                booking_start=day(-1), booking_end=day(10), status='Booking Open',
                instructions='Bring your student ID. Be ready to explain your assignment code.')
    viva.examiners = [meera, arjun]
    viva.rubrics = [Rubric(criterion='Concepts', max_marks=10, weightage=40, description='Understanding of core ideas'),
                    Rubric(criterion='Coding', max_marks=10, weightage=40, description='Reads and writes code'),
                    Rubric(criterion='Communication', max_marks=5, weightage=20)]
    practical = Exam(course=ds201, name='DSA Practical', exam_type='Practical', duration=45,
                     max_marks=50, slot_creation_start=day(-1), slot_creation_end=day(7),
                     booking_start=day(8), booking_end=day(15), status='Slot Creation')
    practical.examiners = [meera]
    demo = Exam(course=ds201, name='Project Demo', exam_type='Project Demo', duration=20,
                max_marks=30, slot_creation_start=day(10), slot_creation_end=day(14),
                booking_start=day(15), booking_end=day(20), status='Draft')
    db.session.add_all([viva, practical, demo])
    db.session.flush()

    s1 = Slot(exam=viva, examiner=meera, date=day(3), start_time=time(10, 0), end_time=time(11, 0),
              capacity=2, available_seats=2, venue='Room 101')
    s2 = Slot(exam=viva, examiner=arjun, date=day(4), start_time=time(14, 0), end_time=time(15, 0),
              capacity=3, available_seats=3, venue='Room 102')
    db.session.add_all([s1, s2])
    db.session.flush()

    booking = Booking(student_id=students[0].id, slot_id=s1.id, exam_id=viva.id)
    db.session.add(booking)
    db.session.flush()
    log_booking(booking, 'Booked', f'Slot #{s1.id} on {s1.date}')
    refresh_slot(s1)
    db.session.commit()
    print('Demo data added.')
    print('Examiner: examiner1@emp.com / exam123   (examiner3@emp.com is waiting for approval)')
    print('Student : student1@emp.com / stud123')
