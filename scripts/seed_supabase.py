import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point to Supabase for the seed operation
SUPABASE_APP_URL = "postgresql+psycopg://postgres.utbefujmvhsvxxkrrbao:Rishwanth%4012345@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
os.environ["DATABASE_URL"] = SUPABASE_APP_URL
os.environ["DATABASE_MIGRATION_URL"] = SUPABASE_APP_URL
os.environ["DATABASE_READONLY_URL"] = SUPABASE_APP_URL

from scripts.seed_demo_data import seed_demo_organization

if __name__ == "__main__":
    print("[*] Seeding 500 customers across 18 months of history into Supabase...")
    org_id = seed_demo_organization(target_customers=500, history_months=18)
    print(f"[✓] Successfully seeded Supabase organization: {org_id}")
