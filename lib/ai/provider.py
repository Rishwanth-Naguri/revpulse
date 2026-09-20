import os
import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RevPulse AI, a PostgreSQL expert for SaaS revenue intelligence.
Given a user's question, write a single PostgreSQL SELECT query targeting ONLY the following whitelisted views in the `analytics` schema:

1. analytics.v_mrr_summary:
   - date (date)
   - total_mrr_cents (bigint)
   - new_mrr_cents (bigint)
   - expansion_mrr_cents (bigint)
   - contraction_mrr_cents (bigint)
   - churn_mrr_cents (bigint)
   - reactivation_mrr_cents (bigint)

2. analytics.v_plan_performance:
   - plan_name (text)
   - interval (text: 'month', 'year', 'quarter', 'week')
   - unit_price_cents (bigint)
   - active_subscribers (bigint)
   - total_mrr_cents (bigint)

3. analytics.v_at_risk_revenue:
   - invoice_id (text)
   - customer_email (text)
   - customer_name (text)
   - amount_due_cents (bigint)
   - status (text: 'open', 'uncollectible')
   - due_date (timestamp)
   - created_at (timestamp)

4. analytics.v_customer_cohorts:
   - cohort_month (date)
   - period_month (int)
   - cohort_size (int)
   - retained_customers (int)
   - retention_rate (numeric)

RULES:
- ONLY output a valid SELECT statement. Do NOT wrap in markdown fences or explanation.
- Target only the 4 views listed above.
- Never use DDL, DML, subqueries to pg_*, or other schemas.
- Convert cents to dollars when presenting output: (amount_cents / 100.0) AS amount_dollars.
- Always include a reasonable ORDER BY and LIMIT <= 50.
"""

class AIProvider:
    @staticmethod
    def generate_sql(question: str) -> str:
        """
        Translates a natural language question into PostgreSQL SELECT syntax.
        Uses Gemini API if configured, otherwise leverages heuristic semantic matcher.
        """
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(
                    f"{SYSTEM_PROMPT}\n\nQuestion: {question}\nSQL Query:"
                )
                raw_sql = response.text.strip()
                # Strip markdown code fences if present
                clean_sql = re.sub(r"^```(?:sql)?\n?", "", raw_sql, flags=re.IGNORECASE)
                clean_sql = re.sub(r"\n?```$", "", clean_sql).strip()
                return clean_sql
            except Exception as e:
                logger.warning("Gemini API call failed, falling back to heuristic parser: %s", str(e))

        # Semantic Rule Matcher Fallback
        q = question.lower()
        if "plan" in q or "tier" in q or "best selling" in q or "most popular" in q:
            return """
            SELECT
                plan_name,
                interval,
                ROUND(unit_price_cents / 100.0, 2) AS price_usd,
                active_subscribers,
                ROUND(total_mrr_cents / 100.0, 2) AS mrr_usd
            FROM analytics.v_plan_performance
            ORDER BY total_mrr_cents DESC
            LIMIT 10;
            """.strip()

        if "at risk" in q or "overdue" in q or "delinquent" in q or "unpaid" in q:
            return """
            SELECT
                customer_name,
                customer_email,
                ROUND(amount_due_cents / 100.0, 2) AS overdue_usd,
                status,
                due_date
            FROM analytics.v_at_risk_revenue
            ORDER BY amount_due_cents DESC
            LIMIT 20;
            """.strip()

        if "cohort" in q or "retention" in q:
            return """
            SELECT
                TO_CHAR(cohort_month, 'Mon YYYY') AS cohort,
                period_month,
                cohort_size,
                retained_customers,
                retention_rate
            FROM analytics.v_customer_cohorts
            WHERE period_month IN (0, 1, 3, 6, 12)
            ORDER BY cohort_month DESC, period_month ASC
            LIMIT 30;
            """.strip()

        if "churn" in q:
            return """
            SELECT
                date,
                ROUND(total_mrr_cents / 100.0, 2) AS mrr_usd,
                ROUND(churn_mrr_cents / 100.0, 2) AS churn_mrr_usd,
                ROUND(contraction_mrr_cents / 100.0, 2) AS contraction_mrr_usd
            FROM analytics.v_mrr_summary
            WHERE churn_mrr_cents > 0 OR contraction_mrr_cents > 0
            ORDER BY date DESC
            LIMIT 30;
            """.strip()

        # Default MRR growth query
        return """
        SELECT
            date,
            ROUND(total_mrr_cents / 100.0, 2) AS mrr_usd,
            ROUND(new_mrr_cents / 100.0, 2) AS new_mrr_usd,
            ROUND(expansion_mrr_cents / 100.0, 2) AS expansion_usd,
            ROUND(churn_mrr_cents / 100.0, 2) AS churn_usd
        FROM analytics.v_mrr_summary
        ORDER BY date DESC
        LIMIT 30;
        """.strip()

    @staticmethod
    def explain_results(question: str, rows: List[Dict[str, Any]]) -> str:
        """
        Produces a concise natural language summary of query results.
        """
        if not rows:
            return "No matching records found for this criteria in the database."

        count = len(rows)
        sample = rows[0]

        if "mrr_usd" in sample:
            latest_mrr = sample.get("mrr_usd")
            return f"Retrieved {count} records. As of the most recent entry ({sample.get('date', 'latest')}), MRR is ${latest_mrr:,.2f}."

        if "overdue_usd" in sample:
            total_overdue = sum(r.get("overdue_usd", 0) for r in rows)
            return f"Found {count} at-risk overdue customer accounts totaling ${total_overdue:,.2f}."

        if "plan_name" in sample:
            top_plan = sample.get("plan_name")
            return f"Across {count} active plans, '{top_plan}' is currently contributing the highest MRR with {sample.get('active_subscribers', 0)} subscribers."

        return f"Successfully retrieved and visualized {count} records from PostgreSQL analytics views."
