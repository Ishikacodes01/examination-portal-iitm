# Examination Management Portal (EMP)

Flask + Flask-SQLAlchemy + Jinja2 + Bootstrap + SQLite. No JavaScript is used for any feature.

## Run it (local machine)

```bash
python -m venv venv
venv\Scripts\activate            # Windows      (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The database (`instance/emp.db`) and the admin account are created **by the code** on the first run.

| Role | Login |
|------|-------|
| Admin | `admin@emp.com` / `admin123` |

Optional sample data (courses, exams, examiners, students): `python seed_demo.py`
(then `examiner1@emp.com` / `exam123` and `student1@emp.com` / `stud123`).

## Files

| File | Job |
|------|-----|
| `app.py` | creates the app, database, admin account, registers the blueprints |
| `models.py` | all database tables |
| `utils.py` | role check, seat counting, marks formula, overlap check |
| `auth.py` | login, register, logout, edit profile |
| `admin.py` / `examiner.py` / `student.py` | the pages and rules for each role |
| `templates/` | Jinja2 pages (`base.html` = shared layout) |
| `static/css/` | Bootstrap (bundled, works offline) + `style.css` |

## Rules and where they live

| Rule | Where |
|------|-------|
| Slots only while slot creation is open | `Exam.slot_creation_open` in `models.py`, checked in `examiner.exam_slots` |
| Booking only while booking is open | `Exam.booking_open`, checked in `student.book` |
| No overbooking, slot closes when full | `student.book` + `refresh_slot` in `utils.py` |
| No duplicate booking for one exam | `student.book` (duplicate check) |
| Cancel only before the booking deadline | `student.cancel` |
| Examiner evaluates only their own students | `examiner.evaluate` (403 otherwise) |
| Slots editable only before booking starts | `Exam.booking_started`, `examiner.slot_edit` / `slot_delete` |
| Examiner needs admin approval | `role_required` in `utils.py` + `examiner.pending` |
| Full booking history | `BookingLog` table, shown on the student's "My bookings" page |

Note: this is a course project. Forms have no CSRF protection and `SECRET_KEY` is a placeholder.
