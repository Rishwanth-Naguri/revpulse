import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig

SUPABASE_URL = "postgresql://postgres.utbefujmvhsvxxkrrbao:Rishwanth%4012345@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
SUPABASE_ALEMBIC_URL = "postgresql+psycopg://postgres.utbefujmvhsvxxkrrbao:Rishwanth%4012345@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"

def setup_cloud_database():
    print("[*] Step 1: Connecting to Supabase and ensuring schemas & extensions...")
    with psycopg.connect(SUPABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
            cur.execute('CREATE SCHEMA IF NOT EXISTS analytics;')
            print("[+] Extension and analytics schema ready.")

            # Create roles if they do not exist
            roles_sql = """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_migrator') THEN
                    CREATE ROLE revpulse_migrator WITH LOGIN PASSWORD 'migrator_secret_change_in_prod';
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_app') THEN
                    CREATE ROLE revpulse_app WITH LOGIN PASSWORD 'app_secret_change_in_prod';
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_readonly') THEN
                    CREATE ROLE revpulse_readonly WITH LOGIN PASSWORD 'readonly_secret_change_in_prod';
                END IF;
            END
            $$;
            """
            cur.execute(roles_sql)
            print("[+] revpulse_migrator, revpulse_app, and revpulse_readonly roles created.")

    print("[*] Step 2: Running Alembic migrations on Supabase...")
    os.environ["DATABASE_MIGRATION_URL"] = SUPABASE_ALEMBIC_URL
    alembic_cfg = AlembicConfig("alembic.ini")
    # In configparser % must be escaped as %%
    alembic_cfg.set_main_option("sqlalchemy.url", SUPABASE_ALEMBIC_URL.replace("%", "%%"))
    command.upgrade(alembic_cfg, "head")
    print("[+] Alembic migrations successfully applied to Supabase!")

if __name__ == "__main__":
    setup_cloud_database()
