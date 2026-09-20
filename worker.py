import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.database import get_migration_session, get_tenant_session
from app.services.queue import QueueService
from app.services.stripe_sync import StripeSyncService
from app.services.mrr import MetricService
from app.services.crypto import CryptoService
from app.models import StripeConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Worker] %(message)s",
)
logger = logging.getLogger("revpulse.worker")

RUNNING = True

def handle_shutdown(signum, frame):
    global RUNNING
    logger.info("Received termination signal. Shutting down worker gracefully...")
    RUNNING = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

def process_job(worker_id: str, job: dict) -> None:
    job_id = job["id"]
    task_type = job["task_type"]
    payload = job["payload"] or {}
    org_id = job.get("org_id")
    attempts = job.get("attempts", 1)
    max_attempts = job.get("max_attempts", 5)

    logger.info(f"[{worker_id}] Processing job {job_id} (Type: {task_type}, Attempt: {attempts}/{max_attempts})")

    try:
        if task_type == "backfill_sync":
            with get_migration_session() as session:
                conn = session.query(StripeConnection).filter_by(org_id=org_id).first()
                if not conn:
                    raise ValueError(f"No Stripe connection found for org {org_id}")
                api_key = CryptoService.decrypt(conn.encrypted_api_key)

            with get_tenant_session(org_id) as session:
                StripeSyncService.backfill_organization_data(session, org_id, api_key)

        elif task_type == "daily_snapshot":
            today = datetime.now(timezone.utc).date()
            start_date = today - timedelta(days=2)
            with get_tenant_session(org_id) as session:
                MetricService.compute_daily_mrr_snapshots(session, org_id, start_date, today)
                MetricService.compute_mrr_movements(session, org_id, start_date, today)

        elif task_type == "refresh_cohorts":
            with get_migration_session() as session:
                MetricService.refresh_cohort_materialized_view(session)

        elif task_type == "test_task":
            time.sleep(0.1)

        else:
            logger.warning(f"Unknown task type: {task_type}")

        # Mark completed
        with get_migration_session() as session:
            QueueService.complete_job(session, job_id)
        logger.info(f"[{worker_id}] Job {job_id} completed successfully.")

    except Exception as e:
        logger.error(f"[{worker_id}] Job {job_id} failed: {e}", exc_info=True)
        with get_migration_session() as session:
            QueueService.fail_job(session, job_id, str(e), attempts, max_attempts)

def run_worker():
    worker_id = f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    logger.info(f"Starting RevPulse Background Worker [{worker_id}]...")

    poll_interval = 1.0
    while RUNNING:
        try:
            with get_migration_session() as session:
                job = QueueService.fetch_and_lock_job(session, worker_id)

            if job:
                process_job(worker_id, job)
            else:
                time.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Worker polling loop error: {e}", exc_info=True)
            time.sleep(2.0)

    logger.info("Worker process exited cleanly.")

if __name__ == "__main__":
    run_worker()
