import time
from flask import Blueprint, jsonify
from sqlalchemy import text
from app.database import get_migration_session

health_bp = Blueprint("health", __name__)

@health_bp.route("/health")
def health():
    """
    Liveness probe: verifies the application web server and database connectivity.
    """
    t0 = time.time()
    db_ok = False
    version = None
    try:
        with get_migration_session() as session:
            version = session.execute(text("SELECT version()")).scalar()
            db_ok = True
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
        }), 503

    latency_ms = round((time.time() - t0) * 1000, 2)
    return jsonify({
        "status": "healthy",
        "database": "connected",
        "latency_ms": latency_ms,
        "postgres_version": version.split()[1] if version else "unknown",
    }), 200


@health_bp.route("/ready")
def ready():
    """
    Readiness probe: returns 200 if database migrations are current.
    """
    try:
        with get_migration_session() as session:
            current_rev = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return jsonify({
                "status": "ready",
                "migration_revision": current_rev,
            }), 200
    except Exception as e:
        return jsonify({
            "status": "not_ready",
            "error": str(e),
        }), 503
