from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
from flask_login import login_required
from sqlalchemy import text

from app.database import get_tenant_session
from app.services.mrr import MetricService

metrics_bp = Blueprint("metrics", __name__)

@metrics_bp.route("/kpis")
@login_required
def get_kpis_api():
    if not g.org_id:
        return jsonify({"error": "No tenant organization"}), 400

    today = datetime.now(timezone.utc).date()
    with get_tenant_session(g.org_id) as session:
        data = MetricService.get_kpis(session, g.org_id, as_of_date=today)

    return jsonify(data)


@metrics_bp.route("/mrr")
@login_required
def get_mrr_api():
    if not g.org_id:
        return jsonify({"error": "No tenant organization"}), 400

    days = request.args.get("days", 30, type=int)
    with get_tenant_session(g.org_id) as session:
        data = MetricService.get_mrr_time_series(session, g.org_id, days=days)

    return jsonify({"data": data})


@metrics_bp.route("/plans")
@login_required
def get_plans_api():
    if not g.org_id:
        return jsonify({"error": "No tenant organization"}), 400

    with get_tenant_session(g.org_id) as session:
        query = text("""
        SELECT plan_name, interval, unit_price_cents, active_subscribers, total_mrr_cents
        FROM analytics.v_plan_performance
        WHERE org_id = :org_id
        ORDER BY total_mrr_cents DESC;
        """)
        rows = session.execute(query, {"org_id": str(g.org_id)}).fetchall()

    plans = [
        {
            "plan_name": r[0],
            "interval": r[1],
            "unit_price": round(r[2] / 100, 2),
            "active_subscribers": r[3],
            "total_mrr": round(r[4] / 100, 2),
        }
        for r in rows
    ]
    return jsonify({"plans": plans})


@metrics_bp.route("/at-risk")
@login_required
def get_at_risk_api():
    if not g.org_id:
        return jsonify({"error": "No tenant organization"}), 400

    with get_tenant_session(g.org_id) as session:
        query = text("""
        SELECT invoice_id, customer_email, customer_name, amount_due_cents, status, due_date, created_at
        FROM analytics.v_at_risk_revenue
        WHERE org_id = :org_id
        ORDER BY created_at DESC
        LIMIT 50;
        """)
        rows = session.execute(query, {"org_id": str(g.org_id)}).fetchall()

    items = [
        {
            "invoice_id": r[0],
            "customer_email": r[1],
            "customer_name": r[2],
            "amount_due": round(r[3] / 100, 2),
            "status": r[4],
            "due_date": r[5].isoformat() if r[5] else None,
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]
    return jsonify({"at_risk": items})
