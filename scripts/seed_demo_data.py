import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from argon2 import PasswordHasher

from app.database import get_migration_session, get_tenant_session
from app.models import (
    Organization,
    User,
    Membership,
    Customer,
    Plan,
    Subscription,
    SubscriptionItem,
    Invoice,
)
from app.services.mrr import MetricService

ph = PasswordHasher()

FIRST_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Sam", "Chris", "Pat", "Casey", "Riley", "Avery", "Jamie", "Logan", "Jesse", "Dakota", "Reese"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez"]
COMPANIES = ["Acme", "CloudScale", "DataFlow", "HyperSync", "Nexus", "PulseMetric", "Vortex", "SaaSify", "ApexLabs", "Starlight", "Synthetix", "OmniTech"]
DOMAINS = ["io", "co", "dev", "app", "tech", "com", "ai"]

def generate_customer_profile(index: int) -> tuple[str, str]:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    company = random.choice(COMPANIES)
    domain = random.choice(DOMAINS)
    name = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}{index}@{company.lower()}.{domain}"
    return name, email

def seed_demo_organization(
    org_id: Optional[uuid.UUID] = None,
    target_customers: int = 2000,
    history_months: int = 18,
) -> uuid.UUID:
    """
    Generates 18 months of realistic synthetic Stripe data for an organization:
    ~2000 customers, monthly and annual plans, trials, upgrades, downgrades, churn, and invoices.
    Calculates mrr_daily, mrr_movements, and refreshes cohort_retention_mv.
    """
    if not org_id:
        org_id = uuid.uuid4()

    print(f"[*] Starting Demo Seed for Organization: {org_id}")
    now = datetime.now(timezone.utc)
    start_history = now - timedelta(days=history_months * 30)

    with get_migration_session() as session:
        # 1. Clean existing demo org if re-seeding
        demo_slug = "demo-pulseflow"
        existing_org = session.query(Organization).filter(Organization.slug.like("demo-pulseflow%")).first()
        if existing_org:
            org_id = existing_org.id
            print(f"[*] Found existing demo org {org_id}, cleaning previous data...")
            session.execute(text("DELETE FROM customers WHERE org_id = :org_id"), {"org_id": str(org_id)})
            session.execute(text("DELETE FROM mrr_daily WHERE org_id = :org_id"), {"org_id": str(org_id)})
            session.execute(text("DELETE FROM mrr_movements WHERE org_id = :org_id"), {"org_id": str(org_id)})
            session.commit()

        # Ensure Organization exists
        org = session.query(Organization).filter_by(id=org_id).first()
        if not org:
            org = Organization(
                id=org_id,
                name="PulseFlow Analytics (Demo)",
                slug=f"demo-pulseflow-{org_id.hex[:6]}",
                plan_tier="pro",
                created_at=start_history,
            )
            session.add(org)

        # 2. Ensure Demo User & Membership exists
        demo_user = session.query(User).filter_by(email="demo@revpulse.dev").first()
        if not demo_user:
            demo_user = User(
                id=uuid.uuid4(),
                email="demo@revpulse.dev",
                password_hash=ph.hash("DemoPassword123!"),
                full_name="Demo Founder",
                created_at=start_history,
            )
            session.add(demo_user)
            session.flush()

        membership = session.query(Membership).filter_by(org_id=org_id, user_id=demo_user.id).first()
        if not membership:
            membership = Membership(
                id=uuid.uuid4(),
                org_id=org_id,
                user_id=demo_user.id,
                role="owner",
                created_at=start_history,
            )
            session.add(membership)

        # 3. Create Plans
        plans_data = [
            ("Starter Monthly", 2900, "month", 1),
            ("Starter Annual", 29000, "year", 1), # $290/yr (~$24/mo)
            ("Growth Monthly", 7900, "month", 1),
            ("Growth Annual", 79000, "year", 1), # $790/yr (~$66/mo)
            ("Scale Monthly", 19900, "month", 1),
            ("Scale Annual", 199000, "year", 1), # $1,990/yr (~$166/mo)
        ]

        created_plans = {}
        for name, amount, interval, interval_count in plans_data:
            stripe_id = f"price_{name.lower().replace(' ', '_')}"
            plan = session.query(Plan).filter_by(org_id=org_id, stripe_id=stripe_id).first()
            if not plan:
                plan = Plan(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    stripe_id=stripe_id,
                    name=name,
                    amount_cents=amount,
                    currency="usd",
                    interval=interval,
                    interval_count=interval_count,
                    created_at=start_history,
                )
                session.add(plan)
                session.flush()
            created_plans[name] = plan

        session.commit()

        # 4. Generate ~2,000 Customers and Subscriptions over 18 months
        print(f"[*] Generating ~{target_customers} customers and subscriptions across {history_months} months...")

        # Month-by-month growth curve (compounding signups)
        # Total months = 18
        # We distribute signups increasingly from month 0 to 18
        customers_to_add: List[Customer] = []
        subs_to_add: List[Subscription] = []
        sub_items_to_add: List[SubscriptionItem] = []
        invoices_to_add: List[Invoice] = []

        cust_counter = 0
        monthly_signup_targets = [
            int(40 * (1.12 ** m)) for m in range(history_months)
        ]
        total_planned = sum(monthly_signup_targets)
        scale_factor = target_customers / total_planned if total_planned > 0 else 1.0

        for m_idx in range(history_months):
            month_date = start_history + timedelta(days=m_idx * 30)
            signups_in_month = int(monthly_signup_targets[m_idx] * scale_factor)

            for _ in range(signups_in_month):
                cust_counter += 1
                signup_day_offset = random.randint(0, 28)
                signup_time = month_date + timedelta(days=signup_day_offset, hours=random.randint(0, 23))
                if signup_time > now:
                    signup_time = now - timedelta(hours=random.randint(1, 12))

                cust_name, cust_email = generate_customer_profile(cust_counter)
                cust_id = uuid.uuid4()
                stripe_cust_id = f"cus_demo_{cust_counter:05d}_{uuid.uuid4().hex[:4]}"

                # 2% delinquency rate
                is_delinquent = random.random() < 0.02

                customer = Customer(
                    id=cust_id,
                    org_id=org_id,
                    stripe_id=stripe_cust_id,
                    email=cust_email,
                    name=cust_name,
                    delinquent=is_delinquent,
                    currency="usd",
                    created_at=signup_time,
                )
                customers_to_add.append(customer)

                # Subscription Lifecycle:
                # 35% trial converts to paid; 65% drop off
                # 75% monthly vs 25% annual
                # Upgrades and churn over time
                plan_tier_choice = random.choices(
                    ["Starter", "Growth", "Scale"],
                    weights=[0.60, 0.30, 0.10],
                )[0]
                interval_choice = "Annual" if random.random() < 0.25 else "Monthly"
                selected_plan_name = f"{plan_tier_choice} {interval_choice}"
                selected_plan = created_plans[selected_plan_name]

                has_trial = random.random() < 0.40
                trial_converted = random.random() < 0.65 if has_trial else True

                sub_id = uuid.uuid4()
                stripe_sub_id = f"sub_demo_{cust_counter:05d}_{uuid.uuid4().hex[:4]}"

                trial_start = signup_time if has_trial else None
                trial_end = signup_time + timedelta(days=14) if has_trial else None

                sub_start = trial_end if (has_trial and trial_converted) else signup_time

                # Determine if and when they churn:
                # Average lifetime ~ 8-12 months, ~3-4% monthly churn
                will_churn = random.random() < 0.25
                if not trial_converted:
                    # Dropped after trial
                    sub_status = "canceled"
                    canceled_at = trial_end
                    period_end = trial_end
                elif will_churn:
                    months_active = random.randint(1, max(1, history_months - m_idx))
                    canceled_at = sub_start + timedelta(days=months_active * 30)
                    if canceled_at > now:
                        sub_status = "active"
                        canceled_at = None
                        period_end = sub_start + timedelta(days=(months_active + 1) * 30)
                    else:
                        sub_status = "canceled"
                        period_end = canceled_at
                else:
                    sub_status = "past_due" if is_delinquent else "active"
                    canceled_at = None
                    period_end = now + timedelta(days=30)

                sub = Subscription(
                    id=sub_id,
                    org_id=org_id,
                    stripe_id=stripe_sub_id,
                    customer_id=cust_id,
                    status=sub_status,
                    current_period_start=sub_start,
                    current_period_end=period_end,
                    cancel_at_period_end=False,
                    canceled_at=canceled_at,
                    trial_start=trial_start,
                    trial_end=trial_end,
                    created_at=signup_time,
                )
                subs_to_add.append(sub)

                sub_item = SubscriptionItem(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    stripe_id=f"si_demo_{cust_counter:05d}",
                    subscription_id=sub_id,
                    plan_id=selected_plan.id,
                    quantity=1,
                )
                sub_items_to_add.append(sub_item)

                # Create sample invoices for this customer
                inv_status = "open" if is_delinquent else "paid"
                inv = Invoice(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    stripe_id=f"in_demo_{cust_counter:05d}",
                    customer_id=cust_id,
                    subscription_id=sub_id,
                    amount_due_cents=selected_plan.amount_cents,
                    amount_paid_cents=0 if is_delinquent else selected_plan.amount_cents,
                    currency="usd",
                    status=inv_status,
                    period_start=sub_start,
                    period_end=sub_start + timedelta(days=30),
                    created_at=sub_start,
                )
                invoices_to_add.append(inv)

        # Batch insert
        session.bulk_save_objects(customers_to_add)
        session.bulk_save_objects(subs_to_add)
        session.bulk_save_objects(sub_items_to_add)
        session.bulk_save_objects(invoices_to_add)
        session.commit()

        print(f"[+] Inserted {len(customers_to_add)} customers, {len(subs_to_add)} subscriptions, and {len(invoices_to_add)} invoices.")

    # 5. Compute mrr_daily and mrr_movements for the entire 18 months
    print("[*] Computing daily MRR snapshots across date spine...")
    with get_tenant_session(org_id) as session:
        MetricService.compute_daily_mrr_snapshots(
            session=session,
            org_id=org_id,
            start_date=start_history.date(),
            end_date=now.date(),
        )
    print("[+] Daily snapshots committed.")

    print("[*] Computing day-over-day MRR movements (new, expansion, contraction, churn)...")
    with get_tenant_session(org_id) as session:
        session.execute(text("ANALYZE mrr_daily;"))
        MetricService.compute_mrr_movements(
            session=session,
            org_id=org_id,
            start_date=start_history.date(),
            end_date=now.date(),
        )
    print("[+] MRR movements committed.")

    # 6. Refresh Materialized View
    print("[*] Refreshing cohort_retention_mv concurrently...")
    with get_migration_session() as session:
        MetricService.refresh_cohort_materialized_view(session)

    print(f"[SUCCESS] Demo Data Seed Completed for org_id: {org_id}!")
    return org_id

if __name__ == "__main__":
    import sys
    target = 2000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        target = int(sys.argv[1])
    seed_demo_organization(target_customers=target)
