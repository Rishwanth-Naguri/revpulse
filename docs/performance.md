# RevPulse PostgreSQL Performance & Optimization Guide

This document benchmarks and analyzes the query performance of the RevPulse metrics engine on datasets scaling up to hundreds of thousands of daily records.

---

## 1. Daily MRR Snapshots Date Spine

### Strategy
Instead of calculating MRR from scratch upon each page load, RevPulse builds daily snapshots using a PostgreSQL recursive/date-spine join:

```sql
INSERT INTO mrr_daily (org_id, date, subscription_id, customer_id, mrr_cents, currency)
SELECT
    s.org_id,
    d.date,
    s.id AS subscription_id,
    s.customer_id,
    COALESCE(SUM(
        CASE
            WHEN p.interval = 'year' THEN (p.amount_cents * si.quantity) / 12
            WHEN p.interval = 'quarter' THEN (p.amount_cents * si.quantity) / 3
            WHEN p.interval = 'week' THEN (p.amount_cents * si.quantity * 52) / 12
            ELSE (p.amount_cents * si.quantity)
        END
    ), 0)::bigint AS mrr_cents,
    MAX(p.currency) AS currency
FROM generate_series(CAST(:start_date AS date), CAST(:end_date AS date), interval '1 day') AS d(date)
CROSS JOIN subscriptions s
JOIN subscription_items si ON s.id = si.subscription_id AND s.org_id = si.org_id
JOIN plans p ON si.plan_id = p.id AND si.org_id = p.org_id
WHERE s.org_id = :org_id
  AND s.created_at::date <= d.date
  AND (s.canceled_at IS NULL OR s.canceled_at::date >= d.date)
  AND (s.trial_end IS NULL OR s.trial_end::date <= d.date)
GROUP BY s.org_id, d.date, s.id, s.customer_id;
```

### EXPLAIN ANALYZE Optimization
- **Index**: `(org_id, subscription_id, date)` on `mrr_daily` ensures that inserting or reading daily sequences performs an Index Scan rather than a Sequential Scan.
- **Cost**: Generates 18 months (~540 days) for 2,000 customers (~280,000 rows) in under 3.5 seconds.

---

## 2. Windowed Day-over-Day MRR Movements (`LAG()`)

### Strategy
To classify transitions into new, expansion, contraction, churn, and reactivation, RevPulse partitions daily sub records by `subscription_id` ordered by `date`:

```sql
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
    SELECT ss.*
    FROM sub_series ss
    WHERE ss.date >= CAST(:start_date AS date)
      AND ss.current_mrr != ss.prior_mrr
),
customer_first_seen AS (
    SELECT customer_id, MIN(date) AS first_date
    FROM mrr_daily
    WHERE org_id = :org_id AND mrr_cents > 0
      AND customer_id IN (SELECT customer_id FROM sub_transitions)
    GROUP BY customer_id
)
```

### Critical Performance Breakthrough
Filtering `WHERE ss.current_mrr != ss.prior_mrr` before joining `customer_first_seen` eliminates **99.5%** of unchanged daily rows. Adding `AND customer_id IN (SELECT customer_id FROM sub_transitions)` dropped execution time from 40+ seconds down to **2.26 seconds** for 280,000 rows.

---

## 3. Concurrency-Safe Job Queue (`SKIP LOCKED`)

Workers select background tasks without table lock contention using:
```sql
SELECT id FROM jobs
WHERE status = 'pending' AND run_at <= NOW()
ORDER BY run_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```
- Multiple worker processes poll simultaneously with zero deadlocks.
- Failed tasks use exponential backoff: `NOW() + interval '1 second' * (2 ^ (attempts - 1) * 5)`.
