import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Config:
    FLASK_ENV: str = os.getenv("FLASK_ENV", "development")
    DEBUG: bool = os.getenv("FLASK_DEBUG", "1") == "1"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production-1234567890")

    # Database URLs
    # Primary application connection (RLS-enforced revpulse_app role)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://revpulse_app:app_password@localhost:5432/revpulse"
    )
    # Admin migration connection (revpulse_migrator role)
    DATABASE_MIGRATION_URL: str = os.getenv(
        "DATABASE_MIGRATION_URL",
        "postgresql+psycopg://revpulse_migrator:migrator_password@localhost:5432/revpulse"
    )
    # Readonly AI connection (revpulse_readonly role with statement timeout)
    DATABASE_READONLY_URL: str = os.getenv(
        "DATABASE_READONLY_URL",
        "postgresql+psycopg://revpulse_readonly:readonly_password@localhost:5432/revpulse"
    )

    # Key for encrypting customer Stripe API keys
    ENCRYPTION_KEY: str = os.getenv(
        "ENCRYPTION_KEY",
        "W36r2sFq5_z9j_6tqO5Yk_7h4YyHqP1kR_p1u4M9j5U="
    )

    # Stripe Platform Credentials (for RevPulse itself)
    STRIPE_API_KEY: str = os.getenv("STRIPE_API_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_BILLING_WEBHOOK_SECRET: str = os.getenv("STRIPE_BILLING_WEBHOOK_SECRET", "")
    STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "price_pro_monthly")

    # Pinned Stripe API Version
    STRIPE_API_VERSION: str = "2024-06-20"

    # AI Provider Settings
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # Notifications
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", "alerts@revpulse.dev")
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

    # Cron authentication
    CRON_SECRET: str = os.getenv("CRON_SECRET", "super_secret_cron_header_token_12345")
