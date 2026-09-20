from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models.jobs import Job

class QueueService:
    @staticmethod
    def enqueue_job(
        session: Session,
        task_type: str,
        payload: Dict[str, Any],
        org_id: Optional[uuid.UUID] = None,
        run_at: Optional[datetime] = None,
        max_attempts: int = 5,
    ) -> uuid.UUID:
        """
        Enqueues a new background task into the Postgres jobs table.
        """
        if run_at is None:
            # 1 second offset avoids microsecond clock skew between host and container
            run_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        job_id = uuid.uuid4()
        job = Job(
            id=job_id,
            org_id=org_id,
            task_type=task_type,
            payload=payload,
            status="pending",
            run_at=run_at,
            max_attempts=max_attempts,
        )
        session.add(job)
        session.commit()
        return job_id

    @classmethod
    def enqueue(
        cls,
        task_type: str,
        payload: Dict[str, Any],
        org_id: Optional[uuid.UUID] = None,
        run_at: Optional[datetime] = None,
        max_attempts: int = 5,
    ) -> uuid.UUID:
        from app.database import get_migration_session
        with get_migration_session() as session:
            return cls.enqueue_job(session, task_type, payload, org_id, run_at, max_attempts)

    @staticmethod
    def fetch_and_lock_job(session: Session, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically selects and locks the next pending job using
        SELECT ... FOR UPDATE SKIP LOCKED. Safe for multiple concurrent workers.
        """
        query = text("""
        WITH next_job AS (
            SELECT id FROM jobs
            WHERE status = 'pending'
              AND run_at <= NOW()
            ORDER BY run_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE jobs
        SET status = 'processing',
            locked_at = NOW(),
            locked_by = :worker_id,
            attempts = attempts + 1
        FROM next_job
        WHERE jobs.id = next_job.id
        RETURNING jobs.id, jobs.task_type, jobs.payload, jobs.org_id, jobs.attempts, jobs.max_attempts;
        """)

        row = session.execute(query, {"worker_id": worker_id}).fetchone()
        session.commit()

        if not row:
            return None

        return {
            "id": row[0],
            "task_type": row[1],
            "payload": row[2],
            "org_id": row[3],
            "attempts": row[4],
            "max_attempts": row[5],
        }

    @staticmethod
    def complete_job(session: Session, job_id: uuid.UUID) -> None:
        """
        Marks a job as successfully completed.
        """
        query = text("""
        UPDATE jobs
        SET status = 'completed',
            locked_at = NULL,
            locked_by = NULL
        WHERE id = :job_id;
        """)
        session.execute(query, {"job_id": str(job_id)})
        session.commit()

    @staticmethod
    def fail_job(session: Session, job_id: uuid.UUID, error_message: str, attempts: int, max_attempts: int) -> None:
        """
        Handles job failure with exponential backoff retry.
        If attempts exceed max_attempts, moves the job to 'dead_letter' status.
        """
        if attempts >= max_attempts:
            new_status = "dead_letter"
            next_run = None
        else:
            new_status = "pending"
            delay_sec = (2 ** attempts) * 5 # 10s, 20s, 40s, 80s
            next_run = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)

        query = text("""
        UPDATE jobs
        SET status = :status,
            locked_at = NULL,
            locked_by = NULL,
            last_error = :error,
            run_at = COALESCE(:run_at, run_at)
        WHERE id = :job_id;
        """)
        session.execute(
            query,
            {
                "job_id": str(job_id),
                "status": new_status,
                "error": error_message[:2000],
                "run_at": next_run.isoformat() if next_run else None,
            },
        )
        session.commit()

JobQueue = QueueService
