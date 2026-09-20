# ⚡ RevPulse — SaaS Revenue Analytics & Intelligence Platform

> **Production-grade, privacy-first revenue analytics platform built for small SaaS founders.** Connects to Stripe to deliver real-time MRR, day-over-day movement breakdowns (New, Expansion, Contraction, Churn, Reactivation), cohort retention matrices, at-risk invoice monitoring, and an AST-guarded AI natural language assistant.

---

## 🏗️ Architecture Diagram

```mermaid
flowchart TD
    subgraph Clients["Clients & External"]
        Browser["Founder Web Browser<br/>(Tailwind + HTMX + Chart.js)"]
        StripeAPI["Stripe API & Webhooks<br/>(API Version: 2024-06-20)"]
    end

    subgraph AppLayer["Application Layer (Flask 3)"]
        AppFactory["Flask App Factory & Blueprints"]
        AuthBP["Auth & Multi-Tenancy Context"]
        DashBP["Dashboard & Chart Endpoints"]
        CohortsBP["Cohort Retention Matrix"]
        AskBP["AI 'Ask Your Data' Assistant"]
        AlertsBP["Slack & Email Alert Dispatcher"]
        BillingBP["SaaS Subscription Management"]
    end

    subgraph SecurityLayer["Security & Validation Layer"]
        SQLGuard["AST SQL-Guard (sqlglot)<br/>Single SELECT • Whitelist • LIMIT <= 100"]
        CryptoService["AES-128 Fernet Key Encryption"]
    end

    subgraph DBLayer["PostgreSQL 16 Database"]
        MigratorRole[("revpulse_migrator<br/>DDL & Alembic Migrations")]
        AppRole[("revpulse_app (NOBYPASSRLS)<br/>Multi-Tenant Row-Level Security")]
        ReadonlyRole[("revpulse_readonly (3000ms timeout)<br/>analytics.* & Materialized View")]
        
        PartitionedEvents["stripe_events (Monthly Partitioned)"]
        JobsQueue["jobs (SKIP LOCKED Worker Queue)"]
        DailyMRR["mrr_daily (Date-Spine Snapshots)"]
        Movements["mrr_movements (LAG Transition Logs)"]
        CohortMV["cohort_retention_mv (Concurrent Refresh)"]
    end

    subgraph WorkerLayer["Background Daemon"]
        Worker["Python Worker Process<br/>(worker.py - Backfill, Aggregations, Alerts)"]
    end

    Browser -->|HTTP / HTMX| AppFactory
    StripeAPI -->|Webhooks| AppFactory
    AppFactory --> AuthBP & DashBP & CohortsBP & AskBP & AlertsBP & BillingBP
    
    AskBP --> SQLGuard
    SQLGuard -->|Safe SELECT| ReadonlyRole
    DashBP & CohortsBP & AuthBP -->|set_config(app.current_org_id)| AppRole
    
    Worker -->|SELECT ... FOR UPDATE SKIP LOCKED| JobsQueue
    Worker -->|Sync & Aggregate| AppRole
    StripeAPI <-->|Backfill / SDK| Worker
    MigratorRole -->|DDL / Alembic| DBLayer
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Language & Runtime** | Python 3.12+ (tested on Python 3.13) |
| **Web Framework** | Flask 3.x (Application Factory, Modular Blueprints) |
| **Database & ORM** | PostgreSQL 16, SQLAlchemy 2.x, Alembic Migrations, psycopg 3 |
| **Frontend UI** | Server-Rendered Jinja2 + HTMX + Tailwind CSS + Chart.js + Lucide Icons |
| **Authentication** | Flask-Login with Argon2 password hashing (swappable interface for Auth0/Clerk) |
| **Security & Privacy** | PostgreSQL Row-Level Security (RLS), AES-128 Fernet Encryption, AST SQL-Guard (`sqlglot`) |
| **Payments & Billing** | Official `stripe-python` SDK (pinned version: `2024-06-20`), Stripe Webhooks, Checkout & Customer Portal |
| **Background Processing** | PostgreSQL-backed ACID Job Queue using `SELECT ... FOR UPDATE SKIP LOCKED` |

---

## 📐 Advanced PostgreSQL Concept Mapping

1. **Row-Level Security (RLS)**:
   - Tenant isolation is enforced at the database engine level via `current_setting('app.current_org_id', true)::uuid`.
   - The application connection pool uses `revpulse_app` with `NOBYPASSRLS`. Every database transaction is scoped via `SELECT set_config('app.current_org_id', :org_id, true)`.
2. **Monthly Declarative Partitioning**:
   - `stripe_events` is partitioned by `RANGE (created_at)` with monthly sub-tables to absorb massive webhook throughput without table bloat.
3. **Concurrent Materialized Views**:
   - `cohort_retention_mv` precomputes cohort retention matrices (month 0 to 12+) and is refreshed concurrently with zero downtime: `REFRESH MATERIALIZED VIEW CONCURRENTLY cohort_retention_mv;`.
4. **Acid Job Queue via `SKIP LOCKED`**:
   - Eliminates Redis/Celery dependency for small teams. Multi-worker consumers poll jobs concurrently with zero deadlock risk using `SELECT ... FOR UPDATE SKIP LOCKED`.
5. **Least-Privilege AI Role**:
   - Natural language queries run through `revpulse_readonly` restricted to `analytics.*` views with `statement_timeout = '3000ms'`.

---

## 📊 Pure SQL Metrics Engine

RevPulse computes financial metrics using pure SQL date-spines and PostgreSQL window functions:

- **MRR Normalization**:
  $$\text{MRR} = \begin{cases} \text{amount} \times \text{qty} & \text{if monthly} \\ (\text{amount} \times \text{qty}) / 12 & \text{if annual} \\ (\text{amount} \times \text{qty}) / 3 & \text{if quarterly} \\ (\text{amount} \times \text{qty} \times 52) / 12 & \text{if weekly} \end{cases}$$
- **Day-over-Day Movements**:
  Uses `LAG(mrr_cents, 1, 0) OVER (PARTITION BY subscription_id ORDER BY date)` to categorize transitions into:
  - **New**: $0 \to >\$0$ (First-time customer)
  - **Expansion**: $X \to Y$ ($Y > X > 0$)
  - **Contraction**: $X \to Y$ ($0 < Y < X$)
  - **Churn**: $X \to \$0$
  - **Reactivation**: $\$0 \to >\$0$ (Returning past customer)
- **SaaS Unit Economics**:
  - **ARR**: $\text{MRR} \times 12$
  - **ARPA**: $\text{Total MRR} / \text{Active Customers}$
  - **Logo Churn %**: $(\text{Churned Customers} / \text{Starting Customers}) \times 100$
  - **Net Revenue Retention (NRR %)**: $\frac{\text{Start MRR} + \text{Expansion} - \text{Contraction} - \text{Churn}}{\text{Start MRR}} \times 100$
  - **At-Risk Revenue**: Sum of unpaid overdue invoices where `period_end < NOW()` or customer is delinquent.

---

## 🤖 AI "Ask Your Data" AST Security Guard

RevPulse allows founders to query their metrics using plain English without exposing base tables or risking prompt injection / SQL injection:

1. **Natural Language to SQL**: Translates queries into target views (`v_mrr_summary`, `v_plan_performance`, `v_at_risk_revenue`, `v_customer_cohorts`).
2. **AST Parser & Validator (`sqlglot`)**:
   - Rejects multiple statements (prevents stacked query injection like `; DROP TABLE`).
   - Rejects any non-SELECT expressions (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`).
   - Rejects unwhitelisted tables and system catalogs (`information_schema`, `pg_catalog`, `pg_tables`, etc.).
   - Rejects malicious functions (`pg_sleep`, `pg_read_file`, `dblink`, etc.).
   - Forces or caps `LIMIT <= 100`.
3. **Execution**: Executed strictly under unprivileged `revpulse_readonly` role with a 3000ms statement timeout.

---

## 🚀 Getting Started

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.12+

### 2. Start PostgreSQL 16
```bash
docker compose up -d
```

### 3. Setup Virtual Environment
```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Run Database Migrations
```bash
alembic upgrade head
```

### 5. Seed Synthetic 18-Month Demo Data
Populates ~2,000 customers, monthly/annual plans, trials, churn, day-over-day movements, and cohort retention:
```bash
python scripts/seed_demo_data.py
```

### 6. Run Web Application
```bash
python run.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.
Click **"Instant Demo"** or sign up with a new account.

### 7. Run Background Worker (Optional / Production)
```bash
python worker.py
```

---

## 🧪 Running Automated Tests

Run the complete test suite verifying Row-Level Security, exact metrics math, concurrency queue, and AST SQL-Guard:
```bash
pytest -v
```

Expected output:
```
tests/test_metrics.py::test_mrr_exact_calculation_and_movements PASSED   [ 12%]
tests/test_queue.py::test_job_queue_concurrency_and_dead_letter PASSED   [ 25%]
tests/test_rls.py::test_rls_tenant_isolation PASSED                      [ 37%]
tests/test_sql_guard.py::test_sql_guard_valid_queries PASSED             [ 50%]
tests/test_sql_guard.py::test_sql_guard_rejects_stacked_queries PASSED   [ 62%]
tests/test_sql_guard.py::test_sql_guard_rejects_non_select PASSED        [ 75%]
tests/test_sql_guard.py::test_sql_guard_rejects_non_whitelisted_tables PASSED [ 87%]
tests/test_sql_guard.py::test_sql_guard_rejects_system_catalogs_and_functions PASSED [100%]

============================== 8 passed in 5.06s ==============================
```

---

## 🔒 Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Application connection string (`revpulse_app` role) | `postgresql+psycopg://revpulse_app:...@localhost:5432/revpulse` |
| `DATABASE_MIGRATION_URL` | Migration connection string (`revpulse_migrator` role) | `postgresql+psycopg://revpulse_migrator:...@localhost:5432/revpulse` |
| `DATABASE_READONLY_URL` | AI Readonly connection string (`revpulse_readonly` role) | `postgresql+psycopg://revpulse_readonly:...@localhost:5432/revpulse` |
| `SECRET_KEY` | Flask session cryptographic secret | Required |
| `STRIPE_ENCRYPTION_KEY` | 32-byte url-safe base64 key for AES-128 Fernet | Required |
| `STRIPE_SECRET_KEY` | Stripe secret key for RevPulse SaaS billing | Optional |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification secret | Optional |
| `GEMINI_API_KEY` | Google Gemini API key for AI assistant | Optional (Rule-based fallback active) |
| `RESEND_API_KEY` | Resend API key for email notifications | Optional (Console log fallback active) |

---

## 📄 License
MIT License. Built with precision for the modern SaaS founder.
