from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

class MetricService:
    @staticmethod
    def compute_daily_mrr_snapshots(
        session: Session,
        org_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> int:
        """
        Populate or update mrr_daily for the given date range.
        Uses PostgreSQL generate_series to create a daily date spine,
        joins against active subscriptions in the window, and normalizes
        amounts into integer minor units (cents).
        """
        query = text("""
        WITH date_spine AS (
            SELECT CAST(d AS date) AS date
            FROM generate_series(CAST(:start_date AS timestamp), CAST(:end_date AS timestamp), interval '1 day') d
        ),
        active_sub_days AS (
            SELECT
                s.org_id,
                ds.date,
                s.id AS subscription_id,
                s.customer_id,
                p.currency,
                SUM(
                    CASE
                        WHEN s.trial_end IS NOT NULL AND ds.date <= CAST(s.trial_end AS date) THEN 0
                        WHEN s.canceled_at IS NOT NULL AND ds.date >= CAST(s.canceled_at AS date) THEN 0
                        WHEN p.interval = 'year' THEN (p.amount_cents * si.quantity) / 12
                        WHEN p.interval = 'quarter' THEN (p.amount_cents * si.quantity) / 3
                        WHEN p.interval = 'week' THEN (p.amount_cents * si.quantity * 52) / 12
                        ELSE (p.amount_cents * si.quantity)
                    END
                )::bigint AS mrr_cents
            FROM date_spine ds
            JOIN subscriptions s ON s.org_id = :org_id
                AND ds.date >= CAST(s.current_period_start AS date)
                AND ds.date <= CAST(s.current_period_end AS date)
                AND (s.canceled_at IS NULL OR ds.date <= CAST(s.canceled_at AS date))
            JOIN subscription_items si ON s.id = si.subscription_id AND s.org_id = si.org_id
            JOIN plans p ON si.plan_id = p.id AND si.org_id = p.org_id
            WHERE s.status NOT IN ('incomplete', 'incomplete_expired', 'unpaid')
            GROUP BY s.org_id, ds.date, s.id, s.customer_id, p.currency
        )
        INSERT INTO mrr_daily (org_id, date, subscription_id, customer_id, mrr_cents, currency)
        SELECT org_id, date, subscription_id, customer_id, mrr_cents, currency
        FROM active_sub_days
        ON CONFLICT (org_id, date, subscription_id)
        DO UPDATE SET
            mrr_cents = EXCLUDED.mrr_cents,
            customer_id = EXCLUDED.customer_id,
            currency = EXCLUDED.currency;
        """)

        result = session.execute(
            query,
            {
                "org_id": str(org_id),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return result.rowcount or 0

    @staticmethod
    def compute_mrr_movements(
        session: Session,
        org_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> int:
        """
        Classifies day-over-day MRR transitions into:
        'new', 'expansion', 'contraction', 'churn', 'reactivation'
        using PostgreSQL LAG() window functions over daily sub MRR.
        """
        query = text("""
        WITH sub_series AS (
            SELECT
                md.org_id,
                md.date,
                md.subscription_id,
                md.customer_id,
                md.mrr_cents AS current_mrr,
                LAG(md.mrr_cents, 1, 0::bigint) OVER (
                    PARTITION BY md.subscription_id
                    ORDER BY md.date
                ) AS prior_mrr
            FROM mrr_daily md
            WHERE md.org_id = :org_id
              AND md.date >= (CAST(:start_date AS date) - interval '1 day')
              AND md.date <= CAST(:end_date AS date)
        ),
        sub_transitions AS (
            SELECT
                ss.org_id,
                ss.date,
                ss.subscription_id,
                ss.customer_id,
                ss.prior_mrr,
                ss.current_mrr
            FROM sub_series ss
            WHERE ss.date >= CAST(:start_date AS date)
              AND ss.current_mrr != ss.prior_mrr
        ),
        customer_first_seen AS (
            SELECT
                customer_id,
                MIN(date) AS first_date
            FROM mrr_daily
            WHERE org_id = :org_id AND mrr_cents > 0
              AND customer_id IN (SELECT customer_id FROM sub_transitions)
            GROUP BY customer_id
        ),
        classified AS (
            SELECT
                st.org_id,
                st.date,
                st.subscription_id,
                st.customer_id,
                st.prior_mrr,
                st.current_mrr,
                CASE
                    -- Zero to positive MRR
                    WHEN st.prior_mrr = 0 AND st.current_mrr > 0 THEN
                        CASE
                            WHEN st.date = cfs.first_date THEN 'new'
                            ELSE 'reactivation'
                        END
                    -- Positive to higher positive
                    WHEN st.current_mrr > st.prior_mrr AND st.prior_mrr > 0 THEN 'expansion'
                    -- Positive to lower positive
                    WHEN st.current_mrr < st.prior_mrr AND st.current_mrr > 0 THEN 'contraction'
                    -- Positive to zero
                    WHEN st.prior_mrr > 0 AND st.current_mrr = 0 THEN 'churn'
                    ELSE NULL
                END AS movement_type,
                CASE
                    WHEN st.prior_mrr = 0 AND st.current_mrr > 0 THEN st.current_mrr
                    WHEN st.current_mrr > st.prior_mrr AND st.prior_mrr > 0 THEN st.current_mrr - st.prior_mrr
                    WHEN st.current_mrr < st.prior_mrr AND st.current_mrr > 0 THEN st.prior_mrr - st.current_mrr
                    WHEN st.prior_mrr > 0 AND st.current_mrr = 0 THEN st.prior_mrr
                    ELSE 0
                END AS amount_cents
            FROM sub_transitions st
            LEFT JOIN customer_first_seen cfs ON st.customer_id = cfs.customer_id
        )
        INSERT INTO mrr_movements (id, org_id, date, subscription_id, customer_id, movement_type, amount_cents, prior_mrr_cents, current_mrr_cents, created_at)
        SELECT
            gen_random_uuid(),
            org_id,
            date,
            subscription_id,
            customer_id,
            movement_type,
            amount_cents,
            prior_mrr,
            current_mrr,
            NOW()
        FROM classified
        WHERE movement_type IS NOT NULL AND amount_cents > 0;
        """)

        # Clean existing movements in the target window first for idempotency
        session.execute(
            text("DELETE FROM mrr_movements WHERE org_id = :org_id AND date >= CAST(:start_date AS date) AND date <= CAST(:end_date AS date)"),
            {"org_id": str(org_id), "start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )

        result = session.execute(
            query,
            {
                "org_id": str(org_id),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return result.rowcount or 0

    @staticmethod
    def get_kpis(session: Session, org_id: uuid.UUID, as_of_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Calculates high-level SaaS financial KPIs for the dashboard.
        """
        if not as_of_date:
            as_of_date = date.today()

        month_start = as_of_date.replace(day=1)
        prior_month_start = (month_start - timedelta(days=1)).replace(day=1)

        # 1. Total MRR & Active Subscriptions today
        mrr_res = session.execute(
            text("""
            SELECT
                COALESCE(SUM(mrr_cents), 0) AS total_mrr,
                COUNT(DISTINCT subscription_id) AS active_subs,
                COUNT(DISTINCT customer_id) AS active_customers
            FROM mrr_daily
            WHERE org_id = :org_id AND date = :as_of_date AND mrr_cents > 0
            """),
            {"org_id": str(org_id), "as_of_date": as_of_date.isoformat()},
        ).fetchone()

        total_mrr = int(mrr_res[0]) if mrr_res else 0
        active_subs = int(mrr_res[1]) if mrr_res else 0
        active_customers = int(mrr_res[2]) if mrr_res else 0
        total_arr = total_mrr * 12

        # 2. Starting MRR this month for Net Revenue Retention and Churn rate
        prior_mrr_res = session.execute(
            text("""
            SELECT COALESCE(SUM(mrr_cents), 0), COUNT(DISTINCT customer_id)
            FROM mrr_daily
            WHERE org_id = :org_id AND date = :start_date AND mrr_cents > 0
            """),
            {"org_id": str(org_id), "start_date": month_start.isoformat()},
        ).fetchone()

        start_mrr = int(prior_mrr_res[0]) if prior_mrr_res else 0
        start_customers = int(prior_mrr_res[1]) if prior_mrr_res else 0

        # 3. Monthly Movements (New, Expansion, Contraction, Churn, Reactivation)
        mov_res = session.execute(
            text("""
            SELECT
                COALESCE(SUM(CASE WHEN movement_type = 'new' THEN amount_cents ELSE 0 END), 0) AS new_mrr,
                COALESCE(SUM(CASE WHEN movement_type = 'expansion' THEN amount_cents ELSE 0 END), 0) AS expansion_mrr,
                COALESCE(SUM(CASE WHEN movement_type = 'contraction' THEN amount_cents ELSE 0 END), 0) AS contraction_mrr,
                COALESCE(SUM(CASE WHEN movement_type = 'churn' THEN amount_cents ELSE 0 END), 0) AS churn_mrr,
                COALESCE(SUM(CASE WHEN movement_type = 'reactivation' THEN amount_cents ELSE 0 END), 0) AS reactivation_mrr,
                COUNT(DISTINCT CASE WHEN movement_type = 'churn' THEN customer_id END) AS churned_customers
            FROM mrr_movements
            WHERE org_id = :org_id
              AND date >= :start_date AND date <= :as_of_date
            """),
            {"org_id": str(org_id), "start_date": month_start.isoformat(), "as_of_date": as_of_date.isoformat()},
        ).fetchone()

        new_mrr = int(mov_res[0]) if mov_res else 0
        expansion_mrr = int(mov_res[1]) if mov_res else 0
        contraction_mrr = int(mov_res[2]) if mov_res else 0
        churn_mrr = int(mov_res[3]) if mov_res else 0
        reactivation_mrr = int(mov_res[4]) if mov_res else 0
        churned_customers = int(mov_res[5]) if mov_res else 0

        net_new_mrr = new_mrr + reactivation_mrr + expansion_mrr - contraction_mrr - churn_mrr

        # 4. Derived SaaS Metrics
        arpa = round(total_mrr / active_customers, 2) if active_customers > 0 else 0
        logo_churn_rate = round((churned_customers / start_customers) * 100, 2) if start_customers > 0 else 0.0
        revenue_churn_rate = round(((churn_mrr + contraction_mrr) / start_mrr) * 100, 2) if start_mrr > 0 else 0.0
        nrr = round(((start_mrr + expansion_mrr - contraction_mrr - churn_mrr) / start_mrr) * 100, 2) if start_mrr > 0 else 100.0
        
        monthly_churn_dec = logo_churn_rate / 100.0 if logo_churn_rate > 0 else 0.05
        simple_ltv = round(arpa / monthly_churn_dec, 2) if monthly_churn_dec > 0 else 0

        # 5. At-Risk Revenue
        at_risk_res = session.execute(
            text("""
            SELECT
                COALESCE(SUM(i.amount_due_cents), 0) AS unpaid_invoices_cents,
                COUNT(DISTINCT i.id) AS overdue_invoices_count
            FROM invoices i
            WHERE i.org_id = :org_id
              AND i.status IN ('open', 'uncollectible')
              AND i.period_end < NOW()
            """),
            {"org_id": str(org_id)},
        ).fetchone()

        at_risk_cents = int(at_risk_res[0]) if at_risk_res else 0
        at_risk_count = int(at_risk_res[1]) if at_risk_res else 0

        return {
            "total_mrr_cents": total_mrr,
            "total_arr_cents": total_arr,
            "active_subscriptions": active_subs,
            "active_customers": active_customers,
            "arpa_cents": int(arpa),
            "logo_churn_rate": logo_churn_rate,
            "revenue_churn_rate": revenue_churn_rate,
            "net_revenue_retention": nrr,
            "simple_ltv_cents": int(simple_ltv),
            "net_new_mrr_cents": net_new_mrr,
            "movements": {
                "new_cents": new_mrr,
                "expansion_cents": expansion_mrr,
                "contraction_cents": contraction_mrr,
                "churn_cents": churn_mrr,
                "reactivation_cents": reactivation_mrr,
            },
            "at_risk": {
                "total_cents": at_risk_cents,
                "count": at_risk_count,
            },
        }

    @staticmethod
    def get_mrr_time_series(session: Session, org_id: uuid.UUID, days: int = 30) -> List[Dict[str, Any]]:
        """
        Returns time series of daily MRR and net new movements for charting.
        """
        query = text("""
        SELECT
            d.date,
            d.total_mrr_cents,
            d.new_mrr_cents,
            d.expansion_mrr_cents,
            d.contraction_mrr_cents,
            d.churn_mrr_cents,
            d.reactivation_mrr_cents,
            (d.new_mrr_cents + d.expansion_mrr_cents + d.reactivation_mrr_cents - d.contraction_mrr_cents - d.churn_mrr_cents) AS net_mrr_cents
        FROM analytics.v_mrr_summary d
        WHERE d.org_id = :org_id
          AND d.date >= (CURRENT_DATE - (:days || ' days')::interval)::date
        ORDER BY d.date ASC;
        """)
        rows = session.execute(query, {"org_id": str(org_id), "days": days}).fetchall()
        return [
            {
                "date": row[0].isoformat(),
                "total_mrr": round(row[1] / 100, 2),
                "new_mrr": round(row[2] / 100, 2),
                "expansion_mrr": round(row[3] / 100, 2),
                "contraction_mrr": round(row[4] / 100, 2),
                "churn_mrr": round(row[5] / 100, 2),
                "reactivation_mrr": round(row[6] / 100, 2),
                "net_mrr": round(row[7] / 100, 2),
            }
            for row in rows
        ]

    @staticmethod
    def refresh_cohort_materialized_view(session: Session) -> None:
        """
        Concurrently refreshes cohort_retention_mv using the unique index.
        """
        session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY cohort_retention_mv;"))
