"""
Turso utilities for the champion scraping system.
Handles libsql connection and data operations cleanly.
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import libsql_client

class TursoConfig:
    """Configuration for Turso connection"""
    def __init__(self, db_url: Optional[str] = None, auth_token: Optional[str] = None):
        self.db_url = db_url or os.environ.get('TURSO_DB_URL')
        self.auth_token = auth_token or os.environ.get('TURSO_AUTH_TOKEN')
        
        # Avoid websocket issues in some environments
        if self.db_url and self.db_url.startswith("libsql://"):
            self.db_url = self.db_url.replace("libsql://", "https://", 1)

    @classmethod
    def from_environment(cls) -> 'TursoConfig':
        """Create config from environment variables"""
        return cls()

class TursoManager:
    """Manages Turso db connection and operations"""
    
    def __init__(self, config: TursoConfig):
        self.config = config

    def _get_client(self):
        """Creates a new libsql client context manager (sync)"""
        if not self.config.db_url or not self.config.auth_token:
            raise ValueError("TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")
        return libsql_client.create_client_sync(self.config.db_url, auth_token=self.config.auth_token)

    def initialize(self) -> bool:
        """Validate Turso Connection"""
        try:
            with self._get_client():
                return True
        except Exception as e:
            print(f"Turso initialization failed: {e}")
            return False

    def get_champion_data(self, champion_key: str) -> Optional[Dict[str, Any]]:
        """Get champion data from Turso"""
        try:
            with self._get_client() as client:
                rs = client.execute("SELECT * FROM champions WHERE id = ?", [champion_key])
                if not rs.rows:
                    return None
                    
                row = rs.rows[0]
                
                # Parse JSON fields
                roles = json.loads(row[4]) if row[4] else {}
                abilities = json.loads(row[5]) if row[5] else []
                
                return {
                    "id": row[0],
                    "name": row[1],
                    "imageName": row[2],
                    "patch": row[3],
                    "roles": roles,
                    "abilities": abilities
                }
        except Exception as e:
            print(f"Error getting champion data for {champion_key}: {e}")
            return None

    def store_champion_data(self, champion_key: str, data: Dict[str, Any]) -> bool:
        """Store champion data in Turso"""
        try:
            with self._get_client() as client:
                name = data.get("name", champion_key)
                image_name = data.get("imageName", "")
                patch = data.get("patch", "")
                roles_json = json.dumps(data.get("roles", {}))
                abilities_json = json.dumps(data.get("abilities", []))
                
                client.execute('''
                    INSERT INTO champions (id, name, image_name, patch, roles_json, abilities_json) 
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET 
                        name = excluded.name,
                        image_name = excluded.image_name,
                        patch = excluded.patch,
                        roles_json = excluded.roles_json,
                        abilities_json = excluded.abilities_json,
                        last_updated = CURRENT_TIMESTAMP
                ''', [champion_key, name, image_name, patch, roles_json, abilities_json])
                
            return True
        except Exception as e:
            print(f"Error storing champion data for {champion_key}: {e}")
            return False

    def get_role_containers(self) -> Optional[Dict[str, Any]]:
        """Get all role container data"""
        try:
            result = {"roles": {}}
            with self._get_client() as client:
                rs = client.execute("SELECT role, champion_ids_json, patch FROM role_containers")
                for row in rs.rows:
                    role = row[0]
                    champion_ids = json.loads(row[1]) if row[1] else []
                    result["roles"][role] = champion_ids
                    result["patch"] = row[2] # just grab the last one
            return result
        except Exception as e:
            print(f"Error getting role containers: {e}")
            return None

    def update_role_containers(self, role_data: Dict[str, Any]) -> bool:
        """Update role container data"""
        try:
            roles = role_data.get("roles", {})
            patch = role_data.get("patch", "")
            
            with self._get_client() as client:
                for role, champion_ids in roles.items():
                    champion_ids_json = json.dumps(champion_ids)
                    client.execute('''
                        INSERT INTO role_containers (role, champion_ids_json, patch)
                        VALUES (?, ?, ?)
                        ON CONFLICT(role) DO UPDATE SET
                            champion_ids_json = excluded.champion_ids_json,
                            patch = excluded.patch,
                            last_updated = CURRENT_TIMESTAMP
                    ''', [role, champion_ids_json, patch])
            return True
        except Exception as e:
            print(f"Error updating role containers: {e}")
            return False

    def get_global_patch_info(self) -> Optional[Dict[str, Any]]:
        """Get global patch metadata"""
        try:
            with self._get_client() as client:
                rs = client.execute("SELECT abilities_patch, abilities_last_updated FROM global_info WHERE id = 'data'")
                if rs.rows:
                    row = rs.rows[0]
                    return {
                        'abilitiesPatch': row[0],
                        'abilitiesLastUpdated': row[1]
                    }
            return None
        except Exception as e:
            print(f"Error getting global patch info: {e}")
            return None

    def update_global_patch_info(self, patch: str) -> bool:
        """Update global patch metadata"""
        try:
            with self._get_client() as client:
                 client.execute('''
                    INSERT INTO global_info (id, abilities_patch, abilities_last_updated) 
                    VALUES ('data', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET 
                        abilities_patch = excluded.abilities_patch,
                        abilities_last_updated = CURRENT_TIMESTAMP
                 ''', [patch])
            return True
        except Exception as e:
            print(f"Error updating global patch info: {e}")
            return False

# Global instance for easy imports if needed
_turso_config = TursoConfig.from_environment()
_turso_manager = TursoManager(_turso_config)

def init_turso() -> bool:
    return _turso_manager.initialize()

def get_db() -> TursoManager:
    return _turso_manager
