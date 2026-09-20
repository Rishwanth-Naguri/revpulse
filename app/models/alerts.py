import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models.base import utc_now

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    rule_type = Column(String(100), nullable=False) # 'churn_spike', 'failed_payment_spike'
    threshold_percent = Column(Integer, default=15, nullable=False) # e.g. 15% above 4-week avg
    channel = Column(String(50), default="both", nullable=False) # 'slack', 'email', 'both'
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_alert_rules_org", "org_id"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(50), default="triggered", nullable=False) # 'triggered', 'sent', 'failed'
    triggered_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_alerts_org_triggered", "org_id", "triggered_at"),
    )
