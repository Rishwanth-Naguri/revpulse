import uuid
from flask import Blueprint, request, redirect, url_for, flash, g, jsonify
from flask_login import login_required
from sqlalchemy import text

from app.database import get_migration_session, get_tenant_session
from app.models import StripeConnection
from app.services.crypto import CryptoService
from app.services.queue import JobQueue

stripe_bp = Blueprint("stripe", __name__)

@stripe_bp.route("/connect", methods=["POST"])
@login_required
def connect():
    if not g.org_id:
        return jsonify({"error": "Unauthorized"}), 401

    api_key = request.form.get("api_key", "").strip()
    if not api_key:
        flash("Stripe API key cannot be empty.", "error")
        return redirect(url_for("settings.index"))

    encrypted_key = CryptoService.encrypt(api_key)

    with get_migration_session() as session:
        conn = session.query(StripeConnection).filter_by(org_id=g.org_id).first()
        if conn:
            conn.encrypted_api_key = encrypted_key
            conn.sync_status = "pending"
        else:
            conn = StripeConnection(
                id=uuid.uuid4(),
                org_id=g.org_id,
                encrypted_api_key=encrypted_key,
                sync_status="pending",
            )
            session.add(conn)
        session.commit()

        # Enqueue backfill job
        JobQueue.enqueue("backfill_sync", {"org_id": str(g.org_id)})

    flash("Stripe account connected! Historical backfill started in background.", "success")
    return redirect(url_for("settings.index"))


@stripe_bp.route("/status")
@login_required
def status():
    if not g.org_id:
        return jsonify({"error": "Unauthorized"}), 401

    with get_migration_session() as session:
        conn = session.query(StripeConnection).filter_by(org_id=g.org_id).first()
        if not conn:
            return jsonify({"connected": False})

        return jsonify({
            "connected": True,
            "status": conn.sync_status,
            "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
            "error": conn.sync_error,
        })


@stripe_bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    if not g.org_id:
        return jsonify({"error": "Unauthorized"}), 401

    with get_migration_session() as session:
        session.execute(
            text("DELETE FROM stripe_connections WHERE org_id = :org_id"),
            {"org_id": str(g.org_id)}
        )
        session.commit()

    flash("Stripe connection disconnected.", "info")
    return redirect(url_for("settings.index"))
