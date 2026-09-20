import os
from flask import Flask, g, redirect, url_for, request
from flask_login import LoginManager, current_user
from authlib.integrations.flask_client import OAuth

from app.config import Config
from app.database import get_migration_session
from app.models import User, Organization, Membership

login_manager = LoginManager()
oauth = OAuth()

def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    oauth.init_app(app)

    # Configure Google OAuth client (mock or real if configured)
    if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            access_token_url="https://accounts.google.com/o/oauth2/token",
            access_token_params=None,
            authorize_url="https://accounts.google.com/o/oauth2/auth",
            authorize_params=None,
            api_base_url="https://www.googleapis.com/oauth2/v1/",
            client_kwargs={"scope": "openid email profile"},
        )

    @login_manager.user_loader
    def load_user(user_id: str):
        with get_migration_session() as session:
            user = session.get(User, user_id)
            if user:
                session.expunge(user)
            return user

    @app.before_request
    def set_request_tenant_context():
        """
        Extract active org_id from authenticated user's session/membership
        and attach to flask request context `g.org_id`.
        """
        g.org_id = None
        g.organization = None
        if current_user and current_user.is_authenticated:
            with get_migration_session() as session:
                membership = (
                    session.query(Membership)
                    .filter_by(user_id=current_user.id)
                    .first()
                )
                if membership:
                    g.org_id = membership.org_id
                    g.org_role = membership.role
                    g.organization = session.get(Organization, membership.org_id)

    # Register blueprints
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.metrics import metrics_bp
    from app.blueprints.customers import customers_bp
    from app.blueprints.cohorts import cohorts_bp
    from app.blueprints.alerts import alerts_bp
    from app.blueprints.ask import ask_bp
    from app.blueprints.stripe_connect import stripe_bp
    from app.blueprints.webhooks import webhooks_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.billing import billing_bp
    from app.blueprints.health import health_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(metrics_bp, url_prefix="/api/metrics")
    app.register_blueprint(customers_bp, url_prefix="/customers")
    app.register_blueprint(cohorts_bp, url_prefix="/cohorts")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")
    app.register_blueprint(ask_bp, url_prefix="/ask")
    app.register_blueprint(stripe_bp, url_prefix="/api/stripe")
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(health_bp, url_prefix="/api")

    return app
