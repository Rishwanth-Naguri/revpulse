import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models.base import utc_now

class AiQueryLog(Base):
    __tablename__ = "ai_query_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    status = Column(String(50), nullable=False) # 'success', 'blocked_guard', 'execution_error'
    error = Column(Text, nullable=True)
    rows_count = Column(Integer, default=0, nullable=False)
    execution_time_ms = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_ai_query_org_created", "org_id", "created_at"),
    )
