import uuid
from sqlalchemy import Column, String, BigInteger, Date, DateTime, ForeignKey, PrimaryKeyConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models.base import utc_now

class MrrDaily(Base):
    """
    Daily snapshot of MRR per active subscription.
    Enables instant daily date-spine joins and point-in-time metrics without recalculating from history.
    """
    __tablename__ = "mrr_daily"

    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    mrr_cents = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(3), default="usd", nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("org_id", "date", "subscription_id", name="pk_mrr_daily"),
        Index("idx_mrr_daily_org_date", "org_id", "date"),
        Index("idx_mrr_daily_org_cust", "org_id", "customer_id"),
    )


class MrrMovement(Base):
    """
    Classified day-over-day MRR transitions per subscription:
    'new', 'expansion', 'contraction', 'churn', 'reactivation'
    """
    __tablename__ = "mrr_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    movement_type = Column(String(50), nullable=False) # new, expansion, contraction, churn, reactivation
    amount_cents = Column(BigInteger, default=0, nullable=False)
    prior_mrr_cents = Column(BigInteger, default=0, nullable=False)
    current_mrr_cents = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_mrr_movements_org_date", "org_id", "date"),
        Index("idx_mrr_movements_org_type", "org_id", "movement_type"),
    )
