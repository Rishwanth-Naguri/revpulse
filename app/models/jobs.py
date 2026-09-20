import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
from app.models.base import utc_now

class Job(Base):
    """
    Postgres-backed reliable job queue.
    Worker processes poll pending records using SELECT ... FOR UPDATE SKIP LOCKED.
    Supports exponential backoff, locking lease, and dead-letter queuing.
    """
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    task_type = Column(String(100), nullable=False) # 'backfill_sync', 'process_webhook', 'daily_snapshot', etc.
    payload = Column(JSONB, default=dict, nullable=False)
    status = Column(String(50), default="pending", nullable=False) # 'pending', 'processing', 'completed', 'failed', 'dead_letter'
    run_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(255), nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_jobs_run_at_pending", "run_at", postgresql_where=(status == "pending")),
        Index("idx_jobs_org_status", "org_id", "status"),
    )
