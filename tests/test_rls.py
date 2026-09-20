import uuid
import pytest
from sqlalchemy import text
from app.database import get_tenant_session, get_migration_session, app_engine
from app.models import Organization, Customer

def test_rls_tenant_isolation():
    """
    Verify that Row-Level Security strictly isolates tenant data:
    1. Org A only sees Org A rows.
    2. Org B only sees Org B rows.
    3. Unset or empty tenant context returns zero rows (fail-safe).
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    # Step 1: Seed two orgs and a customer in each using migration/admin session
    with get_migration_session() as session:
        org_a = Organization(id=org_a_id, name="Tenant Alpha", slug=f"alpha-{org_a_id.hex[:6]}")
        org_b = Organization(id=org_b_id, name="Tenant Beta", slug=f"beta-{org_b_id.hex[:6]}")
        session.add_all([org_a, org_b])
        session.commit()

        cust_a = Customer(
            id=uuid.uuid4(),
            org_id=org_a_id,
            stripe_id=f"cus_alpha_{uuid.uuid4().hex[:6]}",
            email="alpha@example.com",
            name="Alpha Customer",
        )
        cust_b = Customer(
            id=uuid.uuid4(),
            org_id=org_b_id,
            stripe_id=f"cus_beta_{uuid.uuid4().hex[:6]}",
            email="beta@example.com",
            name="Beta Customer",
        )
        session.add_all([cust_a, cust_b])
        session.commit()

    # Step 2: Query as revpulse_app under Org A context
    with get_tenant_session(org_a_id) as session:
        customers_a = session.query(Customer).all()
        assert len(customers_a) == 1
        assert customers_a[0].org_id == org_a_id
        assert customers_a[0].email == "alpha@example.com"

        # Verify raw SQL query also respects RLS
        raw_res = session.execute(text("SELECT count(*) FROM customers")).scalar()
        assert raw_res == 1

    # Step 3: Query as revpulse_app under Org B context
    with get_tenant_session(org_b_id) as session:
        customers_b = session.query(Customer).all()
        assert len(customers_b) == 1
        assert customers_b[0].org_id == org_b_id
        assert customers_b[0].email == "beta@example.com"

        raw_res = session.execute(text("SELECT count(*) FROM customers")).scalar()
        assert raw_res == 1

    # Step 4: Query with no tenant context set (fail-safe zero rows)
    with get_tenant_session(None) as session:
        customers_empty = session.query(Customer).all()
        assert len(customers_empty) == 0

        raw_res = session.execute(text("SELECT count(*) FROM customers")).scalar()
        assert raw_res == 0
