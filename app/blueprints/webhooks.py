import os
import uuid
import json
import logging
import stripe
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import get_migration_session
from app.models import StripeEvent
from app.services.queue import JobQueue

logger = logging.getLogger(__name__)
webhooks_bp = Blueprint("webhooks", __name__)

@webhooks_bp.route("/stripe", methods=["POST"])
def stripe_webhook():
    """
    Receives webhooks from Stripe, verifies signature, stores raw payload
    in partitioned stripe_events table, and enqueues event processing job.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    event = None
    if webhook_secret and sig_header:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning("Stripe webhook signature failed: %s", str(e))
            return jsonify({"error": "Invalid signature"}), 400
    else:
        try:
            event = json.loads(payload)
        except Exception:
            return jsonify({"error": "Invalid JSON payload"}), 400

    stripe_event_id = event.get("id")
    event_type = event.get("type")
    created_ts = event.get("created", int(datetime.now(timezone.utc).timestamp()))
    event_created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)

    # Lookup tenant org_id if present in metadata or Stripe account
    # Default to global ingestion for processing
    org_id = None
    data_obj = event.get("data", {}).get("object", {})
    if "metadata" in data_obj and "org_id" in data_obj["metadata"]:
        try:
            org_id = uuid.UUID(data_obj["metadata"]["org_id"])
        except ValueError:
            pass

    with get_migration_session() as session:
        # Check idempotency
        existing = session.query(StripeEvent).filter_by(stripe_event_id=stripe_event_id).first()
        if not existing:
            # Need a fallback org_id if not in metadata: fetch primary demo/first org
            if not org_id:
                first_org = session.execute(text("SELECT id FROM organizations LIMIT 1")).scalar()
                org_id = first_org or uuid.uuid4()

            stripe_event_row = StripeEvent(
                id=uuid.uuid4(),
                org_id=org_id,
                stripe_event_id=stripe_event_id,
                event_type=event_type,
                payload=event,
                processed=False,
                created_at=event_created_at,
            )
            session.add(stripe_event_row)
            session.commit()

            # Enqueue processing in background job queue
            JobQueue.enqueue(
                "process_stripe_event",
                {"stripe_event_id": stripe_event_id, "org_id": str(org_id), "event_type": event_type}
            )

    return jsonify({"status": "received", "event_id": stripe_event_id}), 200
