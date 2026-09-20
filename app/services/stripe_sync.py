import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

import stripe
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Config
from app.models import (
    StripeConnection,
    Customer,
    Plan,
    Subscription,
    SubscriptionItem,
    Invoice,
)
from app.services.mrr import MetricService

logger = logging.getLogger(__name__)

# Pin official Stripe API version
stripe.api_version = Config.STRIPE_API_VERSION


class StripeSyncService:
    @staticmethod
    def verify_api_key(api_key: str) -> Tuple[bool, bool, Optional[str]]:
        """
        Validates a restricted or secret Stripe API key.
        Returns (is_valid, is_livemode, error_message).
        """
        try:
            balance = stripe.Balance.retrieve(api_key=api_key)
            is_livemode = getattr(balance, "livemode", False)
            return True, is_livemode, None
        except stripe.AuthenticationError as e:
            return False, False, f"Invalid Stripe API Key: {str(e)}"
        except stripe.PermissionError as e:
            return False, False, f"Insufficient permissions on restricted key: {str(e)}"
        except Exception as e:
            return False, False, f"Stripe connection error: {str(e)}"

    @staticmethod
    def _execute_with_retry(func, *args, max_retries: int = 4, **kwargs):
        """
        Executes a Stripe API call with exponential backoff on rate limits.
        """
        delay = 1.0
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except stripe.RateLimitError as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Stripe rate limit hit, backing off {delay}s: {e}")
                time.sleep(delay)
                delay *= 2
            except stripe.APIConnectionError as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Stripe API connection glitch, retrying in {delay}s: {e}")
                time.sleep(delay)
                delay *= 1.5

    @classmethod
    def backfill_organization_data(cls, session: Session, org_id: uuid.UUID, api_key: str) -> Dict[str, int]:
        """
        Full backfill of Stripe Customers, Prices/Plans, Subscriptions, and Invoices.
        Handles cursor-based pagination and stores raw JSON payloads.
        """
        stats = {"customers": 0, "plans": 0, "subscriptions": 0, "invoices": 0}

        # 1. Backfill Prices / Plans
        logger.info(f"Backfilling prices for org {org_id}...")
        has_more = True
        starting_after = None

        while has_more:
            params: Dict[str, Any] = {"limit": 100, "expand": ["data.product"]}
            if starting_after:
                params["starting_after"] = starting_after

            prices_page = cls._execute_with_retry(
                stripe.Price.list,
                api_key=api_key,
                **params,
            )

            for p in prices_page.data:
                product_name = p.product.name if hasattr(p, "product") and hasattr(p.product, "name") else "Plan"
                recurring = p.recurring or {}
                interval = recurring.get("interval", "month")
                interval_count = recurring.get("interval_count", 1)

                plan_obj = session.query(Plan).filter_by(org_id=org_id, stripe_id=p.id).first()
                if not plan_obj:
                    plan_obj = Plan(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        stripe_id=p.id,
                        name=product_name,
                        amount_cents=p.unit_amount or 0,
                        currency=p.currency,
                        interval=interval,
                        interval_count=interval_count,
                        is_active=p.active,
                        raw_json=p.to_dict_recursive(),
                    )
                    session.add(plan_obj)
                else:
                    plan_obj.name = product_name
                    plan_obj.amount_cents = p.unit_amount or 0
                    plan_obj.currency = p.currency
                    plan_obj.interval = interval
                    plan_obj.interval_count = interval_count
                    plan_obj.is_active = p.active
                    plan_obj.raw_json = p.to_dict_recursive()

                stats["plans"] += 1

            has_more = prices_page.has_more
            if prices_page.data:
                starting_after = prices_page.data[-1].id

        session.commit()

        # 2. Backfill Customers
        logger.info(f"Backfilling customers for org {org_id}...")
        has_more = True
        starting_after = None

        while has_more:
            params = {"limit": 100}
            if starting_after:
                params["starting_after"] = starting_after

            cust_page = cls._execute_with_retry(
                stripe.Customer.list,
                api_key=api_key,
                **params,
            )

            for c in cust_page.data:
                created_dt = datetime.fromtimestamp(c.created, tz=timezone.utc)
                cust_obj = session.query(Customer).filter_by(org_id=org_id, stripe_id=c.id).first()
                if not cust_obj:
                    cust_obj = Customer(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        stripe_id=c.id,
                        email=c.email,
                        name=c.name or (c.email or "Customer"),
                        delinquent=c.delinquent or False,
                        currency=c.currency or "usd",
                        created_at=created_dt,
                        raw_json=c.to_dict_recursive(),
                    )
                    session.add(cust_obj)
                else:
                    cust_obj.email = c.email
                    cust_obj.name = c.name or cust_obj.name
                    cust_obj.delinquent = c.delinquent or False
                    cust_obj.currency = c.currency or cust_obj.currency
                    cust_obj.raw_json = c.to_dict_recursive()

                stats["customers"] += 1

            has_more = cust_page.has_more
            if cust_page.data:
                starting_after = cust_page.data[-1].id

        session.commit()

        # 3. Backfill Subscriptions
        logger.info(f"Backfilling subscriptions for org {org_id}...")
        has_more = True
        starting_after = None

        while has_more:
            params = {
                "limit": 100,
                "status": "all",
                "expand": ["data.items.data.price"],
            }
            if starting_after:
                params["starting_after"] = starting_after

            sub_page = cls._execute_with_retry(
                stripe.Subscription.list,
                api_key=api_key,
                **params,
            )

            for s in sub_page.data:
                cust_obj = session.query(Customer).filter_by(org_id=org_id, stripe_id=s.customer).first()
                if not cust_obj:
                    continue

                p_start = datetime.fromtimestamp(s.current_period_start, tz=timezone.utc)
                p_end = datetime.fromtimestamp(s.current_period_end, tz=timezone.utc)
                c_at = datetime.fromtimestamp(s.canceled_at, tz=timezone.utc) if s.canceled_at else None
                t_start = datetime.fromtimestamp(s.trial_start, tz=timezone.utc) if s.trial_start else None
                t_end = datetime.fromtimestamp(s.trial_end, tz=timezone.utc) if s.trial_end else None

                sub_obj = session.query(Subscription).filter_by(org_id=org_id, stripe_id=s.id).first()
                if not sub_obj:
                    sub_obj = Subscription(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        stripe_id=s.id,
                        customer_id=cust_obj.id,
                        status=s.status,
                        current_period_start=p_start,
                        current_period_end=p_end,
                        cancel_at_period_end=s.cancel_at_period_end,
                        canceled_at=c_at,
                        trial_start=t_start,
                        trial_end=t_end,
                        created_at=datetime.fromtimestamp(s.created, tz=timezone.utc),
                        raw_json=s.to_dict_recursive(),
                    )
                    session.add(sub_obj)
                    session.flush()
                else:
                    sub_obj.status = s.status
                    sub_obj.current_period_start = p_start
                    sub_obj.current_period_end = p_end
                    sub_obj.cancel_at_period_end = s.cancel_at_period_end
                    sub_obj.canceled_at = c_at
                    sub_obj.trial_start = t_start
                    sub_obj.trial_end = t_end
                    sub_obj.raw_json = s.to_dict_recursive()

                # Sync Subscription Items
                for item in s.items.data:
                    plan_obj = session.query(Plan).filter_by(org_id=org_id, stripe_id=item.price.id).first()
                    if not plan_obj:
                        continue

                    si_obj = session.query(SubscriptionItem).filter_by(org_id=org_id, stripe_id=item.id).first()
                    if not si_obj:
                        si_obj = SubscriptionItem(
                            id=uuid.uuid4(),
                            org_id=org_id,
                            stripe_id=item.id,
                            subscription_id=sub_obj.id,
                            plan_id=plan_obj.id,
                            quantity=item.quantity or 1,
                            raw_json=item.to_dict_recursive(),
                        )
                        session.add(si_obj)
                    else:
                        si_obj.quantity = item.quantity or 1
                        si_obj.raw_json = item.to_dict_recursive()

                stats["subscriptions"] += 1

            has_more = sub_page.has_more
            if sub_page.data:
                starting_after = sub_page.data[-1].id

        session.commit()

        # 4. Backfill Invoices
        logger.info(f"Backfilling invoices for org {org_id}...")
        has_more = True
        starting_after = None

        while has_more:
            params = {"limit": 100}
            if starting_after:
                params["starting_after"] = starting_after

            inv_page = cls._execute_with_retry(
                stripe.Invoice.list,
                api_key=api_key,
                **params,
            )

            for inv in inv_page.data:
                cust_obj = session.query(Customer).filter_by(org_id=org_id, stripe_id=inv.customer).first()
                if not cust_obj:
                    continue

                sub_obj = session.query(Subscription).filter_by(org_id=org_id, stripe_id=inv.subscription).first() if inv.subscription else None

                p_start = datetime.fromtimestamp(inv.period_start, tz=timezone.utc) if inv.period_start else datetime.fromtimestamp(inv.created, tz=timezone.utc)
                p_end = datetime.fromtimestamp(inv.period_end, tz=timezone.utc) if inv.period_end else p_start

                inv_obj = session.query(Invoice).filter_by(org_id=org_id, stripe_id=inv.id).first()
                if not inv_obj:
                    inv_obj = Invoice(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        stripe_id=inv.id,
                        customer_id=cust_obj.id,
                        subscription_id=sub_obj.id if sub_obj else None,
                        amount_due_cents=inv.amount_due or 0,
                        amount_paid_cents=inv.amount_paid or 0,
                        currency=inv.currency,
                        status=inv.status or "open",
                        period_start=p_start,
                        period_end=p_end,
                        created_at=datetime.fromtimestamp(inv.created, tz=timezone.utc),
                        raw_json=inv.to_dict_recursive(),
                    )
                    session.add(inv_obj)
                else:
                    inv_obj.amount_due_cents = inv.amount_due or 0
                    inv_obj.amount_paid_cents = inv.amount_paid or 0
                    inv_obj.status = inv.status or "open"
                    inv_obj.raw_json = inv.to_dict_recursive()

                stats["invoices"] += 1

            has_more = inv_page.has_more
            if inv_page.data:
                starting_after = inv_page.data[-1].id

        session.commit()

        # 5. Recompute MRR Daily and Movements
        logger.info(f"Recomputing metrics for org {org_id} after backfill...")
        earliest_sub = session.query(Subscription.current_period_start).filter_by(org_id=org_id).order_by(Subscription.current_period_start.asc()).first()
        start_date = earliest_sub[0].date() if earliest_sub else (datetime.now(timezone.utc) - timedelta(days=90)).date()
        today = datetime.now(timezone.utc).date()

        MetricService.compute_daily_mrr_snapshots(session, org_id, start_date, today)
        MetricService.compute_mrr_movements(session, org_id, start_date, today)

        # Update Connection Status
        conn = session.query(StripeConnection).filter_by(org_id=org_id).first()
        if conn:
            conn.status = "active"
            conn.last_synced_at = datetime.now(timezone.utc)
            conn.sync_error = None
            session.commit()

        logger.info(f"Backfill finished successfully for org {org_id}: {stats}")
        return stats
