import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from flask_login import login_required, logout_user
from sqlalchemy import text
from app.database import get_migration_session
from app.models import Organization, StripeConnection, Membership, User
from app.services.crypto import CryptoService
from app.services.queue import JobQueue

settings_bp = Blueprint("settings", __name__)

@settings_bp.route("/")
@login_required
def index():
    if not g.org_id:
        return redirect(url_for("dashboard.index"))

    with get_migration_session() as session:
        org = session.get(Organization, g.org_id)
        conn = session.query(StripeConnection).filter_by(org_id=g.org_id).first()
        members = session.query(User, Membership.role).join(Membership, User.id == Membership.user_id).filter(Membership.org_id == g.org_id).all()

    return render_template(
        "settings.html",
        organization=org,
        connection=conn,
        members=members,
    )


@settings_bp.route("/organization", methods=["POST"])
@login_required
def update_organization():
    if not g.org_id or g.org_role not in ("owner", "admin"):
        flash("Unauthorized to modify organization settings.", "error")
        return redirect(url_for("settings.index"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Organization name cannot be empty.", "error")
        return redirect(url_for("settings.index"))

    with get_migration_session() as session:
        org = session.get(Organization, g.org_id)
        if org:
            org.name = name
            session.commit()

    flash("Organization details updated successfully.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/delete-data", methods=["POST"])
@login_required
def delete_all_data():
    """
    GDPR Right to Erasure / Tenant Purge:
    Permanently deletes all customers, subscriptions, movements, and metric snapshots for this organization.
    """
    if not g.org_id or g.org_role != "owner":
        flash("Only the organization owner can perform data erasure.", "error")
        return redirect(url_for("settings.index"))

    confirm_text = request.form.get("confirm_text", "").strip()
    if confirm_text != "DELETE MY DATA":
        flash("Confirmation phrase mismatch. Data was not deleted.", "error")
        return redirect(url_for("settings.index"))

    with get_migration_session() as session:
        org_id_str = str(g.org_id)
        # Delete related data cascades via foreign keys or explicit deletes
        session.execute(text("DELETE FROM mrr_movements WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM mrr_daily WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM invoices WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM subscription_items WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM subscriptions WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM customers WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM stripe_connections WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM alert_logs WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.execute(text("DELETE FROM alert_rules WHERE org_id = :org_id"), {"org_id": org_id_str})
        session.commit()

    flash("All organization data has been permanently deleted.", "info")
    return redirect(url_for("dashboard.index"))
