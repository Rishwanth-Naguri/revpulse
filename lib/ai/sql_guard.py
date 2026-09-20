import re
from typing import Set
import sqlglot
from sqlglot import exp

WHITELISTED_TABLES: Set[str] = {
    "analytics.v_mrr_summary",
    "v_mrr_summary",
    "analytics.v_customer_cohorts",
    "v_customer_cohorts",
    "analytics.v_plan_performance",
    "v_plan_performance",
    "analytics.v_at_risk_revenue",
    "v_at_risk_revenue",
    "cohort_retention_mv",
}

BLOCKED_IDENTIFIERS: Set[str] = {
    "pg_read_file",
    "pg_write_file",
    "pg_sleep",
    "dblink",
    "version",
    "current_version",
    "current_user",
    "session_user",
    "current_database",
    "information_schema",
    "pg_catalog",
    "pg_tables",
    "pg_shadow",
    "pg_authid",
    "pg_roles",
    "pg_user",
    "pg_settings",
}

class SQLSecurityError(ValueError):
    """Raised when an AI generated SQL query fails security AST inspection."""
    pass

class SQLGuard:
    @staticmethod
    def validate_and_sanitize(sql: str, max_limit: int = 100) -> str:
        """
        Validates that the SQL query is a benign, read-only SELECT against whitelisted views.
        Rejects stacked queries, non-SELECT expressions, blocked tables/functions,
        and caps or appends a LIMIT clause.
        """
        cleaned_sql = sql.strip().rstrip(";")
        if not cleaned_sql:
            raise SQLSecurityError("Empty SQL query")

        try:
            parsed_list = sqlglot.parse(cleaned_sql, read="postgres")
        except Exception as e:
            raise SQLSecurityError(f"SQL Syntax parsing error: {e}")

        if not parsed_list:
            raise SQLSecurityError("No valid SQL statement found")

        # 1. Enforce single statement (reject stacked queries like '; DROP TABLE')
        if len(parsed_list) > 1:
            raise SQLSecurityError("Multiple SQL statements are strictly forbidden")

        root = parsed_list[0]

        # 2. Must be a SELECT expression (or Union of Selects)
        if not isinstance(root, (exp.Select, exp.Union)):
            raise SQLSecurityError(f"Disallowed statement type '{type(root).__name__}'. Only SELECT queries are permitted.")

        # 3. Check for any non-select AST expressions anywhere in the tree
        for node in root.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)):
                raise SQLSecurityError(f"Destructive or mutating clause detected: {type(node).__name__}")

            # Check function and column identifiers for blocked keywords
            if isinstance(node, (exp.Anonymous, exp.Func)):
                func_name = (getattr(node, "name", None) or getattr(node, "key", "")).lower()
                func_sql = node.sql("postgres").lower()
                for blocked in BLOCKED_IDENTIFIERS:
                    if blocked in func_name or blocked in func_sql:
                        raise SQLSecurityError(f"Invocation of sensitive function '{blocked}' is forbidden")

            if isinstance(node, (exp.Identifier, exp.Var)):
                ident_name = (getattr(node, "name", None) or getattr(node, "this", "")).lower()
                if str(ident_name) in BLOCKED_IDENTIFIERS:
                    raise SQLSecurityError(f"Reference to restricted system identifier '{ident_name}' is forbidden")

        # 4. Must select from at least one whitelisted table/view
        tables = list(root.find_all(exp.Table))
        if not tables:
            raise SQLSecurityError("Query must select from a whitelisted analytics view.")

        for t in tables:
            table_name = t.name.lower()
            db_schema = t.db.lower() if t.db else ""
            full_name = f"{db_schema}.{table_name}" if db_schema else table_name

            if full_name not in WHITELISTED_TABLES and table_name not in WHITELISTED_TABLES:
                raise SQLSecurityError(f"Access to table or view '{full_name}' is not permitted. Allowed: {', '.join(sorted(WHITELISTED_TABLES))}")

        # 5. Enforce LIMIT <= max_limit
        if isinstance(root, exp.Select):
            current_limit = None
            limit_exp = root.args.get("limit")
            if limit_exp is not None:
                try:
                    # sqlglot Limit has .expression
                    current_limit = int(limit_exp.expression.this)
                except (ValueError, AttributeError):
                    current_limit = None

            if current_limit is None:
                root = root.limit(max_limit)
            elif current_limit > max_limit or current_limit < 0:
                root.set("limit", None)
                root = root.limit(max_limit)

        return root.sql(dialect="postgres")
