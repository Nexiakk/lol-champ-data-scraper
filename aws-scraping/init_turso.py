import os
import sys
import asyncio
import libsql_client

async def init_db():
    url = os.environ.get("TURSO_DB_URL")
    if url and url.startswith("libsql://"):
        url = url.replace("libsql://", "https://", 1)
        
    auth_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if not url or not auth_token:
        print("Missing credentials")
        sys.exit(1)
        
    print(f"Connecting to {url}...")
    async with libsql_client.create_client(url, auth_token=auth_token) as client:
        print("Creating tables...")
        
        await client.execute('''
            CREATE TABLE IF NOT EXISTS champions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                image_name TEXT,
                patch TEXT,
                roles_json TEXT,
                abilities_json TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- champions created")
        
        await client.execute('''
            CREATE TABLE IF NOT EXISTS global_info (
                id TEXT PRIMARY KEY,
                abilities_patch TEXT,
                abilities_last_updated DATETIME
            )
        ''')
        print("- global_info created")
        
        await client.execute('''
            CREATE TABLE IF NOT EXISTS role_containers (
                role TEXT PRIMARY KEY,
                champion_ids_json TEXT,
                patch TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- role_containers created")
        
        await client.execute('''
            INSERT OR IGNORE INTO global_info (id, abilities_patch, abilities_last_updated)
            VALUES ('data', '14.1', CURRENT_TIMESTAMP)
        ''')
        print("- Defaults inserted")

if __name__ == "__main__":
    asyncio.run(init_db())
