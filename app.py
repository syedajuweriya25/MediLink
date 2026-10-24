from datetime import datetime, timedelta
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, Regexp
import sqlite3
import qrcode
import qrcode.image.svg
from zoneinfo import ZoneInfo
import os


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

connection = sqlite3.connect("user.db", check_same_thread=False)
cursor = connection.cursor()


# regex for username, email and password

USERNAME_VALIDATOR = Regexp(
    r"^[A-Za-z0-9_]{3,20}$",
    message="Username must be 3-20 characters and use only letters, numbers, or underscores.",
)
EMAIL_VALIDATOR = Regexp(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    message="Please enter a valid email address.",
)
PASSWORD_VALIDATOR = Regexp(
    r"^.{8,}$",
    message="Password must be at least 8 characters.",
)


# class for doctor registration form
class DoctorRegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(message="Name is required.")])
    username = StringField("Username", validators=[DataRequired(message="Username is required."), USERNAME_VALIDATOR])
    email = StringField("Email", validators=[DataRequired(message="Email is required."), EMAIL_VALIDATOR])
    password = PasswordField("Password", validators=[DataRequired(message="Password is required."), PASSWORD_VALIDATOR])
    info = StringField("About you (optional)")


# class for patient registration form
class PatientRegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(message="Name is required.")])
    username = StringField("Username", validators=[DataRequired(message="Username is required."), USERNAME_VALIDATOR])
    email = StringField("Email", validators=[DataRequired(message="Email is required."), EMAIL_VALIDATOR])
    password = PasswordField("Password", validators=[DataRequired(message="Password is required."), PASSWORD_VALIDATOR])


# login form for both
class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(message="Username is required.")])
    password = PasswordField("Password", validators=[DataRequired(message="Password is required.")])


# form for adding, editing, deleting, and joining slots
class SlotActionForm(FlaskForm):
    action = StringField(validators=[DataRequired()])
    slot_id = StringField()
    date = StringField()
    time = StringField()
    status = StringField()


# form for booking and joining appointments
class BookForm(FlaskForm):
    action = StringField(validators=[DataRequired()])
    slot_id = StringField(validators=[DataRequired(message="Please choose a slot.")])
    illness = StringField("Reason for visit (optional)")


# formats time and date
def slot_start_datetime(slot_date, slot_time):
    # takes time in HH:MM format if slot time is not provided, return None
    slot_time = (slot_time or "")[:5]
    try:
        # if valid date and time, return the datetime object
        return datetime.strptime(f"{slot_date} {slot_time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


# checks if the slot is currently happening returns boolean
def is_current_slot(slot_date, slot_time):
    start = slot_start_datetime(slot_date, slot_time)
    c_date, c_time = str(datetime.now(ZoneInfo("Asia/Kolkata"))).split(" ")
    current = slot_start_datetime(c_date, c_time)

    if start is None:
        return False
    if (start <= current < start + timedelta(minutes=30)):
        return True
    else:
        return False


# checks if slot time is over and returns boolean
def is_slot_over(slot_date, slot_time):
    start = slot_start_datetime(slot_date, slot_time)
    c_date, c_time = str(datetime.now(ZoneInfo("Asia/Kolkata"))).split(" ")
    current = slot_start_datetime(c_date, c_time)

    if start is None:
        return False
    if current > start + timedelta(minutes=30):
        return True
    else:
        return False


# type conversion of slot id
def parse_slot_id(value):
    try:
        slot_id = int(value)
    except (TypeError, ValueError):
        return None
    if slot_id < 1:
        return None
    return slot_id


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/doctor/register", methods=["GET", "POST"])
def doc_register():
    """registration page for doctor"""

    # taking data from form
    form = DoctorRegisterForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        info = (form.info.data or "").strip() or None
        password_hash = generate_password_hash(form.password.data)

        # values addding to db
        try:
            cursor.execute(
                """
                INSERT INTO doctors (name, username, email, password_hash, info, qr_filename)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, username, email, password_hash, info, "pending"),
            )
            doctor_id = cursor.lastrowid

            # generate a unique qr code for the doc
            qr_filename = f"qr_doctor_{doctor_id}.svg"
            profile_url = request.host_url + f"doctor/{doctor_id}"
            qr_image = qrcode.make(
                profile_url,
                image_factory=qrcode.image.svg.SvgPathImage,
            )
            # saving qr code and with name
            qr_image.save("static/" + qr_filename)

            # addding qr filename
            cursor.execute(
                "UPDATE doctors SET qr_filename = ? WHERE id = ?",
                (qr_filename, doctor_id),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            flash("That username or email is already registered.", "error")
            return render_template("doctor_register.html", form=form)

        flash("Doctor account created. You can now log in.", "success")
        return redirect("/")

    # if in via GET
    return render_template("doctor_register.html", form=form)


@app.route("/", methods=["GET", "POST"])
def doc_login():
    """doctors login page"""

    # if already logged in redirect to dashboard
    if session.get("role") == "doctor" and session.get("doctor_id"):
        return redirect(f"/dashboard/{session['doctor_id']}")

    # if not logged in, show login form
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        cursor.execute(
            "SELECT id, password_hash FROM doctors WHERE username = ?",
            (username,),
        )
        # if username and password matches, fetch the doctor id and password hash
        doctor = cursor.fetchone()

        # if username and password does not match, show error
        if doctor is None or not check_password_hash(doctor[1], password):
            flash("Invalid username or password.", "error")
            return render_template("doc.html", form=form)
        # session.clear()
        session["role"] = "doctor"
        session["doctor_id"] = doctor[0]
        return redirect(f"/dashboard/{doctor[0]}")

    # if in via GET
    return render_template("doc.html", form=form)

@app.route("/dashboard/<int:id>", methods=["GET", "POST"])
def dashboard(id):
    """doctor side- dashboard"""

    # if not logged in as a doctor or the doctor id does not match the id, show error
    if session.get("role") != "doctor" or session.get("doctor_id") != id:
        flash("Please log in as a doctor to view this dashboard.", "error")
        return redirect("/")

    # taking all the info of that doc from db
    cursor.execute(
        "SELECT id, name, info, qr_filename FROM doctors WHERE id = ?",
        (id,),
    )
    doctor_row = cursor.fetchone()
    if doctor_row is None:
        # if doctor account not found, show error
        flash("Doctor account not found.", "error")
        return redirect("/doctor/login")

    # slots adding, deleting, editing and joining part
    form = SlotActionForm()
    if form.validate_on_submit():
        action = (form.action.data or "").strip()
        slot_id = parse_slot_id(form.slot_id.data)
        slot_date = (form.date.data or "").strip()
        slot_time = (form.time.data or "").strip()[:5]
        status = (form.status.data or "").strip()

        if action == "add":
            # error checking
            if slot_start_datetime(slot_date, slot_time) is None:
                flash("Please choose a valid date and time.", "error")
            elif slot_start_datetime(slot_date, slot_time) < datetime.now():
                flash("You can only add a future appointment slot.", "error")
            else:
                # if no errors

                # check if there already  slots at that time
                cursor.execute(
                    """
                    SELECT id FROM slots
                    WHERE doctor_id = ? AND date = ? AND time = ?
                    """,
                    (id, slot_date, slot_time),
                )
                # if there is already a slot at that time and date
                if cursor.fetchone() is not None:
                    flash("That date and time already has a slot.", "error")
                else:
                    # no slot exits at that time add slot
                    cursor.execute(
                        """
                        INSERT INTO slots (doctor_id, date, time, status)
                        VALUES (?, ?, ?, 'available')
                        """,
                        (id, slot_date, slot_time),
                    )
                    connection.commit()
                    flash("Slot added.", "success")

        elif action in ("edit", "delete", "join"):
            if slot_id is None:
                flash("That slot could not be found.", "error")
            else:
                # from db check if slot exits
                cursor.execute(
                    """
                    SELECT id, date, time, status
                    FROM slots
                    WHERE id = ? AND doctor_id = ?
                    """,
                    (slot_id, id),
                )
                slot = cursor.fetchone()
                # if slot not in db
                if slot is None:
                    flash("You can only manage your own slots.", "error")

                # deleting a slot if not yet booked
                elif action == "delete":
                    if slot[3] == "booked":
                        flash("A booked slot cannot be deleted.", "error")
                    else:
                        cursor.execute(
                            "DELETE FROM slots WHERE id = ? AND doctor_id = ?",
                            (slot_id, id),
                        )
                        connection.commit()
                        flash("Slot deleted.", "success")
                # editing the slot if not yet booked
                elif action == "edit":
                    if slot[3] == "booked":
                        flash("A booked slot cannot be edited.", "error")
                    elif slot_start_datetime(slot_date, slot_time) is None:
                        flash("Please choose a valid date and time.", "error")
                    elif status not in ("available", "unavailable"):
                        flash("Status must be available or unavailable.", "error")
                    else:
                        cursor.execute(
                            """
                            SELECT id FROM slots
                            WHERE doctor_id = ? AND date = ? AND time = ? AND id != ?
                            """,
                            (id, slot_date, slot_time, slot_id),
                        )
                        # if at that datetime a slot exits then provide mssg
                        if cursor.fetchone() is not None:
                            flash("That date and time already has a slot.", "error")
                        # if not update
                        else:
                            cursor.execute(
                                """
                                UPDATE slots
                                SET date = ?, time = ?, status = ?
                                WHERE id = ? AND doctor_id = ? AND status != 'booked'
                                """,
                                (slot_date, slot_time, status, slot_id, id),
                            )
                            connection.commit()
                            flash("Slot updated.", "success")
                # starting the appointment
                elif action == "join":
                    if slot[3] != "booked" or not is_current_slot(slot[1], slot[2]):
                        flash("Join is only available during a booked appointment time.", "error")
                    else:
                        session["active_slot_id"] = slot_id
                        flash("You have joined this appointment.", "success")

        return redirect(f"/dashboard/{id}")

    # if form is not submitted, get the selected date from the url (for particular days appointment)
    selected_date = (request.args.get("date") or "").strip()

    # error checking
    if selected_date and slot_start_datetime(selected_date, "00:00") is None:
        selected_date = ""

    # selected date not none provide that days slot
    if selected_date:
        cursor.execute(
            """
            SELECT slots.id, slots.date, slots.time, slots.status,
                   patients.name, appointments.illness, appointments.patient_id
            FROM slots
            LEFT JOIN appointments ON appointments.slot_id = slots.id
            LEFT JOIN patients ON patients.id = appointments.patient_id
            WHERE slots.doctor_id = ? AND slots.date = ?
            ORDER BY slots.time
            """,
            (id, selected_date),
        )
    # if date not selected provide all the slots
    else:
        cursor.execute(
            """
            SELECT slots.id, slots.date, slots.time, slots.status,
                   patients.name, appointments.illness, appointments.patient_id
            FROM slots
            LEFT JOIN appointments ON appointments.slot_id = slots.id
            LEFT JOIN patients ON patients.id = appointments.patient_id
            WHERE slots.doctor_id = ?
            ORDER BY slots.date, slots.time
            """,
            (id,),
        )

    slots = []
    for row in cursor.fetchall():
        # if slot is valid append to slots list to return to template
        if not is_slot_over(row[1], row[2]):
            slots.append(
                {
                    "id": row[0],
                    "date": row[1],
                    "time": row[2][:5] if row[2] else row[2],
                    "status": row[3],
                    "patient_name": row[4],
                    "illness": row[5],
                    "is_current": is_current_slot(row[1], row[2]),
                }
            )

    active_appointment = None
    active_slot_id = session.get("active_slot_id")
    if active_slot_id:
        for slot in slots:
            # if active slot is booked and is currently available set it to current/active appointment
            if slot["id"] == active_slot_id and slot["status"] == "booked" and slot["is_current"]:
                active_appointment = slot
                break
        if active_appointment is None:
            # if no active appointment, pop/remove the active slot id
            session.pop("active_slot_id", None)

    # doctor info to show on dashboard
    doctor = {
        "id": doctor_row[0],
        "name": doctor_row[1],
        "info": doctor_row[2],
        "qr_filename": doctor_row[3],
    }

    # return all the info to template
    return render_template(
        "doc_dashboard.html",
        doctor=doctor,
        slots=slots,
        form=form,
        selected_date=selected_date,
        active_appointment=active_appointment,
    )

@app.route("/pateint/register", methods=["GET", "POST"])
def pat_register():
    """patient registration form"""

    # if submited geting data from form
    form = PatientRegisterForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        password_hash = generate_password_hash(form.password.data)

        # inserting into db and also error checking
        try:
            cursor.execute(
                """
                INSERT INTO patients (name, username, email, password_hash)
                VALUES (?, ?, ?, ?)
                """,
                (name, username, email, password_hash),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            flash("That username or email is already registered.", "error")
            return render_template("patient_register.html", form=form)

        flash("Patient account created. You can now log in.", "success")
        return redirect("/patient/login")

    return render_template("patient_register.html", form=form)


@app.route("/patient/login", methods=["GET", "POST"])
def pat_login():
    """patient login form"""

    # gets doctor id from the qr scan which is in the url
    scanned_doctor_id = request.args.get("doctor_id")

    if scanned_doctor_id is not None:
        try:
            scanned_doctor_id = int(scanned_doctor_id)
        except ValueError:
            # if doctor id is not an integer, set it to None
            scanned_doctor_id = None
        else:
            cursor.execute("SELECT id FROM doctors WHERE id = ?", (scanned_doctor_id,))
            if cursor.fetchone() is None:
                scanned_doctor_id = None
            else:
                # to remember the doctor id from the qr scan after login
                session["scanned_doctor_id"] = scanned_doctor_id

    # if already logged in redirect to doctor/id
    if session.get("role") == "patient" and session.get("patient_id"):
        doctor_id = session.get("scanned_doctor_id")
        if doctor_id:
            return redirect(f"/doctor/{doctor_id}")

    # login form and getting data
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        cursor.execute(
            "SELECT id, password_hash FROM patients WHERE username = ?",
            (username,),
        )
        patient = cursor.fetchone()

        # if patient does not exist or password error
        if patient is None or not check_password_hash(patient[1], password):
            flash("Invalid username or password.", "error")
            return render_template("pat_login.html", form=form)

        scanned_doctor_id = session.get("scanned_doctor_id")

        # remembering details
        session["role"] = "patient"
        session["patient_id"] = patient[0]

        # if scanned qr redirect to that doc profile
        if scanned_doctor_id:
            session["scanned_doctor_id"] = scanned_doctor_id
            return redirect(f"/doctor/{scanned_doctor_id}")

        # if not
        flash("You are logged in. Scan your doctor's QR code to book an appointment.", "success")
        return redirect("/patient/login")

    return render_template("pat_login.html", form=form)

@app.route("/doctor/<int:id>", methods=["GET", "POST"])
def doctor(id):
    """doctor's page but patient side page"""

    # getting doc info using id passed
    cursor.execute(
        "SELECT id, name, info FROM doctors WHERE id = ?",
        (id,),
    )
    doctor_row = cursor.fetchone()

    if doctor_row is None:
        flash("That doctor profile could not be found.", "error")
        return redirect("/patient/login")

    session["scanned_doctor_id"] = id
    # if role is patient then take patient id
    patient_id = session.get("patient_id") if session.get("role") == "patient" else None

    # booking slot and accesing the data provided
    form = BookForm()
    if form.validate_on_submit():
        if patient_id is None:
            flash("Please log in as a patient to book or join an appointment.", "error")
            # redirect to patient login with the doctor id
            return redirect(f"/patient/login?doctor_id={id}")

        action = (form.action.data or "").strip()
        slot_id = parse_slot_id(form.slot_id.data)
        illness = (form.illness.data or "").strip() or None

        # error checking
        if illness and len(illness) > 200:
            flash("Please keep the reason for visit under 200 characters.", "error")
            return redirect(f"/doctor/{id}")

        if slot_id is None:
            flash("Please choose a valid appointment slot.", "error")
            return redirect(f"/doctor/{id}")

        # getting all info of the slot
        cursor.execute(
            """
            SELECT slots.id, slots.date, slots.time, slots.status, appointments.patient_id
            FROM slots
            LEFT JOIN appointments ON appointments.slot_id = slots.id
            WHERE slots.id = ? AND slots.doctor_id = ?
            """,
            (slot_id, id),
        )
        slot = cursor.fetchone()
        # if slot not found
        if slot is None:
            flash("That appointment slot was not found.", "error")
            return redirect(f"/doctor/{id}")

        if action == "book":
            start = slot_start_datetime(slot[1], slot[2])
            if start is None:
                flash("That slot is no longer available to book.", "error")
            if slot[3] != "available":
                flash("That slot is not available.", "error")
            # if slot available then  update the status to booked
            else:
                cursor.execute(
                    """
                    UPDATE slots
                    SET status = 'booked'
                    WHERE id = ? AND doctor_id = ? AND status = 'available'
                    """,
                    (slot_id, id),
                )
                # if the slot was not booked, show error
                if cursor.rowcount != 1:
                    connection.rollback()
                    flash("That slot was just booked. Please choose another time.", "error")
                # if booked then add to appointments table
                else:
                    cursor.execute(
                        """
                        INSERT INTO appointments (doctor_id, patient_id, slot_id, illness)
                        VALUES (?, ?, ?, ?)
                        """,
                        (id, patient_id, slot_id, illness),
                    )
                    connection.commit()
                    flash("Your appointment is booked.", "success")

        # if action is join
        elif action == "join":
            # error checking
            if slot[3] != "booked" or slot[4] != patient_id:
                flash("You can only join an appointment you have booked.", "error")
            elif not is_current_slot(slot[1], slot[2]):
                flash("Join is only available at the appointment time.", "error")
            # if all conditions are right and slot is active remember via sessions
            else:
                session["active_slot_id"] = slot_id
                flash("You have joined your appointment.", "success")
        # if any invalid action selected
        else:
            flash("That action is not supported.", "error")

        return redirect(f"/doctor/{id}")

    # select all the slots from db to dispaly
    cursor.execute(
        """
        SELECT slots.id, slots.date, slots.time, slots.status, appointments.patient_id
        FROM slots
        LEFT JOIN appointments ON appointments.slot_id = slots.id
        WHERE slots.doctor_id = ?
        ORDER BY slots.date, slots.time
        """,
        (id,),
    )
    slots = []
    for row in cursor.fetchall():
        # if slot is valid and is of patient and the id matches patients id append
        if not is_slot_over(row[1], row[2]):
            is_mine = patient_id is not None and row[4] == patient_id
            slots.append(
                {
                    "id": row[0],
                    "date": row[1],
                    "time": row[2][:5] if row[2] else row[2],
                    "status": row[3],
                    "is_mine": is_mine,
                    "is_current": is_current_slot(row[1], row[2]),
                    "is_past": (slot_start_datetime(row[1], row[2]) or datetime.max) < datetime.now(),
                }
            )

    # stting active appointment is if all the conditions are correct
    active_appointment = None
    active_slot_id = session.get("active_slot_id")
    if active_slot_id:
        for slot in slots:
            if slot["id"] == active_slot_id and slot["is_mine"] and slot["is_current"]:
                active_appointment = slot
                break
        # if not remove active slot id
        if active_appointment is None and session.get("role") == "patient":
            session.pop("active_slot_id", None)

    # all the doctor info to display
    doctor = {
        "id": doctor_row[0],
        "name": doctor_row[1],
        "info": doctor_row[2],
    }

    # providing info to template
    return render_template(
        "doctor.html",
        doctor=doctor,
        slots=slots,
        form=form,
        patient_id=patient_id,
        active_appointment=active_appointment,
    )

@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")
