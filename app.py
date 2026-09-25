from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    session,
    jsonify
)

from flask import flash as flask_flash

from groq import Groq
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from sqlalchemy import inspect
from datetime import datetime, timedelta, date
import os


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "lifeline-secret-key"
)


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///lifeline.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================================================
# GROQ AI
# =========================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None


# Current Groq model
GROQ_MODEL = "openai/gpt-oss-120b"


# =========================================================
# AI SYSTEM PROMPT
# =========================================================

AI_SYSTEM_PROMPT = """
You are LifeLine AI, a friendly and caring AI assistant.

Talk naturally like a helpful human assistant.

Personality:
- Friendly
- Calm
- Warm
- Conversational
- Simple English
- Do not sound robotic
- Do not repeat greetings unnecessarily
- Remember recent conversation context
- Answer follow-up questions naturally
- Use a few relevant emojis when appropriate
- Do not overuse emojis

You can help with:
- General health information
- Basic first aid
- Child, adult and senior care
- Animal care
- Bird care
- Plant care
- Tree care
- General wellness
- Agriculture and basic plant care

Safety:
- Do not diagnose medical conditions.
- Do not replace doctors or veterinarians.
- Do not provide dangerous instructions.
- For serious or emergency situations, recommend professional or emergency help.

Response style:
- Answer directly.
- Keep casual conversations short.
- Use bullet points when useful.
- Use headings only when useful.
- Avoid huge walls of text.
- Continue naturally from the recent conversation.
"""


# =========================================================
# FLASH MESSAGE HELPER
# =========================================================

class flash:

    def success(self, message):
        flask_flash(message, category="success")
        return message

    def error(self, message):
        flask_flash(message, category="error")
        return message

    def warning(self, message):
        flask_flash(message, category="warning")
        return message

    def info(self, message):
        flask_flash(message, category="info")
        return message

    def clear(self):
        session.pop("_flashes", None)
        return True

    def get(self):
        return session.get("_flashes", [])


# =========================================================
# USER MODEL
# =========================================================

class User(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    chats = db.relationship(
        "ChatMessage",
        backref="user",
        lazy=True
    )


# =========================================================
# CHAT MESSAGE MODEL
# =========================================================

class ChatMessage(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        nullable=False
    )

    content = db.Column(
        db.Text,
        nullable=False
    )


# =========================================================
# ROUTINE MODEL
# =========================================================

class Routine(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    title = db.Column(
        db.String(150),
        nullable=False
    )

    category = db.Column(
        db.String(50),
        nullable=False
    )

    routine_date = db.Column(
        db.String(20),
        nullable=False
    )

    routine_time = db.Column(
        db.String(20),
        nullable=False
    )

    repeat = db.Column(
        db.String(30),
        nullable=False,
        default="Once"
    )

    completed = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

# =========================================================
# DATABASE SETUP / MIGRATION
# =========================================================

with app.app_context():

    inspector = inspect(db.engine)

    tables = inspector.get_table_names()

    # -----------------------------------------------------
    # OLD CHAT TABLE COMPATIBILITY
    # -----------------------------------------------------

    if "chat_message" in tables:

        columns = [
            column["name"]
            for column in inspector.get_columns(
                "chat_message"
            )
        ]

        # Old database may not have user_id.
        # Only reset the old chat table.
        # User accounts remain safe.

        if "user_id" not in columns:

            print("Old ChatMessage table detected.")

            print(
                "Resetting only chat_message table..."
            )

            ChatMessage.__table__.drop(
                db.engine,
                checkfirst=True
            )

    # -----------------------------------------------------
    # CREATE MISSING TABLES
    # -----------------------------------------------------

    db.create_all()

    # -----------------------------------------------------
    # ROUTINE COMPLETED COLUMN MIGRATION
    # -----------------------------------------------------

    inspector = inspect(db.engine)

    tables = inspector.get_table_names()

    if "routine" in tables:

        routine_columns = {
            column["name"]
            for column in inspector.get_columns(
                "routine"
            )
        }

        if "completed" not in routine_columns:

            print(
                "Adding completed column to routine table..."
            )

            db.session.execute(
                db.text(
                    """
                    ALTER TABLE routine
                    ADD COLUMN completed
                    BOOLEAN NOT NULL DEFAULT 0
                    """
                )
            )

            db.session.commit()

            print(
                "Routine completed column added."
            )

    print("Database ready.")


# =========================================================
# HELPER - BUILD SAFE RECENT CHAT
# =========================================================

def get_recent_messages(user_id, limit=6):
    """
    Get only a small amount of recent conversation.

    This prevents the Groq request from becoming
    too large when the user has a long chat history.
    """

    recent_messages = (
        ChatMessage.query
        .filter_by(user_id=user_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )

    recent_messages.reverse()

    safe_messages = []

    for message in recent_messages:

        content = message.content or ""

        # Prevent one huge message from consuming
        # too many tokens.
        content = content[:1500]

        safe_messages.append({
            "role": message.role,
            "content": content
        })

    return safe_messages


# =========================================================
# HELPER - ASK GROQ
# =========================================================

def ask_groq(messages):

    if client is None:

        return (
            "LifeLine AI is not connected right now. "
            "Please check your GROQ_API_KEY in the .env file."
        )

    response = client.chat.completions.create(

        model=GROQ_MODEL,

        messages=messages,

        temperature=0.6,

        # Keep the generated response small enough
        # for the Groq token-per-minute limit.
        max_tokens=800
    )

    return response.choices[0].message.content


# =========================================================
# HOME
# =========================================================

@app.route("/", methods=["GET"])
def home():

    logged_in = "user_id" in session

    if logged_in:

        user_id = session["user_id"]

        chat_history = (
            ChatMessage.query
            .filter_by(user_id=user_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )

    else:

        chat_history = []

    return render_template(

        "index.html",

        messages=chat_history,

        logged_in=logged_in,

        user_name=session.get("user_name")
    )


# =========================================================
# GUEST CHAT
# =========================================================

@app.route("/guest-chat", methods=["POST"])
def guest_chat():

    question = request.form.get(
        "question",
        ""
    ).strip()

    if not question:

        return jsonify({
            "success": False,
            "answer": "Please enter a question."
        }), 400

    try:

        ai_messages = [

            {
                "role": "system",
                "content": AI_SYSTEM_PROMPT
            },

            {
                "role": "user",
                "content": question[:1500]
            }
        ]

        print("================================")
        print("GUEST USER QUESTION:")
        print(question)
        print("MODEL:")
        print(GROQ_MODEL)
        print("Sending request to Groq...")
        print("================================")

        answer = ask_groq(ai_messages)

        print("================================")
        print("AI RESPONSE RECEIVED")
        print("================================")

        return jsonify({

            "success": True,

            "answer": answer
        })

    except Exception as e:

        print("")
        print("========================================")
        print("GUEST CHAT ERROR")
        print("========================================")
        print(type(e).__name__)
        print(str(e))
        print("========================================")
        print("")

        return jsonify({

            "success": False,

            "answer": (
                "Sorry 😔 I couldn't process that right now. "
                "Please try again."
            )

        }), 500



    # -----------------------------------------------------
    # USER ROUTINES
    # -----------------------------------------------------

    user_routines = (
        Routine.query
        .filter_by(user_id=user_id)
        .order_by(
            Routine.routine_date.asc(),
            Routine.routine_time.asc()
        )
        .all()
    )

    routine_count = len(
        user_routines
    )

    # -----------------------------------------------------
    # CHAT MESSAGES
    # -----------------------------------------------------

    chat_messages = (
        ChatMessage.query
        .filter_by(user_id=user_id)
        .order_by(ChatMessage.id.desc())
        .all()
    )

    chat_count = len(
        chat_messages
    )

    user_message_count = sum(
        1
        for message in chat_messages
        if message.role == "user"
    )

    assistant_message_count = sum(
        1
        for message in chat_messages
        if message.role == "assistant"
    )

    # -----------------------------------------------------
    # ROUTINE CATEGORY COUNTS
    # -----------------------------------------------------

    category_counts = {}

    for routine in user_routines:

        category = routine.category.strip()

        if category:

            category_counts[category] = (
                category_counts.get(
                    category,
                    0
                ) + 1
            )

    category_counts = dict(
        sorted(
            category_counts.items(),
            key=lambda item: item[1],
            reverse=True
        )
    )

    # -----------------------------------------------------
    # RECENT ROUTINES
    # -----------------------------------------------------

    recent_routines = (
        Routine.query
        .filter_by(user_id=user_id)
        .order_by(Routine.id.desc())
        .limit(5)
        .all()
    )

    # -----------------------------------------------------
    # RECENT MESSAGES
    # -----------------------------------------------------

    recent_messages = chat_messages[:5]

    # -----------------------------------------------------
    # CARE INSIGHT
    # -----------------------------------------------------

    if routine_count == 0 and chat_count == 0:

        care_insight = (
            "Your LifeLine dashboard is ready. "
            "Start by creating a routine or asking "
            "the AI Assistant a care-related question."
        )

    elif routine_count > 0 and chat_count == 0:

        care_insight = (
            f"You have {routine_count} saved "
            f"{'routine' if routine_count == 1 else 'routines'}. "
            "Keep building your care plan and use "
            "the AI Assistant whenever you need guidance."
        )

    elif routine_count == 0 and chat_count > 0:

        care_insight = (
            f"You have {chat_count} saved AI messages. "
            "You can turn your care plans into routines "
            "from the Routines section."
        )

    else:

        care_insight = (
            f"You have {routine_count} saved "
            f"{'routine' if routine_count == 1 else 'routines'} "
            f"and {chat_count} AI messages. "
            "Your LifeLine activity is building up nicely."
        )

    return render_template(
        "advanced-dashboard.html",

        user=user,

        routine_count=routine_count,

        chat_count=chat_count,

        user_message_count=user_message_count,

        assistant_message_count=assistant_message_count,

        routines=user_routines,

        recent_routines=recent_routines,

        category_counts=category_counts,

        recent_messages=recent_messages,

        care_insight=care_insight
    )
# =========================================================
# ROUTINES
# =========================================================

@app.route("/routines")
def routines():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    user_routines = (
        Routine.query
        .filter_by(user_id=user_id)
        .order_by(
            Routine.routine_date.asc(),
            Routine.routine_time.asc()
        )
        .all()
    )

    today = date.today().isoformat()

    today_routines = [
        routine
        for routine in user_routines
        if routine.routine_date == today
    ]

    pending_count = sum(
        1 for routine in user_routines
        if not routine.completed
    )

    completed_count = sum(
        1 for routine in user_routines
        if routine.completed
    )

    today_pending_count = sum(
        1 for routine in today_routines
        if not routine.completed
    )

    today_completed_count = sum(
        1 for routine in today_routines
        if routine.completed
    )

    return render_template(
        "routines.html",
        routines=user_routines,
        today_routines=today_routines,
        pending_count=pending_count,
        completed_count=completed_count,
        today_pending_count=today_pending_count,
        today_completed_count=today_completed_count
    )


@app.route("/add-routine", methods=["POST"])
def add_routine():

    if "user_id" not in session:
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    routine_date = request.form.get("routine_date", "").strip()
    routine_time = request.form.get("routine_time", "").strip()
    repeat = request.form.get("repeat", "Once").strip()

    if not title or not category or not routine_date or not routine_time:
        flask_flash(
            "Please fill in all routine details.",
            category="error"
        )
        return redirect(url_for("routines"))

    new_routine = Routine(
        user_id=session["user_id"],
        title=title,
        category=category,
        routine_date=routine_date,
        routine_time=routine_time,
        repeat=repeat,
        completed=False
    )

    db.session.add(new_routine)
    db.session.commit()

    flask_flash(
        "Routine saved successfully! 🔔",
        category="success"
    )

    return redirect(url_for("routines"))


@app.route("/toggle-routine/<int:routine_id>", methods=["POST"])
def toggle_routine(routine_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    routine = Routine.query.filter_by(
        id=routine_id,
        user_id=session["user_id"]
    ).first_or_404()

    routine.completed = not routine.completed

    db.session.commit()

    return redirect(url_for("routines"))


@app.route("/delete-routine/<int:routine_id>", methods=["POST"])
def delete_routine(routine_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    routine = Routine.query.filter_by(
        id=routine_id,
        user_id=session["user_id"]
    ).first_or_404()

    db.session.delete(routine)
    db.session.commit()

    flask_flash(
        "Routine deleted.",
        category="success"
    )

    return redirect(url_for("routines"))


@app.route("/edit-routine/<int:routine_id>", methods=["POST"])
def edit_routine(routine_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    routine = Routine.query.filter_by(
        id=routine_id,
        user_id=session["user_id"]
    ).first_or_404()

    routine.title = request.form.get(
        "title", routine.title
    ).strip()

    routine.category = request.form.get(
        "category", routine.category
    ).strip()

    routine.routine_date = request.form.get(
        "routine_date", routine.routine_date
    ).strip()

    routine.routine_time = request.form.get(
        "routine_time", routine.routine_time
    ).strip()

    routine.repeat = request.form.get(
        "repeat", routine.repeat
    ).strip()

    db.session.commit()

    flask_flash(
        "Routine updated successfully! ✨",
        category="success"
    )

    return redirect(url_for("routines"))

# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    history_messages = (
        ChatMessage.query
        .filter_by(user_id=user_id)
        .order_by(ChatMessage.id.desc())
        .all()
    )

    return render_template(
        "history.html",
        messages=history_messages
    )
# =========================================================
# LOGGED-IN CHAT
# =========================================================

@app.route("/chat", methods=["GET", "POST"])
def chat():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    user = db.session.get(
        User,
        user_id
    )

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    if request.method == "GET":

        chat_history = (
            ChatMessage.query
            .filter_by(user_id=user_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )

        return render_template(

            "chat.html",

            user=user,

            messages=chat_history
        )

    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

    question = request.form.get(
        "question",
        ""
    ).strip()

    if not question:

        return jsonify({

            "success": False,

            "answer": "Please enter a question."

        }), 400

    try:

        # -------------------------------------------------
        # SAVE USER MESSAGE
        # -------------------------------------------------

        user_message = ChatMessage(

            user_id=user_id,

            role="user",

            content=question
        )

        db.session.add(
            user_message
        )

        db.session.commit()

        # -------------------------------------------------
        # GET ONLY RECENT CHAT HISTORY
        # -------------------------------------------------

        recent_messages = get_recent_messages(
            user_id,
            limit=6
        )

        # -------------------------------------------------
        # BUILD AI MESSAGES
        # -------------------------------------------------

        ai_messages = [

            {
                "role": "system",

                "content": AI_SYSTEM_PROMPT
            }

        ]

        ai_messages.extend(
            recent_messages
        )

        # -------------------------------------------------
        # ASK GROQ
        # -------------------------------------------------

        print("================================")
        print("USER QUESTION:")
        print(question)
        print("MODEL:")
        print(GROQ_MODEL)
        print("RECENT MESSAGES SENT:")
        print(len(recent_messages))
        print("Sending request to Groq...")
        print("================================")

        answer = ask_groq(
            ai_messages
        )

        print("================================")
        print("AI RESPONSE RECEIVED")
        print("================================")

        # -------------------------------------------------
        # SAVE AI MESSAGE
        # -------------------------------------------------

        ai_message = ChatMessage(

            user_id=user_id,

            role="assistant",

            content=answer
        )

        db.session.add(
            ai_message
        )

        db.session.commit()

        # -------------------------------------------------
        # RETURN JSON
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "answer": answer
        })

    except Exception as e:

        print("")
        print("========================================")
        print("LIFELINE CHAT ERROR")
        print("========================================")
        print(type(e).__name__)
        print(str(e))
        print("========================================")
        print("")

        db.session.rollback()

        return jsonify({

            "success": False,

            "answer": (
                "Sorry 😔 I couldn't process that right now. "
                "Please try again."
            ),

            "error": str(e)

        }), 500


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password,
            password
        ):

            session["user_id"] = user.id

            session["user_name"] = user.name

        return redirect(
             url_for("dashboard")
        )
        flask_flash(
            "Invalid email or password.",
            category="error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "login.html"
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user = db.session.get(
        User,
        session["user_id"]
    )

    return render_template(
        "dashboard.html",
        user=user
    )
# =========================================================
# ADVANCED DASHBOARD
# =========================================================

@app.route("/advanced-dashboard")

@app.route("/advanced-dashboard")
def advanced_dashboard():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        session.clear()

        return redirect(
            url_for("login")
        )
    # =========================================================
    # ROUTINE ANALYTICS
    # =========================================================

    user_routines = (
        Routine.query
        .filter_by(user_id=user_id)
        .order_by(
            Routine.routine_date.asc(),
            Routine.routine_time.asc()
        )
        .all()
    )

    routine_count = len(user_routines)

    # Category analytics
    category_counts = {}

    for routine in user_routines:
        category = (routine.category or "Other").strip()

        if category:
            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )

    category_counts = dict(
        sorted(
            category_counts.items(),
            key=lambda item: item[1],
            reverse=True
        )
    )

    # =========================================================
    # WEEKLY ROUTINE ANALYTICS
    # =========================================================

    today = datetime.utcnow().date()

    weekly_counts = {
        "Mon": 0,
        "Tue": 0,
        "Wed": 0,
        "Thu": 0,
        "Fri": 0,
        "Sat": 0,
        "Sun": 0
    }

    for routine in user_routines:
        try:
            routine_date = datetime.strptime(
                routine.routine_date,
                "%Y-%m-%d"
            ).date()

            # Only count routines from the current week
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)

            if week_start <= routine_date <= week_end:
                day_name = routine_date.strftime("%a")

                if day_name in weekly_counts:
                    weekly_counts[day_name] += 1

        except (ValueError, TypeError):
            continue

    # =========================================================
    # CHAT ANALYTICS
    # =========================================================

    chat_messages = (
        ChatMessage.query
        .filter_by(user_id=user_id)
        .order_by(ChatMessage.id.desc())
        .all()
    )

    chat_count = len(chat_messages)

    user_message_count = sum(
        1
        for message in chat_messages
        if message.role == "user"
    )

    assistant_message_count = sum(
        1
        for message in chat_messages
        if message.role == "assistant"
    )

    # =========================================================
    # RECENT DATA
    # =========================================================

    recent_routines = (
        Routine.query
        .filter_by(user_id=user_id)
        .order_by(Routine.id.desc())
        .limit(5)
        .all()
    )

    recent_messages = chat_messages[:5]

    # =========================================================
    # CARE INSIGHT
    # =========================================================

    if routine_count == 0 and chat_count == 0:

        care_insight = (
            "Your LifeLine dashboard is ready. "
            "Start by creating a routine or asking the AI Assistant "
            "a care-related question."
        )

    elif routine_count > 0 and chat_count == 0:

        care_insight = (
            f"You have {routine_count} saved "
            f"{'routine' if routine_count == 1 else 'routines'}. "
            "Keep building your care plan and use the AI Assistant "
            "whenever you need guidance."
        )

    elif routine_count == 0 and chat_count > 0:

        care_insight = (
            f"You have {chat_count} saved AI messages. "
            "You can turn your care plans into routines from the "
            "Routines section."
        )

    else:

        care_insight = (
            f"You have {routine_count} saved "
            f"{'routine' if routine_count == 1 else 'routines'} "
            f"and {chat_count} AI messages. "
            "Your LifeLine activity is building up nicely."
        )

    # =========================================================
    # RENDER ADVANCED DASHBOARD
    # =========================================================

    return render_template(
        "advanced-dashboard.html",
        user=user,

        routine_count=routine_count,
        chat_count=chat_count,

        user_message_count=user_message_count,
        assistant_message_count=assistant_message_count,

        routines=user_routines,
        recent_routines=recent_routines,
        recent_messages=recent_messages,

        category_counts=category_counts,
        weekly_counts=weekly_counts,

        care_insight=care_insight
    )

# =========================================================
# SIGNUP
# =========================================================

@app.route(
    "/signup",
    methods=["GET", "POST"]
)
def signup():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not name or not email or not password:

            flask_flash(
                "Please fill in all fields.",
                category="error"
            )

            return render_template(
                "signup.html"
            )

        # -------------------------------------------------
        # CHECK EXISTING USER
        # -------------------------------------------------

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flask_flash(
                "An account with this email already exists.",
                category="error"
            )

            return render_template(
                "signup.html"
            )

        # -------------------------------------------------
        # HASH PASSWORD
        # -------------------------------------------------

        hashed_password = generate_password_hash(
            password
        )

        # -------------------------------------------------
        # CREATE USER
        # -------------------------------------------------

        new_user = User(

            name=name,

            email=email,

            password=hashed_password
        )

        db.session.add(
            new_user
        )

        db.session.commit()

        flask_flash(
            "Account created successfully. Please login.",
            category="success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "signup.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# AGE MODE
# =========================================================

@app.route("/age-mode")
def age_mode():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template("age_mode.html")


# =========================================================
# CHILD
# =========================================================

@app.route("/child")
def child():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "child.html"
    )


# =========================================================
# ADULT
# =========================================================

@app.route("/adult")
def adult():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "adult.html"
    )


# =========================================================
# SENIOR
# =========================================================

@app.route("/senior")
def senior():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "senior.html"
    )


# =========================================================
# FIRST AID
# =========================================================

@app.route("/firstaid")
def firstaid():

    return render_template(
        "firstaid.html"
    )


# =========================================================
# HEALTH TIPS
# =========================================================

@app.route("/healthtips")
def healthtips():

    return render_template(
        "healthtips.html"
    )


# =========================================================
# HOSPITALS / NEARBY HELP
# =========================================================

@app.route("/hospitals")
def hospitals():

    return render_template(
        "hospitals.html"
    )


# =========================================================
# ABOUT
# =========================================================

@app.route("/about")
def about():

    return render_template(
        "about.html"
    )


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )