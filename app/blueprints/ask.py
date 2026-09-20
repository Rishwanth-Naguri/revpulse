import uuid
import time
from flask import Blueprint, render_template, request, g, jsonify
from flask_login import login_required
from sqlalchemy import text

from app.database import get_readonly_session
from lib.ai.provider import AIProvider
from lib.ai.sql_guard import SQLGuard, SQLSecurityError

ask_bp = Blueprint("ask", __name__)

@ask_bp.route("/")
@login_required
def index():
    return render_template("ask.html")


@ask_bp.route("/query", methods=["POST"])
@login_required
def query():
    if not g.org_id:
        return render_template("ask/_error.html", error="No organization selected.")

    question = request.form.get("question", "").strip()
    if not question:
        return render_template("ask/_error.html", error="Please enter a question.")

    t0 = time.time()
    try:
        # 1. Translate question to SQL
        raw_sql = AIProvider.generate_sql(question)

        # 2. Strict AST verification and sanitization
        safe_sql = SQLGuard.validate_and_sanitize(raw_sql)

        # 3. Execute with unprivileged readonly role and 3s statement_timeout
        with get_readonly_session(g.org_id) as session:
            cursor = session.execute(text(safe_sql))
            columns = list(cursor.keys())
            raw_rows = cursor.fetchall()

        rows = [dict(zip(columns, r)) for r in raw_rows]
        explanation = AIProvider.explain_results(question, rows)
        duration_ms = round((time.time() - t0) * 1000, 1)

        return render_template(
            "ask/_results.html",
            question=question,
            sql=safe_sql,
            columns=columns,
            rows=rows,
            explanation=explanation,
            duration_ms=duration_ms,
        )

    except SQLSecurityError as sec_err:
        return render_template("ask/_error.html", error=f"Security Guard Blocked Query: {sec_err}")
    except Exception as e:
        return render_template("ask/_error.html", error=f"Execution error: {str(e)}")
