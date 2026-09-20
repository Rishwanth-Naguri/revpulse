from collections import defaultdict
from flask import Blueprint, render_template, g, jsonify
from flask_login import login_required
from sqlalchemy import text

from app.database import get_tenant_session

cohorts_bp = Blueprint("cohorts", __name__)

@cohorts_bp.route("/")
@login_required
def index():
    if not g.org_id:
        return render_template("cohorts.html", matrix=[], max_period=0)

    with get_tenant_session(g.org_id) as session:
        query = text("""
        SELECT cohort_month, period_month, cohort_size, retained_customers, retention_rate
        FROM analytics.v_customer_cohorts
        WHERE org_id = :org_id
        ORDER BY cohort_month ASC, period_month ASC;
        """)
        rows = session.execute(query, {"org_id": str(g.org_id)}).fetchall()

    cohort_dict = defaultdict(dict)
    cohort_sizes = {}
    max_period = 0

    for r in rows:
        c_month = r[0].strftime("%b %Y")
        period = int(r[1])
        c_size = int(r[2])
        rate = float(r[4])

        cohort_dict[c_month][period] = rate
        cohort_sizes[c_month] = c_size
        if period > max_period:
            max_period = min(period, 12) # Display up to Month 12

    matrix = []
    for c_month, periods in cohort_dict.items():
        row_data = {
            "cohort_month": c_month,
            "cohort_size": cohort_sizes.get(c_month, 0),
            "periods": [periods.get(p) for p in range(max_period + 1)],
        }
        matrix.append(row_data)

    return render_template("cohorts.html", matrix=matrix, max_period=max_period)
