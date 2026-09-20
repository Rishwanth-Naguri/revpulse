import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
from app.models.base import utc_now

class StripeEvent(Base):
    """
    Partitioned table for storing raw incoming Stripe Webhook events.
    Partitioned by RANGE on `created_at` (monthly partitions).
    Because PostgreSQL requires unique constraints on partitioned tables to include
    the partition key, uniqueness is enforced on (org_id, stripe_event_id, created_at).
    """
    __tablename__ = "stripe_events"

    id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_event_id = Column(String(255), nullable=False)
    event_type = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    payload = Column(JSONB, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        UniqueConstraint("org_id", "stripe_event_id", "created_at", name="uq_stripe_events_org_event_created"),
        Index("idx_stripe_events_org_type", "org_id", "event_type"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )
