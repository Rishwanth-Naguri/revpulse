-- ==============================================================================
-- RevPulse PostgreSQL Database Initialization & Role Isolation
-- Executed by postgres superuser on fresh database initialization
-- ==============================================================================

-- 1. Create Roles if they do not exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_migrator') THEN
        CREATE ROLE revpulse_migrator WITH LOGIN PASSWORD 'migrator_password' CREATEDB BYPASSRLS;
    ELSE
        ALTER ROLE revpulse_migrator BYPASSRLS;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_app') THEN
        CREATE ROLE revpulse_app WITH LOGIN PASSWORD 'app_password' NOINHERIT NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revpulse_readonly') THEN
        CREATE ROLE revpulse_readonly WITH LOGIN PASSWORD 'readonly_password' NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

-- Configure strict statement timeouts on the AI role
ALTER ROLE revpulse_readonly SET statement_timeout = '3000ms';

-- 2. Create and configure Database
\connect revpulse

-- 3. Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 4. Schemas
CREATE SCHEMA IF NOT EXISTS public;
CREATE SCHEMA IF NOT EXISTS analytics;

ALTER SCHEMA public OWNER TO revpulse_migrator;
ALTER SCHEMA analytics OWNER TO revpulse_migrator;

GRANT ALL ON SCHEMA public TO revpulse_migrator;
GRANT ALL ON SCHEMA analytics TO revpulse_migrator;
GRANT ALL ON DATABASE revpulse TO revpulse_migrator;

-- 5. Permissions
-- Revpulse App Permissions
GRANT CONNECT ON DATABASE revpulse TO revpulse_app;
GRANT USAGE, CREATE ON SCHEMA public TO revpulse_app;
GRANT USAGE ON SCHEMA analytics TO revpulse_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO revpulse_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO revpulse_app;
ALTER DEFAULT PRIVILEGES FOR ROLE revpulse_migrator IN SCHEMA public GRANT ALL ON TABLES TO revpulse_app;
ALTER DEFAULT PRIVILEGES FOR ROLE revpulse_migrator IN SCHEMA public GRANT ALL ON SEQUENCES TO revpulse_app;

-- Revpulse Readonly (AI Engine) Permissions
-- Strict least privilege: only SELECT on analytics schema
GRANT CONNECT ON DATABASE revpulse TO revpulse_readonly;
GRANT USAGE ON SCHEMA analytics TO revpulse_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO revpulse_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE revpulse_migrator IN SCHEMA analytics GRANT SELECT ON TABLES TO revpulse_readonly;

-- Revpulse Readonly must NOT have access to public tables directly
REVOKE ALL ON SCHEMA public FROM revpulse_readonly;
