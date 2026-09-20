import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from flask_login import login_required
from sqlalchemy import text
from app.database import get_migration_session
from app.services.alerts import AlertService

alerts_bp = Blueprint("alerts", __name__)

@alerts_bp.route("/")
@login_required
def index():
    if not g.org_id:
        return redirect(url_for("dashboard.index"))

    with get_migration_session() as session:
        rules = session.execute(
            text("SELECT id, rule_type, threshold_percent, channel, is_enabled, created_at FROM alert_rules WHERE org_id = :org_id ORDER BY created_at DESC"),
            {"org_id": str(g.org_id)}
        ).fetchall()

        logs = session.execute(
            text("SELECT id, title, message, status, triggered_at FROM alerts WHERE org_id = :org_id ORDER BY triggered_at DESC LIMIT 20"),
            {"org_id": str(g.org_id)}
        ).fetchall()

    return render_template("alerts.html", rules=rules, logs=logs)


@alerts_bp.route("/rules", methods=["POST"])
@login_required
def create_rule():
    if not g.org_id:
        return redirect(url_for("dashboard.index"))

    rule_type = request.form.get("rule_type", "churn_spike")
    threshold = int(request.form.get("threshold", 15))
    channel = request.form.get("channel", "slack")

    with get_migration_session() as session:
        session.execute(
            text("""
            INSERT INTO alert_rules (id, org_id, rule_type, threshold_percent, channel, is_enabled, created_at)
            VALUES (gen_random_uuid(), :org_id, :rule_type, :threshold, :channel, true, NOW())
            """),
            {
                "org_id": str(g.org_id),
                "rule_type": rule_type,
                "threshold": threshold,
                "channel": channel,
            }
        )
        session.commit()

    flash("Alert rule successfully created!", "success")
    return redirect(url_for("alerts.index"))


@alerts_bp.route("/test", methods=["POST"])
@login_required
def test_alert():
    channel = request.form.get("channel", "slack")
    destination = request.form.get("destination", "").strip()

    if not destination:
        flash("Destination required for test", "error")
        return redirect(url_for("alerts.index"))

    if channel == "slack":
        success = AlertService.send_slack_notification(
            webhook_url=destination,
            message="🎉 *RevPulse Connection Successful!*\nYour Slack webhook is receiving real-time revenue and churn alerts from RevPulse.",
            title="RevPulse Test Notification"
        )
    else:
        success = AlertService.send_email_notification(
            to_email=destination,
            subject="RevPulse Test Notification",
            body="Your email alerts are connected and active."
        )

    # Log to alerts table
    with get_migration_session() as session:
        session.execute(
            text("""
            INSERT INTO alerts (id, org_id, title, message, status, triggered_at)
            VALUES (gen_random_uuid(), :org_id, :title, :message, :status, NOW())
            """),
            {
                "org_id": str(g.org_id),
                "title": "RevPulse Test Notification",
                "message": f"Test alert dispatched via {channel} to {destination}",
                "status": "sent" if success else "failed",
            }
        )
        session.commit()

    if success:
        flash("Test notification sent successfully!", "success")
    else:
        flash("Failed to deliver test alert. Please verify your URL / email.", "error")

    return redirect(url_for("alerts.index"))
