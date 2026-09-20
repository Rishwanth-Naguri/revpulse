import pytest
from lib.ai.sql_guard import SQLGuard, SQLSecurityError

def test_sql_guard_valid_queries():
    # Basic SELECT with analytics view
    sql = "SELECT date, total_mrr_cents FROM analytics.v_mrr_summary WHERE date >= '2024-01-01'"
    clean = SQLGuard.validate_and_sanitize(sql)
    assert "LIMIT 100" in clean
    assert "analytics.v_mrr_summary" in clean

    # Select with existing small limit
    sql2 = "SELECT * FROM analytics.v_plan_performance LIMIT 10"
    clean2 = SQLGuard.validate_and_sanitize(sql2)
    assert "LIMIT 10" in clean2

    # Select with excessive limit should be capped to 100
    sql3 = "SELECT * FROM analytics.v_customer_cohorts LIMIT 5000"
    clean3 = SQLGuard.validate_and_sanitize(sql3)
    assert "LIMIT 100" in clean3


def test_sql_guard_rejects_stacked_queries():
    sql = "SELECT * FROM analytics.v_mrr_summary; DROP TABLE customers;"
    with pytest.raises(SQLSecurityError, match="Multiple SQL statements"):
        SQLGuard.validate_and_sanitize(sql)


def test_sql_guard_rejects_non_select():
    queries = [
        "DELETE FROM customers WHERE id = '123'",
        "UPDATE subscriptions SET status = 'canceled'",
        "INSERT INTO customers (id, name) VALUES ('123', 'Hacker')",
        "DROP TABLE customers",
        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN",
        "CREATE TABLE test (id int)",
        "TRUNCATE TABLE mrr_daily",
    ]
    for q in queries:
        with pytest.raises(SQLSecurityError):
            SQLGuard.validate_and_sanitize(q)


def test_sql_guard_rejects_non_whitelisted_tables():
    # Direct access to base public tables should fail
    unauthorized = [
        "SELECT * FROM customers",
        "SELECT * FROM users",
        "SELECT * FROM stripe_connections",
        "SELECT * FROM subscriptions",
        "SELECT * FROM invoices",
        "SELECT * FROM mrr_daily",
    ]
    for q in unauthorized:
        with pytest.raises(SQLSecurityError, match="Access to table or view"):
            SQLGuard.validate_and_sanitize(q)


def test_sql_guard_rejects_system_catalogs_and_functions():
    dangerous = [
        "SELECT pg_sleep(10)",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM pg_tables",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT version()",
        "SELECT current_user",
    ]
    for q in dangerous:
        with pytest.raises(SQLSecurityError):
            SQLGuard.validate_and_sanitize(q)
