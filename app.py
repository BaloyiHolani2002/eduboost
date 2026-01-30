# ===========================================================
# IMPORTS
# ===========================================================
# Standard library
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse
from functools import wraps

# Third-party
from flask import Flask, render_template, request, redirect, session, flash, jsonify, url_for, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename


# ===========================================================
# FLASK APP CONFIG
# ===========================================================
app = Flask(__name__)
app.secret_key = 'edu-boost-up-secret-key-2024'  # CHANGE WHEN GOING LIVE
app.config['UPLOAD_FOLDER'] = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ===========================================================
# LOCAL DATABASE CONFIG (fallback)
# ===========================================================
LOCAL_DB = {
    'host': 'localhost',
    'database': 'eduboostup',
    'user': 'postgres',
    'password': 'Admin2023',
    'port': '5432'
}


# ===========================================================
# START SCHEDULER
# ===========================================================
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()  # Start scheduler immediately


# ===========================================================
# DATABASE CONNECTION HANDLER (LOCAL OR RAILWAY)
# ===========================================================
def get_db_connection():
    """
    Connect to Railway PostgreSQL if DATABASE_URL exists,
    otherwise connect to the local PostgreSQL database.
    """
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")

        if DATABASE_URL:
            # -----------------------------------------------------------
            # RAILWAY DATABASE CONNECTION
            # -----------------------------------------------------------
            result = urlparse(DATABASE_URL)

            conn = psycopg2.connect(
                database=result.path[1:],  # remove "/" at the start
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port
            )

            print("🌍 Connected to RAILWAY PostgreSQL")
            return conn

        else:
            # -----------------------------------------------------------
            # LOCAL DATABASE CONNECTION
            # -----------------------------------------------------------
            conn = psycopg2.connect(
                host=LOCAL_DB['host'],
                database=LOCAL_DB['database'],
                user=LOCAL_DB['user'],
                password=LOCAL_DB['password'],
                port=LOCAL_DB['port']
            )

            print("🖥 Connected to LOCAL PostgreSQL")
            return conn

    except Exception as e:
        print(f"❌ DATABASE CONNECTION ERROR: {e}")
        return None


# ===========================================================
# HOME ROUTE
# ===========================================================
@app.route('/')
def index():
    return render_template('index.html')


# ===========================================================
# SAMPLE TEST ROUTE FOR DATABASE CHECK
# ===========================================================
@app.route('/check-db')
def check_db():
    conn = get_db_connection()

    if not conn:
        return "❌ Could not connect to any database."

    cursor = conn.cursor()
    cursor.execute("SELECT NOW();")
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return f"✅ Database connected successfully! TIME = {result[0]}"


# ===========================================================
# SIGN UP PAGES AND RESET PASSWORD
# ===========================================================

def calculate_id_score(id_number):
    results = {'score': 0, 'age': None, 'messages': [], 'passed': False}

    if len(id_number) != 13 or not id_number.isdigit():
        results['messages'].append("ID must be 13 digits")
        return results

    results['score'] += 10  # passed basic check

    try:
        year = int(id_number[0:2])
        month = int(id_number[2:4])
        day = int(id_number[4:6])

        full_year = 2000 + year if year <= 21 else 1900 + year
        birth_date = datetime(full_year, month, day)

        today = datetime.now()
        age = today.year - birth_date.year
        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age -= 1

        results['age'] = age

        if 13 <= age <= 25:
            results['score'] += 15
        else:
            results['messages'].append(f"Age {age} not in 13-25 range")

    except ValueError:
        results['messages'].append("Invalid birth date in ID")
        return results

    if id_number[10] in ['0', '1']:
        results['score'] += 5
    else:
        results['messages'].append("Invalid citizenship digit")

    if luhn_check(id_number):
        results['score'] += 20
    else:
        results['messages'].append("Checksum invalid")

    results['passed'] = results['score'] >= 40
    return results


def luhn_check(id_num):
    digits = [int(d) for d in id_num]
    first12 = digits[:12]

    sum_odd = sum(first12[0::2])
    even_digits = ''.join(str(d) for d in first12[1::2])
    if even_digits == "":
        return False

    even_mult = int(even_digits) * 2
    sum_even_digits = sum(int(c) for c in str(even_mult))

    total = sum_odd + sum_even_digits
    computed_check = (10 - (total % 10)) % 10

    return computed_check == digits[12]


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # Check if registration is open
    if request.method == 'GET':
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT message FROM Notification 
                WHERE notification_type = 'registration_status' 
                ORDER BY date_sent DESC LIMIT 1
            """)
            notification = cur.fetchone()
            
            if notification and 'closed' in notification[0].lower():
                return redirect('/registration-closed')
                
        except Exception as e:
            print(f"Error checking registration status: {e}")
        finally:
            cur.close()
            conn.close()
    
    if request.method == 'POST':

        student_id = request.form.get('student_id')
        name = request.form.get('name')
        surname = request.form.get('surname')
        email = request.form.get('email')
        phone = request.form.get('phone')
        grade = request.form.get('grade')
        password = request.form.get('password')

        # --- ID VALIDATION ---
        score_info = calculate_id_score(student_id)
        if score_info['score'] < 40:
            return render_template("singuperror.html",
                                   error_message=f"ID validation failed: {score_info['messages']}")

        age = score_info['age']
        if not age:
            return render_template("singuperror.html",
                                   error_message="Could not calculate age")

        if age < 13 or age > 25:
            return render_template("singuperror.html",
                                   error_message=f"Age {age} not allowed (13–25 only)")

        # --- GRADE CHECK ---
        try:
            grade_num = int(grade)
            if grade_num < 10 or grade_num > 12:
                return render_template("singuperror.html",
                                       error_message="Grade must be 10, 11 or 12.")
        except:
            return render_template("singuperror.html",
                                   error_message="Invalid grade format.")

        # --- CONNECT DB ---
        conn = get_db_connection()
        if not conn:
            return render_template("singuperror.html",
                                   error_message="Database connection failed.")

        try:
            cur = conn.cursor()

            # Check email
            cur.execute("SELECT email FROM Student WHERE email=%s", (email,))
            if cur.fetchone():
                return render_template("singupIdUsed.html",
                                       error_message="Email already registered.")

            # Check student ID
            cur.execute("SELECT student_id FROM Student WHERE student_id=%s", (student_id,))
            if cur.fetchone():
                return render_template("singupIdUsed.html",
                                       error_message="Student ID already registered.")

            # Hash password
            hashed_password = generate_password_hash(password)

            # Insert student
            cur.execute("""
                INSERT INTO Student (student_id, name, surname, email, password, grade, phone)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (student_id, name, surname, email, password, grade, phone))

            # Insert enrollment
            cur.execute("""
                INSERT INTO Enrollment (student_id, enrollment_days, days_remaining, status)
                VALUES (%s, 20, 20, 'active')
            """, (student_id,))

            conn.commit()
            cur.close()
            conn.close()

            # Session
            session['user_id'] = student_id
            session['user_name'] = f"{name} {surname}"
            session['user_role'] = "student"
            session['grade'] = grade
            session['age'] = age

            return render_template("successfullsingup.html",
                                   student_name=f"{name} {surname}",
                                   student_id=student_id,
                                   grade=grade,
                                   age=age)

        except Exception as e:
            if conn:
                conn.close()
            return render_template("singuperror.html", error_message=f"Registration failed: {e}")

    return render_template("signup.html")


# ✅ Schedule job to run daily at midnight (00:00)
@scheduler.task('cron', id='reduce_days_job', hour=0, minute=0)
def scheduled_reduce_days():
    print("⏰ Scheduled job triggered at midnight")
    reduce_enrollment_days()


def reduce_enrollment_days():
    """Reduce enrollment days by 1 for all active enrollments WITHOUT updating any date fields."""
    conn = get_db_connection()
    if not conn:
        print("❌ DB connection failed for daily reduction")
        return
    
    try:
        cur = conn.cursor()
        print("🔄 Running daily reduction WITHOUT updating date...")

        # Only reduce days_remaining (do NOT touch last_updated)
        cur.execute("""
            UPDATE Enrollment
            SET days_remaining = days_remaining - 1
            WHERE status = 'active'
            AND days_remaining > 0
        """)
        
        reduced = cur.rowcount

        # Mark expired without touching last_updated
        cur.execute("""
            UPDATE Enrollment
            SET status = 'expired'
            WHERE status = 'active'
            AND days_remaining <= 0
        """)
        
        expired = cur.rowcount

        conn.commit()
        print(f"✅ Reduced: {reduced}, Expired: {expired}")

    except Exception as e:
        conn.rollback()
        print("❌ Error:", str(e))

    finally:
        cur.close()
        conn.close()


# ===========================================================
#  LOGIN FOR ALL USERS AND RESET PASSWORD
# ===========================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Validate input
        if not email or not password:
            return render_template('login.html', 
                                error='Please enter both email and password',
                                email=email)

        conn = get_db_connection()
        if not conn:
            return render_template('login.html', 
                                error='Database connection failed. Please try again.',
                                email=email)

        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check Student
            cur.execute("""
                SELECT * FROM Student 
                WHERE email = %s AND password = %s AND status = 'active'
            """, (email, password))
            student = cur.fetchone()

            if student:
                session['user_id'] = student['student_id']
                session['user_name'] = f"{student['name']} {student['surname']}"
                session['grade'] = student['grade']
                session['user_role'] = 'student'
                session['email'] = email
                cur.close()
                conn.close()
                
                # Redirect based on user role
                return redirect('/student/dashboard')

            # Check Mentor
            cur.execute("""
                SELECT * FROM Mentor
                WHERE email = %s AND password = %s AND status = 'active'
            """, (email, password))
            mentor = cur.fetchone()
            
            if mentor:
                session['user_id'] = mentor['mentor_id']
                session['user_name'] = f"{mentor['name']} {mentor['surname']}"
                session['user_role'] = 'mentor'
                session['email'] = email
                cur.close()
                conn.close()
                return redirect('/employee/dashboard')

            # Check Admin
            cur.execute("""
                SELECT * FROM Admin 
                WHERE email = %s AND password = %s
            """, (email, password))
            admin = cur.fetchone()
            
            if admin:
                session['user_id'] = admin['admin_id']
                session['user_name'] = admin['name']
                session['user_role'] = 'admin'
                session['role'] = admin['role']
                session['email'] = email
                cur.close()
                conn.close()
                return redirect('/admin/dashboard')

            cur.close()
            conn.close()
            
            # If no user found with these credentials
            return render_template('login.html', 
                                error='Invalid email or password. Please try again.',
                                email=email)

        except Exception as e:
            print("LOGIN ERROR:", e)
            if conn:
                cur.close()
                conn.close()
            return render_template('login.html', 
                                error='Server error. Please try again later.',
                                email=email)

    # GET request - show login form
    return render_template('login.html')


# ---------- Step 1: Identity confirmation (Email only) ----------
@app.route("/reset", methods=["GET", "POST"])
def reset_request():
    if request.method == "POST":
        email = request.form.get("email").strip()

        if not email:
            flash("❌ Please enter your email.", "danger")
            return render_template("reset_request.html")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Check if student exists
            cur.execute("""
                SELECT student_id, email 
                FROM Student 
                WHERE email = %s
            """, (email,))
            student = cur.fetchone()

            if student:
                # Save temporary session info for reset
                session['reset_student_id'] = student['student_id']
                session['reset_email'] = student['email']
                flash("✅ Identity confirmed. You can now reset your password.", "success")
                return redirect("/reset/password")
            else:
                flash("❌ Email not found. Please check and try again.", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template("reset_request.html")


# ---------- Step 2: Reset password ----------
@app.route("/reset/password", methods=["GET", "POST"])
def reset_password():
    if 'reset_student_id' not in session or 'reset_email' not in session:
        flash("Please confirm your email first.", "warning")
        return redirect("/reset")

    if request.method == "POST":
        new_password = request.form.get("new_password").strip()
        confirm_password = request.form.get("confirm_password").strip()

        if not new_password or not confirm_password:
            flash("Please fill in all fields.", "danger")
        elif new_password != confirm_password:
            flash("Passwords do not match.", "danger")
        else:
            student_id = session['reset_student_id']
            email = session['reset_email']

            conn = get_db_connection()
            cur = conn.cursor()
            try:
                # Update student password (hashing recommended!)
                cur.execute("""
                    UPDATE Student 
                    SET password = %s 
                    WHERE student_id = %s AND email = %s
                """, (new_password, student_id, email))
                conn.commit()

                flash("✅ Password reset successful. Please log in.", "success")

                # Clear session info
                session.pop('reset_student_id')
                session.pop('reset_email')

                return redirect("/login")
            finally:
                cur.close()
                conn.close()

    return render_template("reset_password.html")


# ===========================================================
#  STUDENT DESHBOARD AND FANTIONALITIES
# ===========================================================
# ------------------------------
# STUDENT DASHBOARD
# ------------------------------
@app.route("/student/dashboard")
def student_dashboard():
    # 1️⃣ Check student login
    if 'user_role' not in session or session['user_role'] != 'student':
        return redirect('/login')

    student_id = session['user_id']
    grade = session.get('grade')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 2️⃣ Get student profile
        cur.execute("SELECT * FROM Student WHERE student_id = %s", (student_id,))
        student = cur.fetchone()

        if not student:
            session.clear()
            return redirect('/login')

        # 3️⃣ Get OR create student enrollment
        cur.execute("""
            SELECT days_remaining FROM Enrollment
            WHERE student_id = %s AND status = 'active'
            ORDER BY enrollment_id DESC LIMIT 1
        """, (student_id,))
        enroll = cur.fetchone()

        days_remaining = enroll['days_remaining'] if enroll else 0

        # 4️⃣ Load mentors with images
        cur.execute("""
            SELECT mentor_id, name, surname, subject_speciality, bio, profile_image, phone
            FROM Mentor
            WHERE status = 'active'
            ORDER BY name ASC
        """)
        mentors = cur.fetchall()

        # 5️⃣ Load subjects for this student's grade
        cur.execute("""
            SELECT DISTINCT subject
            FROM Content
            WHERE grade = %s
            ORDER BY subject
        """, (grade,))
        courses = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    # 6️⃣ Render dashboard
    return render_template(
        "student_dashboard.html",
        student=student,
        mentors=mentors,
        courses=courses,
        days_remaining=days_remaining
    )


@app.route("/student/profile", methods=['GET', 'POST'])
def student_profile():
    # Ensure user is logged in AND is a student
    if 'user_role' not in session or session['user_role'] != 'student':
        return redirect('/login')

    student_id = session['user_id']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch student info
    cur.execute("SELECT * FROM Student WHERE student_id = %s", (student_id,))
    student = cur.fetchone()

    if not student:
        session.clear()
        return redirect('/login')

    if request.method == 'POST':
        name = request.form.get('name')
        surname = request.form.get('surname')
        phone = request.form.get('phone')
        grade = request.form.get('grade')

        profile_file = request.files.get('profile_image')

        image_path = student['profile_image']  # keep old one if no new upload

        # If user uploaded NEW IMAGE
        if profile_file and allowed_file(profile_file.filename):
            filename = secure_filename(profile_file.filename)
            save_path = os.path.join("static/uploads", filename)
            profile_file.save(save_path)

            image_path = f"/static/uploads/{filename}"  # store as URL path

        # Update student info
        cur.execute("""
            UPDATE Student
            SET name = %s,
                surname = %s,
                phone = %s,
                grade = %s,
                profile_image = %s
            WHERE student_id = %s
        """, (name, surname, phone, grade, image_path, student_id))

        conn.commit()
        cur.close()
        conn.close()

        # Update session values
        session['user_name'] = f"{name} {surname}"
        session['grade'] = grade

        return redirect('/student/dashboard')

    cur.close()
    conn.close()

    return render_template("student_profile.html", student=student)


@app.route("/student/classes")
def student_classes():
    if 'user_role' not in session or session['user_role'] != 'student':
        return redirect('/login')

    student_id = session['user_id']
    grade = session.get('grade')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT C.class_id, C.title, C.topic, C.type, C.start_time,
                   C.duration, C.upload_date, C.link,
                   M.name AS mentor_name, M.surname AS mentor_surname
            FROM Class C
            LEFT JOIN Mentor M ON C.mentor_id = M.mentor_id
            WHERE C.grade = %s
            ORDER BY C.upload_date DESC
        """, (grade,))
        classes = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template("student_classes.html", classes=classes)


@app.route("/student/courses/<string:subject>/contents")
def student_course_contents(subject):
    # Ensure student is logged in
    if 'user_role' not in session or session['user_role'] != 'student' or 'user_id' not in session:
        return redirect('/login')

    student_id = session['user_id']

    conn = get_db_connection()
    if not conn:
        return "❌ Failed to connect to database", 500

    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get student's grade
        cur.execute("""
            SELECT grade
            FROM Student
            WHERE student_id = %s AND status='active'
            LIMIT 1
        """, (student_id,))
        grade_result = cur.fetchone()
        if not grade_result:
            return "❌ Student not found or inactive", 404

        grade = grade_result['grade']

        # Get all content for this subject and grade
        cur.execute("""
            SELECT C.content_id, C.title, C.description, C.type,
                   C.file_url, C.file_name, C.file_size_mb, C.upload_date,
                   M.name AS mentor_name, M.surname AS mentor_surname
            FROM Content C
            LEFT JOIN Mentor M ON C.mentor_id = M.mentor_id
            WHERE C.subject = %s AND C.grade = %s
            ORDER BY C.upload_date DESC
        """, (subject, grade))
        contents = cur.fetchall()

        # Get multiple video links for each content
        content_links = {}
        for content in contents:
            cur.execute("""
                SELECT file_link, upload_date 
                FROM ContentRecord 
                WHERE content_id = %s
                ORDER BY upload_date DESC
            """, (content['content_id'],))
            content_links[content['content_id']] = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    return render_template(
        "course_contents.html",
        subject=subject,
        grade=grade,
        contents=contents,
        content_links=content_links
    )


@app.route("/student/dashboard/courses")
def student_courses():
    # 1️⃣ Ensure student is logged in
    if 'user_role' not in session or session['user_role'] != 'student':
        return redirect('/login')

    student_id = session['user_id']
    grade = session.get('grade')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get student info for sidebar
        cur.execute("""
            SELECT name, surname, grade
            FROM Student
            WHERE student_id = %s
        """, (student_id,))
        student = cur.fetchone()

        # 2️⃣ Check enrollment
        cur.execute("""
            SELECT days_remaining 
            FROM Enrollment
            WHERE student_id = %s AND status = 'active'
            ORDER BY enrollment_id DESC
            LIMIT 1
        """, (student_id,))
        enrollment = cur.fetchone()

        if not enrollment or enrollment['days_remaining'] <= 0:
            return redirect('/student/payment?expired=1')

        # 3️⃣ Get distinct subjects for the student's grade
        cur.execute("""
            SELECT DISTINCT subject
            FROM Content
            WHERE grade = %s
            ORDER BY subject
        """, (grade,))
        subjects = cur.fetchall()

    except Exception as e:
        print(f"Error fetching courses: {e}")
        subjects = []
        student = None
        enrollment = None
    finally:
        cur.close()
        conn.close()

    # Calculate days_remaining
    days_remaining = enrollment['days_remaining'] if enrollment else 0

    return render_template(
        "student_courses.html", 
        subjects=subjects, 
        grade=grade,
        student=student,  # Add student object
        days_remaining=days_remaining  # Add days_remaining
    )

@app.route("/student/request", methods=['GET', 'POST'])
def student_request():
    # 1️⃣ Ensure student is logged in
    if 'user_role' not in session or session['user_role'] != 'student' or 'user_id' not in session:
        return redirect('/login')

    student_id = session['user_id']  # use consistent session key

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 2️⃣ Fetch all active mentors for dropdown
        cur.execute("""
            SELECT mentor_id, name, surname 
            FROM Mentor 
            WHERE status='active' 
            ORDER BY name
        """)
        mentors = cur.fetchall()

        if request.method == 'POST':
            mentor_id = request.form.get('mentor_id')
            topic = request.form.get('topic')
            message = request.form.get('message')
            request_type = request.form.get('request_type')
            pdf_file_url = None

            # 3️⃣ Handle PDF upload
            if 'pdf' in request.files:
                file = request.files['pdf']
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    pdf_file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(pdf_file_path)
                    pdf_file_url = f"uploads/{filename}"  # store relative path in DB

            # 4️⃣ Insert request into DB
            cur.execute("""
                INSERT INTO Request (student_id, mentor_id, topic, message, request_type, pdf_url)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (student_id, mentor_id, topic, message, request_type, pdf_file_url))
            conn.commit()

            flash("Request sent successfully!", "success")
            return render_template("student_dashboard.html", mentors=mentors, success=True)

    except Exception as e:
        print(f"Error sending request: {e}")
        flash("Failed to send request. Please try again.", "error")

    finally:
        cur.close()
        conn.close()

    # 5️⃣ Render the form if GET or POST fails
    return render_template("student_request.html", mentors=mentors)

@app.route("/student/enrollment")
def student_enrollment():
    if 'user_role' not in session or session['user_role'] != 'student' or 'user_id' not in session:
        return redirect('/login')

    student_id = session['user_id']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get enrollment info with student details
        cur.execute("""
            SELECT e.enrollment_id, e.days_remaining, e.status, e.last_updated AS enrollment_date,
                   s.name, s.surname, s.grade
            FROM Enrollment e
            JOIN Student s ON e.student_id = s.student_id
            WHERE e.student_id = %s
            ORDER BY e.enrollment_id DESC
            LIMIT 1
        """, (student_id,))
        enrollment = cur.fetchone()

    finally:
        cur.close()
        conn.close()

    # ✅ ADD THIS EXPIRATION CHECK
    if not enrollment:
        # No enrollment found - redirect to payment
        return redirect("/student/payment?no_enrollment=1")
    
    if enrollment["status"] != "active" or enrollment["days_remaining"] <= 0:
        # Enrollment expired - redirect to payment
        return redirect("/student/payment?expired=1")

    # Create student object from enrollment data
    student = {
        "name": enrollment["name"],
        "surname": enrollment["surname"],
        "grade": enrollment["grade"]
    }
    
    days_remaining = enrollment["days_remaining"]

    # ✅ Pass all required variables to template
    return render_template(
        "student_enrollment.html",
        student=student,
        enrollments=[enrollment],
        days_remaining=days_remaining,
        payment_info={
            "bank_name": "ABSA\n/ CAPITEC",
            "account_name": "EduBoost / Baloyi",
            "account_number": "4103751120\n/ 1843987021",
            "reference": f"STU-{student_id}"
        }
    )


@app.route("/student/payment")
def student_payment():
    # Ensure student is logged in
    if 'user_role' not in session or session['user_role'] != 'student' or 'user_id' not in session:
        return redirect('/login')
    
    student_id = session['user_id']
    
    # Check why they're redirected here
    expired = request.args.get('expired')
    no_enrollment = request.args.get('no_enrollment')
    
    # Get student info
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("SELECT name, surname, grade FROM Student WHERE student_id = %s", (student_id,))
        student = cur.fetchone()
        
        # Get enrollment status
        cur.execute("""
            SELECT status, days_remaining 
            FROM Enrollment 
            WHERE student_id = %s 
            ORDER BY enrollment_id DESC 
            LIMIT 1
        """, (student_id,))
        enrollment = cur.fetchone()
        
    finally:
        cur.close()
        conn.close()
    
    # Determine message based on why they're here
    if expired == '1':
        message = "Your enrollment has expired. Please renew your subscription to continue accessing content."
        title = "Enrollment Expired"
    elif no_enrollment == '1':
        message = "You don't have an active enrollment. Please subscribe to access content."
        title = "No Active Enrollment"
    else:
        message = "Make a payment to renew or start your enrollment."
        title = "Payment Required"
    
    # Payment information
    payment_info = {
        "bank_name": "ABSA / CAPITEC",
        "account_name": "EduBoost / Baloyi",
        "account_number": "4103751120 / 1843987021",
        "reference": f"STU-{student_id}"
    }
    
    return render_template(
        "student_payment.html",
        student=student,
        title=title,
        message=message,
        payment_info=payment_info
    )


# ===========================================================
#  MENTORS DESHBOARD AND FANTIONALITIES
# ===========================================================
# ------------------------------
# MENTORS DASHBOARD
# ------------------------------

def mentor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # ✅ Ensure user is logged in as mentor
        if 'user_role' not in session or session['user_role'] != 'mentor':
            flash("Please login as a mentor first.", "warning")
            return redirect('/login')  # unified login page
        return f(*args, **kwargs)
    return decorated

@app.route('/employee/dashboard')
def employee_dashboard():
    # ✅ Ensure user is logged in as mentor
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Please login as mentor first.", "warning")
        return redirect('/login')  # unified login page

    mentor_id = session['user_id']  # use 'user_id' set during login

    conn = get_db_connection()
    if not conn:
        return "❌ Failed to connect to database", 500

    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Fetch mentor details
        cur.execute("""
            SELECT name, surname, subject_speciality, bio, profile_image, phone
            FROM Mentor
            WHERE mentor_id = %s AND status='active'
        """, (mentor_id,))
        mentor = cur.fetchone()

        if not mentor:
            return "❌ Mentor not found or inactive", 404
    finally:
        cur.close()
        conn.close()

    # Render template with mentor dictionary
    return render_template('employee_dashboard.html', mentor=mentor)


@app.route('/mentor-login', methods=['GET', 'POST'])
def mentor_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password_input = request.form.get('password')

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT mentor_id, name, surname, email, password, status
            FROM Mentor
            WHERE email = %s AND status = 'active'
        """, (email,))
        mentor = cur.fetchone()

        cur.close()
        conn.close()

        if mentor:
            db_password = mentor[4]  # password column

            # Compare raw password directly (no hashing)
            if db_password == password_input:
                session['mentor_id'] = mentor[0]
                session['mentor_name'] = mentor[1] + " " + mentor[2]
                session['mentor_email'] = mentor[3]
                session['user_role'] = 'mentor'

                return redirect('/employee/dashboard')

        return render_template('employee_login.html', error_message="Invalid email or password")

    return render_template('employee_login.html')


@app.route('/employee/content/upload/pdf', methods=['GET', 'POST'])
@mentor_required
def upload_pdf():
    grade = request.args.get('grade')
    if not grade:
        flash("Select a grade first.", "warning")
        return redirect('/employee/dashboard')

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        subject = request.form['subject']

        file = request.files['pdf_file']

        if not file:
            flash("Please upload a PDF file.", "danger")
            return redirect(request.url)

        pdf_data = file.read()
        file_name = secure_filename(file.filename)
        file_size_mb = round(len(pdf_data) / (1024 * 1024), 2)

        if file_size_mb > 25:
            flash("PDF exceeds 25MB limit.", "danger")
            return redirect(request.url)

        conn = get_db_connection()
        cur = conn.cursor()

        # Save file
        filename = secure_filename(file.filename)
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(pdf_path)

        cur.execute("""
            INSERT INTO Content (mentor_id, title, description, subject, grade, pdf_file, file_name, file_size_mb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING content_id
        """, (session["mentor_id"], title, description, subject, grade, pdf_path, file_name, file_size_mb))

        conn.commit()
        cur.close()
        conn.close()

        flash("✅ PDF uploaded successfully for Grade " + grade, "success")
        return redirect('/employee/dashboard')

    return render_template('upload_pdf.html', grade=grade)


@app.route("/employee/content/upload", methods=["GET", "POST"])
def employee_content_upload():
    # ----------------------------
    # 1️⃣ Ensure logged in as mentor
    # ----------------------------
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Please login as a mentor first.", "warning")
        return redirect("/login")

    mentor_id = session['user_id']  # ✅ unified session key
    grade = request.args.get("grade")

    if not grade:
        flash("Please select a grade first.", "warning")
        return redirect("/employee/dashboard")

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        subject = request.form.get("subject")
        file_url = request.form.get("file_url")  # PDF link
        video_links = request.form.getlist("video_links[]")  # multiple videos

        # Validate required fields
        if not title or not subject:
            flash("Title and Subject are required.", "danger")
            return redirect(request.url)

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # Insert main content record (PDF stored as link)
            cur.execute("""
                INSERT INTO Content (mentor_id, title, description, subject, grade, file_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING content_id
            """, (mentor_id, title, description, subject, grade, file_url))

            content_id = cur.fetchone()[0]
            conn.commit()

            # Insert video links if provided
            for link in video_links:
                if link.strip() != "":
                    cur.execute("""
                        INSERT INTO ContentRecord (content_id, file_link)
                        VALUES (%s, %s)
                    """, (content_id, link))
            conn.commit()

            flash(f"✅ Content uploaded successfully for Grade {grade}", "success")
            return redirect("/employee/content/uploaded")

        except Exception as e:
            conn.rollback()
            flash(f"Failed to upload content: {e}", "danger")
            print(f"Error uploading content: {e}")

        finally:
            cur.close()
            conn.close()

    return render_template("upload_content.html", grade=grade)


@app.route("/employee/manage-contents")
def employee_manage_contents():
    # Ensure logged in as mentor
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Please login as a mentor first.", "warning")
        return redirect("/login")

    mentor_id = session['user_id']  # Unified session key

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get all content uploaded by this mentor
    cur.execute("""
        SELECT C.content_id, C.title, C.subject, C.grade, C.file_url, C.upload_date
        FROM Content C
        WHERE C.mentor_id = %s
        ORDER BY C.upload_date DESC
    """, (mentor_id,))
    contents = cur.fetchall()

    # Get multiple resource/video links for each content
    content_links = {}
    for c in contents:
        cur.execute("""
            SELECT file_link 
            FROM ContentRecord 
            WHERE content_id = %s
        """, (c['content_id'],))
        content_links[c['content_id']] = [row['file_link'] for row in cur.fetchall()]

    cur.close()
    conn.close()

    return render_template(
        "manage_contents.html",
        contents=contents,
        content_links=content_links
    )


@app.route("/employee/manage-contents/delete/<int:content_id>", methods=["POST"])
def delete_content(content_id):
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Unauthorized", "danger")
        return redirect("/login")

    conn = get_db_connection()
    cur = conn.cursor()

    # Delete associated extra links first
    cur.execute("DELETE FROM ContentRecord WHERE content_id = %s", (content_id,))
    # Delete main content
    cur.execute("DELETE FROM Content WHERE content_id = %s", (content_id,))
    
    conn.commit()
    cur.close()
    conn.close()

    flash("Content deleted successfully.", "success")
    return redirect("/employee/manage-contents")


@app.route("/employee/requests")
def employee_requests():
    # Check if user is logged in as mentor or admin
    if 'user_role' not in session or session.get('user_role') not in ['mentor', 'admin'] or 'user_id' not in session:
        flash("Please login first.", "warning")
        return redirect("/login")  # unified login page

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT R.request_id, R.topic, R.message, R.request_type, R.status, R.created_at, R.pdf_url,
                   S.name AS student_name, S.surname AS student_surname, S.phone AS student_phone, S.email AS student_email
            FROM Request R
            LEFT JOIN Student S ON R.student_id = S.student_id
            ORDER BY R.created_at DESC
        """)
        requests = cur.fetchall()
    except Exception as e:
        print(f"Error fetching requests: {e}")
        flash("Failed to load requests.", "danger")
        requests = []
    finally:
        cur.close()
        conn.close()

    return render_template("employee_requests.html", requests=requests)


@app.route("/update-request-status/<int:request_id>", methods=["POST"])
def update_request_status(request_id):
    # Check if user is logged in as mentor or admin
    if 'user_role' not in session or session.get('user_role') not in ['mentor', 'admin']:
        return jsonify({'error': 'Unauthorized', 'success': False}), 401
    
    try:
        # Parse JSON data
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided', 'success': False}), 400
            
        new_status = data.get('status')
        
        if not new_status:
            return jsonify({'error': 'Status is required', 'success': False}), 400
            
        if new_status not in ['pending', 'in-progress', 'completed']:
            return jsonify({'error': 'Invalid status', 'success': False}), 400
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            # Check if request exists
            cur.execute("""
                SELECT request_id FROM Request WHERE request_id = %s
            """, (request_id,))
            
            if cur.fetchone() is None:
                return jsonify({'error': 'Request not found', 'success': False}), 404
            
            # Update the request status (updated_at will be auto-updated by trigger)
            cur.execute("""
                UPDATE Request 
                SET status = %s 
                WHERE request_id = %s
                RETURNING request_id, status, updated_at
            """, (new_status, request_id))
            
            updated_request = cur.fetchone()
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': 'Status updated successfully',
                'request_id': updated_request[0],
                'status': updated_request[1],
                'updated_at': updated_request[2].isoformat() if updated_request[2] else None
            })
            
        except Exception as e:
            conn.rollback()
            print(f"Database error updating request status: {e}")
            return jsonify({'error': 'Database error', 'success': False}), 500
        finally:
            cur.close()
            conn.close()
            
    except Exception as e:
        print(f"Error in update_request_status: {e}")
        return jsonify({'error': 'Server error', 'success': False}), 500


@app.route("/debug-requests")
def debug_requests():
    # Check if user is logged in as mentor or admin
    if 'user_role' not in session or session.get('user_role') not in ['mentor', 'admin']:
        return "Unauthorized", 401
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT R.request_id, R.topic, R.status, R.request_type, R.created_at, R.updated_at,
                   S.name AS student_name, S.surname AS student_surname, S.phone AS student_phone
            FROM Request R
            LEFT JOIN Student S ON R.student_id = S.student_id
            ORDER BY R.created_at DESC
            LIMIT 5
        """)
        requests = cur.fetchall()
        
        # Convert to list for better display
        requests_list = []
        for r in requests:
            requests_list.append(dict(r))
            
        return jsonify({
            'count': len(requests_list),
            'requests': requests_list
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/employee/profile/edit", methods=["GET", "POST"])
def employee_profile_edit():
    if 'mentor_id' not in session:
        return redirect('/mentor-login')

    mentor_id = session['mentor_id']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == "POST":
        name = request.form.get("name")
        surname = request.form.get("surname")
        phone = request.form.get("phone")
        subject_speciality = request.form.get("subject_speciality")
        bio = request.form.get("bio")

        cur.execute("""
            UPDATE Mentor
            SET name = %s, surname = %s, phone = %s, subject_speciality = %s, bio = %s
            WHERE mentor_id = %s
        """, (name, surname, phone, subject_speciality, bio, mentor_id))
        conn.commit()

        cur.close()
        conn.close()
        return redirect("/employee/dashboard")

    # Load existing data
    cur.execute("SELECT * FROM Mentor WHERE mentor_id = %s", (mentor_id,))
    mentor = cur.fetchone()

    cur.close()
    conn.close()
    return render_template("employee_profile_edit.html", mentor=mentor)

@app.route("/employee/profile/password", methods=["GET", "POST"])
def employee_change_password():
    # Ensure user is logged in as mentor
    if 'user_role' not in session or session['user_role'] != 'mentor' or 'user_id' not in session:
        return redirect("/login")

    mentor_id = session['user_id']
    error = None

    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")

        if not current_password or not new_password:
            error = "Both fields are required."
            return render_template("employee_change_password.html", error=error)

        conn = get_db_connection()
        cur = conn.cursor()

        # Fetch current password from DB
        cur.execute("SELECT password FROM Mentor WHERE mentor_id = %s", (mentor_id,))
        result = cur.fetchone()

        if not result:
            cur.close()
            conn.close()
            error = "Mentor not found."
            return render_template("employee_change_password.html", error=error)

        db_password = result[0]

        # Direct comparison
        if db_password != current_password:
            cur.close()
            conn.close()
            error = "Current password is incorrect."
            return render_template("employee_change_password.html", error=error)

        # Update password
        cur.execute("UPDATE Mentor SET password = %s WHERE mentor_id = %s", (new_password, mentor_id))
        conn.commit()
        cur.close()
        conn.close()

        # Redirect after successful change
        return redirect("/employee/dashboard")

    return render_template("employee_change_password.html", error=error)

@app.route("/employee/content/uploaded")
def upload_success():
    return render_template("employee_content_uploaded.html")

@app.route("/employee/class/new", methods=["GET", "POST"])
def create_new_class():
    # ----------------------------
    # 1️⃣ Ensure user is logged in as mentor
    # ----------------------------
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Please login as a mentor first.", "warning")
        return redirect("/login")

    mentor_id = session['user_id']  # ✅ unified session key

    if request.method == "POST":
        title = request.form.get("title")
        topic = request.form.get("topic")
        class_type = request.form.get("type")
        start_time = request.form.get("start_time")
        duration = request.form.get("duration")
        grade = request.form.get("grade")
        link = request.form.get("link")
        subject = request.form.get("subject", topic)  # Use topic as subject if not provided
        start_date = request.form.get("start_date", datetime.now().date())  # Use current date if not provided

        if not title or not grade:
            flash("Title and Grade are required.", "danger")
            return redirect(request.url)

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO Class (mentor_id, title, topic, type, start_time, duration, grade, link, subject, start_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (mentor_id, title, topic, class_type, start_time, duration, grade, link, subject, start_date))
            conn.commit()
            flash("✅ Class posted successfully!", "success")
            return redirect('/employee/dashboard')

        except Exception as e:
            flash(f"Failed to post class: {e}", "danger")
            print(f"Error creating new class: {e}")

        finally:
            cur.close()
            conn.close()

    return render_template("employee_class_new.html")


@app.route("/employee/classes")
def view_classes():
    # ----------------------------
    # 1️⃣ Ensure user is logged in as mentor
    # ----------------------------
    if 'user_role' not in session or session['user_role'] != 'mentor':
        flash("Please login as a mentor first.", "warning")
        return redirect("/login")

    mentor_id = session['user_id']  # ✅ use unified session key

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT class_id, title, topic, type, start_time, duration, grade, link, upload_date, subject, start_date
            FROM Class
            WHERE mentor_id = %s
            ORDER BY start_date DESC, start_time DESC
        """, (mentor_id,))

        classes = cur.fetchall()

    except Exception as e:
        flash(f"Failed to fetch classes: {e}", "danger")
        print(f"Error fetching mentor classes: {e}")
        classes = []

    finally:
        cur.close()
        conn.close()

    return render_template("employee_classes.html", classes=classes)

@app.route("/mentor/classes/delete/<int:class_id>", methods=["POST", "GET"])
def mentor_delete_class(class_id):

    # ✅ Ensure mentor is logged in
    if 'user_role' not in session or session['user_role'] != 'mentor':
        return redirect('/login')

    mentor_id = session['user_id']

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # ✔ Ensure mentor only deletes THEIR OWN class
        cur.execute("""
            DELETE FROM Class 
            WHERE class_id = %s AND mentor_id = %s
        """, (class_id, mentor_id))

        if cur.rowcount == 0:
            flash("❌ You are not allowed to delete this class.", "danger")
        else:
            flash("✅ Class deleted successfully!", "success")

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash("Error deleting class: " + str(e), "danger")

    finally:
        cur.close()
        conn.close()

    return redirect("/employee/classes")


# ===========================================================
#  ADMIN DESHBOARD AND FANTIONALITIES
# ===========================================================
# ------------------------------
# ADMIN DASHBOARD
# ------------------------------
# ---------------- ADMIN LOGIN -------------------
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password_input = request.form.get('password')

        conn = get_db_connection()
        cur = conn.cursor()

        # Match your table structure
        cur.execute("""
            SELECT admin_id, name, surname, email, password, role 
            FROM Admin WHERE email = %s
        """, (email,))
        admin = cur.fetchone()

        cur.close()
        conn.close()

        if admin:
            db_password = admin[4]  # password column index

            # Direct string comparison (NO hash)
            if db_password == password_input:
                session['admin_id'] = admin[0]
                session['admin_name'] = admin[1]
                session['admin_email'] = admin[3]
                session['user_role'] = admin[5] if admin[5] else "superadmin"
                return redirect('/admin/dashboard')

        # If wrong password or email not found
        return render_template('admin_login.html', error_message="Invalid email or password")

    return render_template('admin_login.html')

# --------------- ADMIN PROTECTOR ---------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        role = session.get('user_role')
        if role not in ['admin', 'superadmin']:
            flash("Please login as admin.", "warning")
            return redirect('/admin-login')
        return f(*args, **kwargs)
    return decorated


# --------------- ADMIN DASHBOARD ---------------
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    stats = {}
    recent_requests = []
    registration_status = 'open'
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Count students
            cur.execute("SELECT COUNT(*) as count FROM Student")
            stats['students'] = cur.fetchone()['count']
            
            # Count mentors
            cur.execute("SELECT COUNT(*) as count FROM Mentor")
            stats['mentors'] = cur.fetchone()['count']
            
            # Count classes - FIXED: Using new columns
            cur.execute("SELECT COUNT(*) as count FROM Class WHERE start_date >= CURRENT_DATE")
            stats['classes'] = cur.fetchone()['count']
            
            # Count active enrollments
            cur.execute("SELECT COUNT(*) as count FROM Enrollment WHERE status = 'active' AND days_remaining > 0")
            stats['active_enrollments'] = cur.fetchone()['count']
            
            # Get recent student requests - Now includes updated_at
            cur.execute("""
                SELECT r.request_id, r.message, r.status, r.created_at, r.updated_at,
                       s.name as student_name, s.surname as student_surname, s.phone as student_phone,
                       m.name as mentor_name
                FROM Request r
                LEFT JOIN Student s ON r.student_id = s.student_id
                LEFT JOIN Mentor m ON r.mentor_id = m.mentor_id
                ORDER BY r.created_at DESC
                LIMIT 5
            """)
            recent_requests = cur.fetchall()
            
            # Get registration status - Using notification_type column
            cur.execute("""
                SELECT message FROM Notification 
                WHERE notification_type = 'registration_status' 
                ORDER BY date_sent DESC LIMIT 1
            """)
            notification = cur.fetchone()
            
            if notification and ('closed' in notification['message'].lower() or 'not open' in notification['message'].lower()):
                registration_status = 'closed'
            
            cur.close()
        except Exception as e:
            print(f"Admin dashboard stats error: {e}")
        finally:
            conn.close()
    
    return render_template(
        'admin_dashboard.html', 
        admin_name=session.get('user_name'),
        stats=stats,
        recent_requests=recent_requests,
        registration_status=registration_status
    )


# ----------------- LOGOUT ----------------------
@app.route('/admin/logout')
def admin_logout():
    for key in ['admin_id', 'admin_name', 'admin_email', 'user_role']:
        session.pop(key, None)
    flash("Logged out successfully.", "info")
    return redirect('/admin-login')


# Example skeleton route for notifications
@app.route('/admin/notifications', methods=['GET', 'POST'])
@admin_required
def admin_notifications():
    if request.method == 'POST':
        title = request.form.get('title')
        message = request.form.get('message')
        # Save to DB and/or queue for sending
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO Notifications (title, message, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP)", (title, message))
        conn.commit()
        cur.close()
        conn.close()
        flash("Notification created.", "success")
        return redirect('/admin/notifications')

    # GET
    return render_template('admin_notifications.html')


# --- Add employee (mentor/staff) form + POST handler ---
@app.route('/admin/mentors/add', methods=['GET', 'POST'])
@admin_required
def admin_add_mentor():
    if request.method == 'POST':
        name = request.form.get('name')
        surname = request.form.get('surname')
        email = request.form.get('email')
        phone = request.form.get('phone')
        subject_speciality = request.form.get('subject_speciality')
        bio = request.form.get('bio')
        password = request.form.get('password') or 'changeme123'
        profile_image = request.form.get('profile_image')  # ← image URL here

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO Mentor (name, surname, email, phone, subject_speciality, password, bio, profile_image, join_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, 'active')
            """, (name, surname, email, phone, subject_speciality, password, bio, profile_image))

            conn.commit()
            flash("Mentor account created successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error creating mentor: {e}", "error")
        finally:
            cur.close()
            conn.close()

        return redirect('/admin/mentors')

    return render_template('admin_add_mentor.html')

# --- View all employees / mentors (example) ---
@app.route('/admin/mentors')
@admin_required
def admin_view_mentors():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT mentor_id, name, surname, email, subject_speciality, status, join_date FROM Mentor ORDER BY join_date DESC")
    mentors = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin_view_mentors.html', mentors=mentors)


@app.route("/admin/toggle-registration", methods=["POST"])
def toggle_registration():
    if 'user_role' not in session or session.get('user_role') != 'admin':
        return jsonify({'error': 'Unauthorized', 'success': False}), 401
    
    data = request.get_json()
    status = data.get('status', 'open')
    message = data.get('message', '')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Insert notification about registration status
        if not message:
            message = f"Registration is currently {status}. Students will {'not ' if status == 'closed' else ''}be able to register for classes."
        
        # Insert notification with notification_type
        cur.execute("""
            INSERT INTO Notification (message, notification_type, date_sent)
            VALUES (%s, 'registration_status', CURRENT_TIMESTAMP)
        """, (message,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Registration has been {status} successfully.',
            'status': status
        })
        
    except Exception as e:
        conn.rollback()
        print(f"Error toggling registration: {e}")
        return jsonify({'error': 'Failed to update registration status', 'success': False}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/admin/mentors/edit/<int:mentor_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_mentor(mentor_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get current mentor
    cur.execute("SELECT * FROM Mentor WHERE mentor_id = %s", (mentor_id,))
    mentor = cur.fetchone()
    if not mentor:
        flash("Mentor not found.", "danger")
        return redirect('/admin/mentors')

    if request.method == 'POST':
        name = request.form.get("name")
        surname = request.form.get("surname")
        email = request.form.get("email")
        phone = request.form.get("phone")
        subject_speciality = request.form.get("subject_speciality")
        bio = request.form.get("bio")
        status = request.form.get("status")

        # Handle profile image upload
        file = request.files.get('profile_image')
        image_path = mentor['profile_image']  # Keep old image

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)

            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            # Store ONLY the file name
            image_path = filename

        # Update record
        cur.execute("""
            UPDATE Mentor
            SET name=%s, surname=%s, email=%s, phone=%s,
                subject_speciality=%s, bio=%s, status=%s, profile_image=%s
            WHERE mentor_id=%s
        """, (name, surname, email, phone, subject_speciality,
              bio, status, image_path, mentor_id))

        conn.commit()
        cur.close()
        conn.close()

        flash("Mentor updated successfully.", "success")
        return redirect('/admin/mentors')

    cur.close()
    conn.close()
    return render_template('admin_edit_mentor.html', mentor=mentor)

# --- Delete mentor ---
@app.route('/admin/mentors/delete/<int:mentor_id>', methods=['GET'])
@admin_required
def admin_delete_mentor(mentor_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM Mentor WHERE mentor_id=%s", (mentor_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Mentor deleted successfully.", "success")
    return redirect('/admin/mentors')


@app.route('/admin/enrollments/add-days', methods=['POST'])
@admin_required
def add_enrollment_days():
    enrollment_id = request.form.get('enrollment_id')
    additional_days = request.form.get('additional_days')

    if not enrollment_id or not additional_days:
        flash("Missing enrollment ID or days.", "error")
        return redirect('/admin/enrollments')

    try:
        additional_days = int(additional_days)
        if additional_days <= 0:
            flash("Days must be positive.", "error")
            return redirect('/admin/enrollments')
    except ValueError:
        flash("Invalid number of days.", "error")
        return redirect('/admin/enrollments')

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Update enrollment days and remaining days
            cur.execute("""
                UPDATE Enrollment
                SET enrollment_days = enrollment_days + %s,
                    days_remaining = days_remaining + %s,
                    last_updated = CURRENT_TIMESTAMP,
                    status = 'active'
                WHERE enrollment_id = %s
            """, (additional_days, additional_days, enrollment_id))
            conn.commit()
            cur.close()
            flash(f"Successfully added {additional_days} days to enrollment.", "success")
        except Exception as e:
            flash(f"Error updating enrollment: {e}", "error")
            print(f"Add enrollment days error: {e}")
        finally:
            conn.close()

    return redirect('/admin/enrollments')


# --- View student enrollments (example) ---
@app.route('/admin/enrollments')
@admin_required
def admin_view_enrollments():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT e.enrollment_id, e.student_id, s.name, s.surname, e.enrollment_days, e.days_remaining, e.status, e.enrollment_date, e.last_updated
        FROM Enrollment e
        LEFT JOIN Student s ON s.student_id = e.student_id
        ORDER BY e.last_updated DESC
    """)
    enrollments = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin_view_enrollments.html', enrollments=enrollments)


@app.route('/admin/students')
@admin_required
def admin_view_students():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT student_id, name, surname, phone, email, grade, status FROM Student ORDER BY name")
    students = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin_view_students.html', students=students)


# ===========================================================
# NEW ADMIN ROUTES FOR MISSING PAGES
# ===========================================================

@app.route("/admin/requests")
def admin_requests():
    # Check if user is logged in as admin
    if 'user_role' not in session or session.get('user_role') != 'admin':
        flash("Please login as administrator.", "warning")
        return redirect("/login")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get all student requests with details - Now includes updated_at
        cur.execute("""
            SELECT r.request_id, r.topic, r.message, r.request_type, r.status, 
                   r.created_at, r.updated_at, r.pdf_url,
                   s.name as student_name, s.surname as student_surname, 
                   s.phone as student_phone, s.email as student_email,
                   m.name as mentor_name, m.surname as mentor_surname,
                   m.phone as mentor_phone, m.email as mentor_email
            FROM Request r
            LEFT JOIN Student s ON r.student_id = s.student_id
            LEFT JOIN Mentor m ON r.mentor_id = m.mentor_id
            ORDER BY r.created_at DESC
        """)
        requests = cur.fetchall()
        
        # Get stats for filters
        cur.execute("SELECT COUNT(*) as total FROM Request")
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) as pending FROM Request WHERE status = 'pending'")
        pending = cur.fetchone()['pending']
        
        cur.execute("SELECT COUNT(*) as completed FROM Request WHERE status = 'completed'")
        completed = cur.fetchone()['completed']
        
        cur.execute("SELECT COUNT(*) as in_progress FROM Request WHERE status = 'in-progress'")
        in_progress = cur.fetchone()['in_progress']
        
        return render_template("admin_requests.html",
                             requests=requests,
                             stats={
                                 'total': total,
                                 'pending': pending,
                                 'completed': completed,
                                 'in_progress': in_progress
                             })
                             
    except Exception as e:
        print(f"Error loading admin requests: {e}")
        flash("Failed to load student requests.", "danger")
        return render_template("admin_requests.html",
                             requests=[],
                             stats={'total': 0, 'pending': 0, 'completed': 0, 'in_progress': 0})
    finally:
        cur.close()
        conn.close()


@app.route("/admin/classes/upcoming")
def admin_upcoming_classes():
    # Check if user is logged in as admin
    if 'user_role' not in session or session.get('user_role') != 'admin':
        flash("Please login as administrator.", "warning")
        return redirect("/login")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get upcoming classes with details - Now includes subject and start_date
        cur.execute("""
            SELECT c.class_id, c.title, c.subject, c.topic, c.grade,
                   c.start_date, c.start_time, c.duration,
                   c.upload_date,
                   m.name as mentor_name, m.surname as mentor_surname,
                   m.email as mentor_email, m.phone as mentor_phone
            FROM Class c
            LEFT JOIN Mentor m ON c.mentor_id = m.mentor_id
            WHERE c.start_date >= CURRENT_DATE OR c.start_date IS NULL
            ORDER BY c.start_date ASC NULLS LAST, c.start_time ASC
        """)
        classes = cur.fetchall()
        
        # Get stats
        cur.execute("""
            SELECT COUNT(*) as total, 
                   COUNT(CASE WHEN start_date >= CURRENT_DATE THEN 1 END) as upcoming
            FROM Class 
        """)
        stats = cur.fetchone()
        stats['active'] = stats['upcoming']
        stats['full'] = 0  # Placeholder since we don't have max_students column
        
        # Get subjects and grades for filters
        cur.execute("SELECT DISTINCT subject FROM Class WHERE subject IS NOT NULL ORDER BY subject")
        subjects = [row['subject'] for row in cur.fetchall()]
        
        cur.execute("SELECT DISTINCT grade FROM Class WHERE grade IS NOT NULL ORDER BY grade")
        grades = [row['grade'] for row in cur.fetchall()]
        
        # Get topics for filters
        cur.execute("SELECT DISTINCT topic FROM Class WHERE topic IS NOT NULL AND topic != '' ORDER BY topic")
        topics = [row['topic'] for row in cur.fetchall()]
        
        return render_template("admin_upcoming_classes.html",
                             classes=classes,
                             stats=stats,
                             subjects=subjects,
                             topics=topics,
                             grades=grades)
                             
    except Exception as e:
        print(f"Error loading upcoming classes: {e}")
        flash("Failed to load upcoming classes.", "danger")
        return render_template("admin_upcoming_classes.html",
                             classes=[],
                             stats={'total': 0, 'full': 0, 'active': 0},
                             subjects=[],
                             topics=[],
                             grades=[])
    finally:
        cur.close()
        conn.close()


# ===========================================================
# REGISTRATION SYSTEM ROUTES
# ===========================================================

@app.route("/check-registration-status")
def check_registration_status():
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get latest registration status - Using notification_type column
        cur.execute("""
            SELECT message FROM Notification 
            WHERE notification_type = 'registration_status' 
            ORDER BY date_sent DESC LIMIT 1
        """)
        notification = cur.fetchone()
        
        if notification and ('closed' in notification[0].lower() or 'not open' in notification[0].lower()):
            return jsonify({
                'status': 'closed',
                'message': notification[0]
            })
        else:
            return jsonify({
                'status': 'open',
                'message': 'Registration is open. You can sign up now.'
            })
            
    except Exception as e:
        print(f"Error checking registration status: {e}")
        return jsonify({'status': 'open', 'message': 'Registration is open.'})
    finally:
        cur.close()
        conn.close()


@app.route("/registration-closed")
def registration_closed():
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get the registration closed message - Using notification_type column
        cur.execute("""
            SELECT message FROM Notification 
            WHERE notification_type = 'registration_status' 
            ORDER BY date_sent DESC LIMIT 1
        """)
        notification = cur.fetchone()
        
        message = "Registration is currently closed. We will open registrations at the beginning of the next term."
        if notification and ('closed' in notification[0].lower() or 'not open' in notification[0].lower()):
            message = notification[0]
            
    except Exception as e:
        print(f"Error fetching registration message: {e}")
        message = "Registration is currently closed. We will open registrations at the beginning of the next term."
    finally:
        cur.close()
        conn.close()
    
    return render_template("registration_closed.html", message=message)


# ===========================================================
# MAIN EXECUTION
# ===========================================================

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    app.run(debug=True, port=5000)