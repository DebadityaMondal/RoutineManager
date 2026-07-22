"""Database models for the school routine generator."""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User model for authentication."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # Relationships
    subjects = db.relationship("Subject", backref="user", lazy=True, cascade="all, delete-orphan")
    teachers = db.relationship("Teacher", backref="user", lazy=True, cascade="all, delete-orphan")
    classes = db.relationship("ClassSection", backref="user", lazy=True, cascade="all, delete-orphan")
    settings = db.relationship("ScheduleSettings", backref="user", uselist=False, cascade="all, delete-orphan")
    routines = db.relationship("GeneratedRoutine", backref="user", lazy=True, cascade="all, delete-orphan")
    class_subject_periods = db.relationship("ClassSubjectPeriod", backref="user", lazy=True, cascade="all, delete-orphan")
    class_teachers = db.relationship("ClassTeacher", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Subject(db.Model):
    """Subject model."""
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_first_period = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint("name", "user_id", name="uq_subject_user"),)


class Teacher(db.Model):
    """Teacher model."""
    __tablename__ = "teachers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Many-to-many with subjects
    teacher_subjects = db.relationship("TeacherSubject", backref="teacher", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("name", "user_id", name="uq_teacher_user"),)

    @property
    def subject_names(self):
        return [ts.subject_name for ts in self.teacher_subjects]


class TeacherSubject(db.Model):
    """Teacher-Subject association."""
    __tablename__ = "teacher_subjects"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)
    subject_name = db.Column(db.String(100), nullable=False)


class ClassSection(db.Model):
    """Class and section model."""
    __tablename__ = "class_sections"

    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(100), nullable=False)
    section = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("class_name", "section", "user_id", name="uq_class_section_user"),)

    @property
    def full_name(self):
        return f"{self.class_name} - {self.section}"


class ScheduleSettings(db.Model):
    """Schedule configuration per user."""
    __tablename__ = "schedule_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    periods_per_day = db.Column(db.Integer, default=6)
    days = db.Column(db.Text, default="Monday,Tuesday,Wednesday,Thursday,Friday,Saturday")
    # JSON string: {"Monday": 7, "Tuesday": 6, ...}
    day_periods_json = db.Column(db.Text, default="{}")
    # JSON string: ["Math", "English"]
    first_period_subjects_json = db.Column(db.Text, default="[]")
    # Class teacher feature toggle
    enable_class_teacher = db.Column(db.Boolean, default=False)
    # Optional: max periods a single teacher can take per day (0 = no limit)
    max_teacher_periods_per_day = db.Column(db.Integer, default=0)
    # Optional: avoid assigning the same teacher to consecutive periods in a class
    avoid_consecutive = db.Column(db.Boolean, default=False)
    # Optional: tiffin break after which period (0 = disabled, default 4)
    tiffin_after_period = db.Column(db.Integer, default=4)

    @property
    def days_list(self):
        return [d.strip() for d in self.days.split(",") if d.strip()]

    @days_list.setter
    def days_list(self, value):
        self.days = ",".join(value)

    @property
    def day_periods(self):
        import json
        try:
            return json.loads(self.day_periods_json or "{}")
        except Exception:
            return {}

    @day_periods.setter
    def day_periods(self, value):
        import json
        self.day_periods_json = json.dumps(value)

    @property
    def first_period_subjects(self):
        import json
        try:
            return json.loads(self.first_period_subjects_json or "[]")
        except Exception:
            return []

    @first_period_subjects.setter
    def first_period_subjects(self, value):
        import json
        self.first_period_subjects_json = json.dumps(value)

    def get_periods_for_day(self, day):
        return self.day_periods.get(day, self.periods_per_day)

    def has_tiffin(self, day):
        if not self.tiffin_after_period or self.tiffin_after_period == 0:
            return False
        return self.get_periods_for_day(day) > self.tiffin_after_period


class GeneratedRoutine(db.Model):
    """Stores the last generated routine for substitute lookup."""
    __tablename__ = "generated_routines"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    # JSON blob storing the full routine
    routine_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    @property
    def routine_data(self):
        import json
        return json.loads(self.routine_json)

    @routine_data.setter
    def routine_data(self, value):
        import json
        self.routine_json = json.dumps(value)


class ClassSubjectPeriod(db.Model):
    """
    Optional: Define how many periods per week a specific class should have
    for each subject. If not set, the generator distributes evenly.
    """
    __tablename__ = "class_subject_periods"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    class_name = db.Column(db.String(100), nullable=False)  # e.g. "Class 6 - A"
    subject_name = db.Column(db.String(100), nullable=False)
    periods_per_week = db.Column(db.Integer, nullable=False, default=4)

    __table_args__ = (db.UniqueConstraint("user_id", "class_name", "subject_name",
                                          name="uq_class_subject_period"),)


class ClassTeacher(db.Model):
    """
    Optional: Assign a class teacher to each class-section.
    When enabled, the class teacher takes the first period every day
    with their assigned subject.
    """
    __tablename__ = "class_teachers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    class_name = db.Column(db.String(100), nullable=False)  # e.g. "Class 6 - A"
    teacher_name = db.Column(db.String(100), nullable=False)
    subject_name = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "class_name",
                                          name="uq_class_teacher"),)
