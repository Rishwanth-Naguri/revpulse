import contextlib
from typing import Generator, Optional
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import Config

# Declarative Base for models
Base = declarative_base()

# Application engine (revpulse_app role, RLS enforced)
app_engine = create_engine(
    Config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
AppSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=app_engine)

# Migration / DDL engine (revpulse_migrator role)
migration_engine = create_engine(
    Config.DATABASE_MIGRATION_URL,
    pool_pre_ping=True,
)
MigrationSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=migration_engine)

# Readonly AI engine (revpulse_readonly role, analytics schema)
readonly_engine = create_engine(
    Config.DATABASE_READONLY_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
ReadonlySessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=readonly_engine)


@contextlib.contextmanager
def get_tenant_session(org_id: Optional[uuid.UUID | str] = None) -> Generator[Session, None, None]:
    """
    Context manager that yields an SQLAlchemy session with Row-Level Security
    enforced via transaction-local setting `SELECT set_config('app.current_org_id', :org_id, true)`.

    Compatible with transaction-mode connection pooling (PgBouncer, Neon, Supabase).
    If org_id is None or empty, tenant queries fail-safe to 0 rows.
    """
    session = AppSessionLocal()
    try:
        if org_id:
            # Enforce tenant context inside the transaction (is_local = true)
            session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )
        else:
            # Reset or set empty string to guarantee fail-safe 0 rows
            session.execute(text("SELECT set_config('app.current_org_id', '', true)"))
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextlib.contextmanager
def get_readonly_session(org_id: Optional[uuid.UUID | str] = None) -> Generator[Session, None, None]:
    """
    Yields a read-only session connected as revpulse_readonly.
    Strictly constrained by statement_timeout and RLS.
    """
    session = ReadonlySessionLocal()
    try:
        if org_id:
            session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )
        else:
            session.execute(text("SELECT set_config('app.current_org_id', '', true)"))
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextlib.contextmanager
def get_migration_session() -> Generator[Session, None, None]:
    """
    Session for running administrative DDL, role initialization, and Alembic migrations.
    """
    session = MigrationSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
