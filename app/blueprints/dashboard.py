from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, g, jsonify
from flask_login import current_user

from app.database import get_tenant_session, get_migration_session
from app.models import Customer, Subscription, StripeConnection
from app.services.mrr import MetricService

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("landing.html")

    org_id = g.org_id
    if not org_id:
        return redirect(url_for("auth.login"))

    # Check if this organization has data
    with get_tenant_session(org_id) as session:
        cust_count = session.query(Customer).count()
        conn = session.query(StripeConnection).filter_by(org_id=org_id).first()

    if cust_count == 0 and not conn:
        return render_template("onboarding.html")

    # Fetch KPIs and Time Series
    today = datetime.now(timezone.utc).date()
    days_param = request.args.get("days", 30, type=int)

    with get_tenant_session(org_id) as session:
        kpis = MetricService.get_kpis(session, org_id, as_of_date=today)
        time_series = MetricService.get_mrr_time_series(session, org_id, days=days_param)

    return render_template(
        "dashboard.html",
        kpis=kpis,
        time_series=time_series,
        days=days_param,
    )


@dashboard_bp.route("/dashboard/chart-data")
def chart_data():
    if not current_user.is_authenticated or not g.org_id:
        return jsonify({"error": "Unauthorized"}), 401

    days_param = request.args.get("days", 30, type=int)
    with get_tenant_session(g.org_id) as session:
        series = MetricService.get_mrr_time_series(session, g.org_id, days=days_param)

    return jsonify({"series": series})
