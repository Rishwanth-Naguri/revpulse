import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from flask_login import UserMixin
from app.database import Base
from app.models.base import utc_now

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    plan_tier = Column(String(50), default="free", nullable=False) # 'free' | 'pro'
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
    stripe_connection = relationship("StripeConnection", back_populates="organization", uselist=False, cascade="all, delete-orphan")


class User(Base, UserMixin):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True) # null if Google OAuth only
    full_name = Column(String(255), nullable=False)
    google_id = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    def get_id(self) -> str:
        return str(self.id)


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), default="member", nullable=False) # 'owner' | 'member'
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
    )
