import uuid
import threading
from sqlalchemy import text
from app.database import get_migration_session
from app.services.queue import QueueService

def test_job_queue_concurrency_and_dead_letter():
    """
    Verify:
    1. Two concurrent workers never receive the same job (FOR UPDATE SKIP LOCKED).
    2. Failed jobs increment attempts and transition to dead_letter upon exceeding max_attempts.
    """
    with get_migration_session() as session:
        session.execute(text("DELETE FROM jobs WHERE task_type IN ('test_task', 'failing_task')"))
        session.commit()

        # Enqueue 5 distinct jobs
        job_ids = [
            QueueService.enqueue_job(
                session=session,
                task_type="test_task",
                payload={"index": i},
                max_attempts=2,
            )
            for i in range(5)
        ]

    claimed_jobs_worker_1 = []
    claimed_jobs_worker_2 = []

    def worker_loop(worker_id: str, claimed_list: list):
        with get_migration_session() as session:
            for _ in range(10):
                job = QueueService.fetch_and_lock_job(session, worker_id)
                if job:
                    if job["id"] in job_ids:
                        claimed_list.append(job["id"])
                    QueueService.complete_job(session, job["id"])

    t1 = threading.Thread(target=worker_loop, args=("worker_alpha", claimed_jobs_worker_1))
    t2 = threading.Thread(target=worker_loop, args=("worker_beta", claimed_jobs_worker_2))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 1. Assert no job was claimed more than once
    intersection = set(claimed_jobs_worker_1).intersection(set(claimed_jobs_worker_2))
    assert len(intersection) == 0, f"Collision detected! Both workers claimed: {intersection}"
    total_claimed = len(claimed_jobs_worker_1) + len(claimed_jobs_worker_2)
    assert total_claimed == 5, f"Expected 5 claimed jobs, got {total_claimed}"

    # 2. Test failure and dead-letter logic
    with get_migration_session() as session:
        failing_job_id = QueueService.enqueue_job(
            session=session,
            task_type="failing_task",
            payload={"test": "failure"},
            max_attempts=2,
        )

        # Attempt 1: Fetch and fail
        job1 = QueueService.fetch_and_lock_job(session, "worker_test")
        assert job1 is not None
        assert job1["id"] == failing_job_id
        assert job1["attempts"] == 1
        QueueService.fail_job(session, failing_job_id, "Temporary network timeout", attempts=1, max_attempts=2)

        # Force run_at to now for immediate test of retry attempt 2
        session.execute(
            text("UPDATE jobs SET run_at = NOW() - interval '1 second' WHERE id = :job_id"),
            {"job_id": str(failing_job_id)},
        )
        session.commit()

        # Attempt 2: Fetch and fail again -> reaches dead_letter
        job2 = QueueService.fetch_and_lock_job(session, "worker_test")
        assert job2 is not None
        assert job2["id"] == failing_job_id
        assert job2["attempts"] == 2
        QueueService.fail_job(session, failing_job_id, "Fatal database corruption", attempts=2, max_attempts=2)

        # Verify it is now dead_letter and cannot be locked by worker
        job3 = QueueService.fetch_and_lock_job(session, "worker_test")
        assert job3 is None
