import os
from dotenv import load_dotenv

# Load from .env if present
load_dotenv()

from scraper.turso_utils import init_turso, get_db

def migrate():
    print("Init Turso:", init_turso())
    db = get_db()
    
    conn = db._get_conn()
    
    commands = [
        "ALTER TABLE champions DROP COLUMN image_name;",
        "ALTER TABLE champions ADD COLUMN abilities_patch TEXT;",
        "ALTER TABLE global_info ADD COLUMN patch TEXT;",
        "ALTER TABLE global_info ADD COLUMN patch_last_updated DATETIME;"
    ]
    
    for cmd in commands:
        try:
            print(f"Executing: {cmd}")
            conn.execute(cmd)
            print("Success")
        except Exception as e:
            print(f"Error (may already be migrated): {e}")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
