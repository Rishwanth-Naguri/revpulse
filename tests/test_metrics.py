import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import text
from app.database import get_tenant_session, get_migration_session
from app.models import Organization, Customer, Plan, Subscription, SubscriptionItem
from app.services.mrr import MetricService

def test_mrr_exact_calculation_and_movements():
    """
    Hand-computable 5-customer test suite:
    1. Customer 1: Starter Monthly ($50/mo = 5,000 cents) -> New $50
    2. Customer 2: Pro Annual ($1,200/yr = 120,000 cents / 12 = 10,000 cents MRR) -> New $100
    3. Customer 3: Upgrades from Starter ($50) to Pro ($100) on day 10 -> Expansion +$50
    4. Customer 4: Downgrades from Pro ($100) to Starter ($50) on day 15 -> Contraction -$50
    5. Customer 5: Cancels on day 20 -> Churn -$50
    """
    org_id = uuid.uuid4()

    with get_migration_session() as session:
        org = Organization(id=org_id, name="Metrics Test Org", slug=f"metrics-{org_id.hex[:6]}")
        session.add(org)
        session.commit()

        # Create Plans
        plan_starter_m = Plan(
            id=uuid.uuid4(),
            org_id=org_id,
            stripe_id=f"plan_starter_m_{uuid.uuid4().hex[:4]}",
            name="Starter Monthly",
            amount_cents=5000,
            interval="month",
            interval_count=1,
        )
        plan_pro_m = Plan(
            id=uuid.uuid4(),
            org_id=org_id,
            stripe_id=f"plan_pro_m_{uuid.uuid4().hex[:4]}",
            name="Pro Monthly",
            amount_cents=10000,
            interval="month",
            interval_count=1,
        )
        plan_pro_y = Plan(
            id=uuid.uuid4(),
            org_id=org_id,
            stripe_id=f"plan_pro_y_{uuid.uuid4().hex[:4]}",
            name="Pro Annual",
            amount_cents=120000, # $1,200/yr = $100/mo
            interval="year",
            interval_count=1,
        )
        session.add_all([plan_starter_m, plan_pro_m, plan_pro_y])
        session.commit()

        # 5 Customers
        c1 = Customer(id=uuid.uuid4(), org_id=org_id, stripe_id="cus_1", email="c1@test.com", name="C1")
        c2 = Customer(id=uuid.uuid4(), org_id=org_id, stripe_id="cus_2", email="c2@test.com", name="C2")
        c3 = Customer(id=uuid.uuid4(), org_id=org_id, stripe_id="cus_3", email="c3@test.com", name="C3")
        c4 = Customer(id=uuid.uuid4(), org_id=org_id, stripe_id="cus_4", email="c4@test.com", name="C4")
        c5 = Customer(id=uuid.uuid4(), org_id=org_id, stripe_id="cus_5", email="c5@test.com", name="C5")
        session.add_all([c1, c2, c3, c4, c5])
        session.commit()

        t_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t_end = datetime(2026, 1, 31, tzinfo=timezone.utc)

        # Sub 1: C1 Starter Monthly
        s1 = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_1", customer_id=c1.id, status="active", current_period_start=t_start, current_period_end=t_end)
        si1 = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_1", subscription_id=s1.id, plan_id=plan_starter_m.id, quantity=1)

        # Sub 2: C2 Pro Annual ($1200/yr -> $100/mo normalized)
        s2_id = uuid.uuid4()
        s2 = Subscription(id=s2_id, org_id=org_id, stripe_id="sub_2", customer_id=c2.id, status="active", current_period_start=t_start, current_period_end=datetime(2027, 1, 1, tzinfo=timezone.utc))
        si2 = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_2", subscription_id=s2.id, plan_id=plan_pro_y.id, quantity=1)

        # Sub 3: C3 Upgrades on day 10
        # Day 1-9: Starter ($50)
        s3_a = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_3a", customer_id=c3.id, status="canceled", current_period_start=t_start, current_period_end=datetime(2026, 1, 9, 23, 59, 59, tzinfo=timezone.utc), canceled_at=datetime(2026, 1, 9, 23, 59, 59, tzinfo=timezone.utc))
        si3_a = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_3a", subscription_id=s3_a.id, plan_id=plan_starter_m.id, quantity=1)
        # Day 10-31: Pro ($100)
        s3_b = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_3b", customer_id=c3.id, status="active", current_period_start=datetime(2026, 1, 10, tzinfo=timezone.utc), current_period_end=t_end)
        si3_b = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_3b", subscription_id=s3_b.id, plan_id=plan_pro_m.id, quantity=1)

        # Sub 4: C4 Downgrades on day 15
        # Day 1-14: Pro ($100)
        s4_a = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_4a", customer_id=c4.id, status="canceled", current_period_start=t_start, current_period_end=datetime(2026, 1, 14, 23, 59, 59, tzinfo=timezone.utc), canceled_at=datetime(2026, 1, 14, 23, 59, 59, tzinfo=timezone.utc))
        si4_a = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_4a", subscription_id=s4_a.id, plan_id=plan_pro_m.id, quantity=1)
        # Day 15-31: Starter ($50)
        s4_b = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_4b", customer_id=c4.id, status="active", current_period_start=datetime(2026, 1, 15, tzinfo=timezone.utc), current_period_end=t_end)
        si4_b = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_4b", subscription_id=s4_b.id, plan_id=plan_starter_m.id, quantity=1)

        # Sub 5: C5 Cancels on day 20
        s5 = Subscription(id=uuid.uuid4(), org_id=org_id, stripe_id="sub_5", customer_id=c5.id, status="canceled", current_period_start=t_start, current_period_end=t_end, canceled_at=datetime(2026, 1, 20, 23, 59, 59, tzinfo=timezone.utc))
        si5 = SubscriptionItem(id=uuid.uuid4(), org_id=org_id, stripe_id="si_5", subscription_id=s5.id, plan_id=plan_starter_m.id, quantity=1)

        session.add_all([s1, si1, s2, si2, s3_a, si3_a, s3_b, si3_b, s4_a, si4_a, s4_b, si4_b, s5, si5])
        session.commit()

    # Step 2: Compute daily snapshots for January 2026 under tenant context
    with get_tenant_session(org_id) as session:
        MetricService.compute_daily_mrr_snapshots(
            session=session,
            org_id=org_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        MetricService.compute_mrr_movements(
            session=session,
            org_id=org_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        # 1. Test Day 1 MRR:
        # C1: 5000, C2: 10000 (annual normalized), C3: 5000, C4: 10000, C5: 5000
        # Total Day 1 MRR = 5000 + 10000 + 5000 + 10000 + 5000 = 35,000 cents ($350)
        day1_res = session.execute(
            text("SELECT SUM(mrr_cents) FROM mrr_daily WHERE org_id = :org_id AND date = '2026-01-01'"),
            {"org_id": str(org_id)},
        ).scalar()
        assert day1_res == 35000

        # 2. Test Annual Plan Normalization explicitly
        annual_mrr = session.execute(
            text("SELECT mrr_cents FROM mrr_daily WHERE org_id = :org_id AND date = '2026-01-01' AND subscription_id = :sub_id"),
            {"org_id": str(org_id), "sub_id": str(s2_id)},
        ).scalar()
        assert annual_mrr == 10000 # $1,200 / 12 = $100/mo = 10,000 cents

        # 3. Test End of Month (Jan 31) MRR:
        # C1: 5000
        # C2: 10000
        # C3: 10000 (upgraded)
        # C4: 5000 (downgraded)
        # C5: 0 (canceled on Jan 20)
        # Total Jan 31 MRR = 5000 + 10000 + 10000 + 5000 + 0 = 30,000 cents ($300)
        day31_res = session.execute(
            text("SELECT COALESCE(SUM(mrr_cents), 0) FROM mrr_daily WHERE org_id = :org_id AND date = '2026-01-31'"),
            {"org_id": str(org_id)},
        ).scalar()
        assert day31_res == 30000

        # 4. Test Movements on Day 1 (all are 'new')
        day1_new_mrr = session.execute(
            text("SELECT SUM(amount_cents) FROM mrr_movements WHERE org_id = :org_id AND date = '2026-01-01' AND movement_type = 'new'"),
            {"org_id": str(org_id)},
        ).scalar()
        assert day1_new_mrr == 35000
