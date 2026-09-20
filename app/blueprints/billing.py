import os
import uuid
import stripe
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from flask_login import login_required
from sqlalchemy import text
from app.database import get_migration_session
from app.models import Organization

billing_bp = Blueprint("billing", __name__)

PRICING_PLANS = [
    {
        "id": "starter",
        "name": "Starter",
        "price": 0,
        "mrr_limit": "$10,000 tracked MRR",
        "features": ["Core MRR & Churn Tracking", "Basic Cohort Matrix", "Email Support"],
        "price_id": None,
    },
    {
        "id": "growth",
        "name": "Growth Pro",
        "price": 49,
        "mrr_limit": "$100,000 tracked MRR",
        "features": ["Full 12-Month Cohorts", "Slack Alerts & Anomaly Triggers", "AI 'Ask Your Data' Assistant", "Daily Backfill Sync"],
        "price_id": os.getenv("STRIPE_GROWTH_PRICE_ID", "price_growth_monthly"),
    },
    {
        "id": "scale",
        "name": "Scale Enterprise",
        "price": 149,
        "mrr_limit": "Unlimited tracked MRR",
        "features": ["Unlimited Team Members", "Custom Webhooks & Audit Logs", "Priority Slack Channel", "Dedicated Data Engineer"],
        "price_id": os.getenv("STRIPE_SCALE_PRICE_ID", "price_scale_monthly"),
    },
]

@billing_bp.route("/")
@login_required
def index():
    if not g.org_id:
        return redirect(url_for("dashboard.index"))

    with get_migration_session() as session:
        org = session.get(Organization, g.org_id)
        current_tier = org.plan_tier if org else "free"

    return render_template(
        "billing.html",
        plans=PRICING_PLANS,
        current_tier=current_tier,
    )


@billing_bp.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    plan_id = request.form.get("plan_id")
    secret_key = os.getenv("STRIPE_SECRET_KEY")

    if not secret_key:
        # Mock mode when running in local dev without live Stripe account
        with get_migration_session() as session:
            org = session.get(Organization, g.org_id)
            if org:
                org.plan_tier = plan_id
                session.commit()
        flash(f"Upgraded to {plan_id.title()} plan (Local Mock Active).", "success")
        return redirect(url_for("billing.index"))

    stripe.api_key = secret_key
    selected_plan = next((p for p in PRICING_PLANS if p["id"] == plan_id), None)
    if not selected_plan or not selected_plan["price_id"]:
        flash("Invalid plan selection.", "error")
        return redirect(url_for("billing.index"))

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": selected_plan["price_id"], "quantity": 1}],
            mode="subscription",
            success_url=url_for("billing.index", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("billing.index", _external=True),
            metadata={"org_id": str(g.org_id)},
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        flash(f"Stripe Checkout error: {str(e)}", "error")
        return redirect(url_for("billing.index"))


@billing_bp.route("/create-portal-session", methods=["POST"])
@login_required
def create_portal_session():
    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        flash("Stripe Customer Portal requires STRIPE_SECRET_KEY.", "info")
        return redirect(url_for("billing.index"))

    # Redirect to customer portal
    stripe.api_key = secret_key
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=g.organization.stripe_customer_id,
            return_url=url_for("billing.index", _external=True),
        )
        return redirect(portal_session.url, code=303)
    except Exception as e:
        flash(f"Portal error: {str(e)}", "error")
        return redirect(url_for("billing.index"))
