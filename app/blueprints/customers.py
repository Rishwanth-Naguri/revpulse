import uuid
from flask import Blueprint, render_template, request, g, jsonify
from flask_login import login_required
from sqlalchemy import text
from app.database import get_tenant_session
from app.models import Customer, Subscription, Invoice

customers_bp = Blueprint("customers", __name__)

@customers_bp.route("/")
@login_required
def index():
    if not g.org_id:
        return render_template("customers.html", customers=[], total=0, page=1)

    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all")
    page = request.args.get("page", 1, type=int)
    limit = 25
    offset = (page - 1) * limit

    with get_tenant_session(g.org_id) as session:
        query_str = """
        SELECT
            c.id,
            c.name,
            c.email,
            c.delinquent,
            c.created_at,
            s.status AS sub_status,
            p.name AS plan_name,
            COALESCE(
                CASE
                    WHEN p.interval = 'year' THEN (p.amount_cents * si.quantity) / 12
                    ELSE (p.amount_cents * si.quantity)
                END, 0
            ) AS mrr_cents
        FROM customers c
        LEFT JOIN subscriptions s ON c.id = s.customer_id AND s.org_id = c.org_id
        LEFT JOIN subscription_items si ON s.id = si.subscription_id AND s.org_id = si.org_id
        LEFT JOIN plans p ON si.plan_id = p.id AND si.org_id = p.org_id
        WHERE c.org_id = :org_id
        """
        params = {"org_id": str(g.org_id), "limit": limit, "offset": offset}

        if search:
            query_str += " AND (c.name ILIKE :search OR c.email ILIKE :search)"
            params["search"] = f"%{search}%"

        if status_filter != "all":
            query_str += " AND s.status = :status_filter"
            params["status_filter"] = status_filter

        query_str += " ORDER BY c.created_at DESC LIMIT :limit OFFSET :offset"

        rows = session.execute(text(query_str), params).fetchall()

        # Count total
        count_str = "SELECT count(DISTINCT c.id) FROM customers c WHERE c.org_id = :org_id"
        total = session.execute(text(count_str), {"org_id": str(g.org_id)}).scalar() or 0

    customers = [
        {
            "id": r[0],
            "name": r[1] or "Unknown",
            "email": r[2] or "No email",
            "delinquent": r[3],
            "created_at": r[4].strftime("%b %d, %Y") if r[4] else "-",
            "status": r[5] or "none",
            "plan_name": r[6] or "No Plan",
            "mrr": round(r[7] / 100, 2),
        }
        for r in rows
    ]

    if request.headers.get("HX-Request"):
        return render_template("customers/_table.html", customers=customers, total=total, page=page)

    return render_template("customers.html", customers=customers, total=total, page=page, search=search, status=status_filter)


@customers_bp.route("/<uuid:cust_id>")
@login_required
def detail(cust_id: uuid.UUID):
    if not g.org_id:
        return jsonify({"error": "Unauthorized"}), 401

    with get_tenant_session(g.org_id) as session:
        cust = session.query(Customer).filter_by(id=cust_id, org_id=g.org_id).first()
        if not cust:
            return jsonify({"error": "Customer not found"}), 404

        subs = session.query(Subscription).filter_by(customer_id=cust_id, org_id=g.org_id).all()
        invoices = session.query(Invoice).filter_by(customer_id=cust_id, org_id=g.org_id).order_by(Invoice.created_at.desc()).all()

    return render_template("customers/_detail_modal.html", customer=cust, subscriptions=subs, invoices=invoices)
