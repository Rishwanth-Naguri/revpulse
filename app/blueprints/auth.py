import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.database import get_migration_session
from app.models import User, Organization, Membership

auth_bp = Blueprint("auth", __name__)
ph = PasswordHasher()

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with get_migration_session() as db_session:
            user = db_session.query(User).filter_by(email=email).first()
            if user and user.password_hash:
                try:
                    ph.verify(user.password_hash, password)
                    login_user(user)
                    flash("Welcome back!", "success")
                    return redirect(url_for("dashboard.index"))
                except VerifyMismatchError:
                    pass

        flash("Invalid email or password", "error")

    return render_template("auth/login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        org_name = request.form.get("org_name", "").strip() or f"{full_name}'s SaaS"

        if not email or not password or not full_name:
            flash("All fields are required.", "error")
            return render_template("auth/signup.html")

        with get_migration_session() as db_session:
            existing = db_session.query(User).filter_by(email=email).first()
            if existing:
                flash("Email already registered. Please login.", "error")
                return redirect(url_for("auth.login"))

            # Create User
            user = User(
                id=uuid.uuid4(),
                email=email,
                full_name=full_name,
                password_hash=ph.hash(password),
            )
            db_session.add(user)
            db_session.flush()

            # Create Organization
            org_slug = org_name.lower().replace(" ", "-") + "-" + uuid.uuid4().hex[:6]
            org = Organization(
                id=uuid.uuid4(),
                name=org_name,
                slug=org_slug,
                plan_tier="free",
            )
            db_session.add(org)
            db_session.flush()

            # Create Membership as Owner
            membership = Membership(
                id=uuid.uuid4(),
                org_id=org.id,
                user_id=user.id,
                role="owner",
            )
            db_session.add(membership)
            db_session.commit()

            login_user(user)
            flash("Account created! Let's connect Stripe or try demo data.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/signup.html")


@auth_bp.route("/demo-login", methods=["GET", "POST"])
def demo_login():
    """
    One-click demo login into the synthetic demo SaaS organization.
    """
    with get_migration_session() as db_session:
        demo_user = db_session.query(User).filter_by(email="demo@revpulse.dev").first()
        if not demo_user:
            # Create on the fly if needed
            demo_user = User(
                id=uuid.uuid4(),
                email="demo@revpulse.dev",
                full_name="Demo Founder",
                password_hash=ph.hash("DemoPassword123!"),
            )
            db_session.add(demo_user)
            db_session.flush()

        login_user(demo_user)
        flash("Logged in to Demo Mode with 18 months of sample SaaS data!", "info")
        return redirect(url_for("dashboard.index"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
