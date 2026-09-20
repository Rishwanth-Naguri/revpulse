import uuid
from datetime import datetime
from sqlalchemy import Column, String, BigInteger, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.base import utc_now

class StripeConnection(Base):
    __tablename__ = "stripe_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    encrypted_api_key = Column(Text, nullable=False)
    livemode = Column(Boolean, default=False, nullable=False)
    status = Column(String(50), default="connected", nullable=False) # 'connected' | 'syncing' | 'active' | 'error'
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    organization = relationship("Organization", back_populates="stripe_connection")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_id = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=True)
    delinquent = Column(Boolean, default=False, nullable=False)
    currency = Column(String(3), default="usd", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    raw_json = Column(JSONB, nullable=True)

    subscriptions = relationship("Subscription", back_populates="customer", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="customer", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("org_id", "stripe_id", name="uq_customers_org_stripe_id"),
        Index("idx_customers_org_id", "org_id"),
    )


class Plan(Base):
    __tablename__ = "plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    amount_cents = Column(BigInteger, default=0, nullable=False) # minor units
    currency = Column(String(3), default="usd", nullable=False)
    interval = Column(String(50), default="month", nullable=False) # month, year, week, day
    interval_count = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    raw_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    subscription_items = relationship("SubscriptionItem", back_populates="plan")

    __table_args__ = (
        UniqueConstraint("org_id", "stripe_id", name="uq_plans_org_stripe_id"),
        Index("idx_plans_org_id", "org_id"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_id = Column(String(255), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False) # active, trialing, past_due, canceled, unpaid, incomplete
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    trial_start = Column(DateTime(timezone=True), nullable=True)
    trial_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    raw_json = Column(JSONB, nullable=True)

    customer = relationship("Customer", back_populates="subscriptions")
    items = relationship("SubscriptionItem", back_populates="subscription", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("org_id", "stripe_id", name="uq_subscriptions_org_stripe_id"),
        Index("idx_subscriptions_org_status", "org_id", "status"),
        Index("idx_subscriptions_org_cust", "org_id", "customer_id"),
    )


class SubscriptionItem(Base):
    __tablename__ = "subscription_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_id = Column(String(255), nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    raw_json = Column(JSONB, nullable=True)

    subscription = relationship("Subscription", back_populates="items")
    plan = relationship("Plan", back_populates="subscription_items")

    __table_args__ = (
        UniqueConstraint("org_id", "stripe_id", name="uq_sub_items_org_stripe_id"),
        Index("idx_sub_items_org_sub", "org_id", "subscription_id"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_id = Column(String(255), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    amount_due_cents = Column(BigInteger, default=0, nullable=False)
    amount_paid_cents = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(3), default="usd", nullable=False)
    status = Column(String(50), nullable=False) # paid, open, uncollectible, void
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    raw_json = Column(JSONB, nullable=True)

    customer = relationship("Customer", back_populates="invoices")

    __table_args__ = (
        UniqueConstraint("org_id", "stripe_id", name="uq_invoices_org_stripe_id"),
        Index("idx_invoices_org_status", "org_id", "status"),
        Index("idx_invoices_org_created", "org_id", "created_at"),
    )
