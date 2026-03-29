"""
Turso utilities for the champion scraping system.
Handles libsql connection and data operations cleanly using libsql_experimental.
"""

import os
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from functools import wraps
import libsql_experimental as libsql

from .logging_utils import get_logger

_logger = get_logger(__name__)


def retry_on_stream_error(max_retries=3):
    """Retry decorator for Turso stream errors"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "stream not found" in str(e) and attempt < max_retries - 1:
                        time.sleep(1 + attempt)  # 1s, 2s, 3s delays
                        continue
                    raise
        return wrapper
    return decorator


class TursoConfig:
    """Configuration for Turso connection"""
    def __init__(self, db_url: Optional[str] = None, auth_token: Optional[str] = None):
        self.db_url = db_url or os.environ.get('TURSO_DB_URL')
        self.auth_token = auth_token or os.environ.get('TURSO_AUTH_TOKEN')

    @classmethod
    def from_environment(cls) -> 'TursoConfig':
        """Create config from environment variables"""
        return cls()

class TursoManager:
    """Manages Turso db connection and operations"""
    
    def __init__(self, config: TursoConfig):
        self.config = config

    def _get_conn(self):
        """Creates a new libsql connection"""
        if not self.config.db_url or not self.config.auth_token:
            raise ValueError("TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")
        return libsql.connect(self.config.db_url, auth_token=self.config.auth_token)

    def initialize(self) -> bool:
        """Validate Turso Connection"""
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            conn.close()
            return True
        except Exception as e:
            _logger.error(f"Turso initialization failed: {e}")
            return False

    @retry_on_stream_error(max_retries=3)
    def get_champion_data(self, champion_key: str) -> Optional[Dict[str, Any]]:
        """Get champion data from Turso"""
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.execute("SELECT id, name, patch, abilities_patch, roles_json, abilities_json FROM champions WHERE id = ?", (champion_key,))
            row = cursor.fetchone()
            if not row:
                return None
                
            # Parse JSON fields
            roles = json.loads(row[4]) if row[4] else {}
            abilities = json.loads(row[5]) if row[5] else []
            
            return {
                "id": row[0],
                "name": row[1],
                "patch": row[2],
                "abilitiesPatch": row[3],
                "roles": roles,
                "abilities": abilities
            }
        except Exception as e:
            _logger.error(f"Error getting champion data for {champion_key}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    @retry_on_stream_error(max_retries=3)
    def store_champion_data(self, champion_key: str, data: Dict[str, Any]) -> bool:
        """Store champion data in Turso"""
        conn = None
        try:
            conn = self._get_conn()
            name = data.get("name", champion_key)
            patch = data.get("patch", "")
            abilities_patch = data.get("abilitiesPatch", "")
            roles_json = json.dumps(data.get("roles", {}))
            abilities_json = json.dumps(data.get("abilities", []))
            
            conn.execute('''
                INSERT INTO champions (id, name, patch, abilities_patch, roles_json, abilities_json) 
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET 
                    name = excluded.name,
                    patch = excluded.patch,
                    abilities_patch = excluded.abilities_patch,
                    roles_json = excluded.roles_json,
                    abilities_json = excluded.abilities_json,
                    last_updated = CURRENT_TIMESTAMP
            ''', (champion_key, name, patch, abilities_patch, roles_json, abilities_json))
            conn.commit()
            return True
        except Exception as e:
            _logger.error(f"Error storing champion data for {champion_key}: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_role_containers(self) -> Optional[Dict[str, Any]]:
        """Get all role container data"""
        conn = None
        try:
            result = {"roles": {}}
            conn = self._get_conn()
            cursor = conn.execute("SELECT role, champion_ids_json, patch FROM role_containers")
            for row in cursor.fetchall():
                role = row[0]
                champion_ids = json.loads(row[1]) if row[1] else []
                result["roles"][role] = champion_ids
                result["patch"] = row[2] # just grab the last one
            return result
        except Exception as e:
            _logger.error(f"Error getting role containers: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_role_containers(self, role_data: Dict[str, Any]) -> bool:
        """Update role container data"""
        conn = None
        try:
            roles = role_data.get("roles", {})
            patch = role_data.get("patch", "")
            
            conn = self._get_conn()
            for role, champion_ids in roles.items():
                champion_ids_json = json.dumps(champion_ids)
                conn.execute('''
                    INSERT INTO role_containers (role, champion_ids_json, patch)
                    VALUES (?, ?, ?)
                    ON CONFLICT(role) DO UPDATE SET
                        champion_ids_json = excluded.champion_ids_json,
                        patch = excluded.patch,
                        last_updated = CURRENT_TIMESTAMP
                ''', (role, champion_ids_json, patch))
            conn.commit()
            return True
        except Exception as e:
            _logger.error(f"Error updating role containers: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_global_patch_info(self) -> Optional[Dict[str, Any]]:
        """Get global patch metadata"""
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.execute("SELECT patch, patch_last_updated, abilities_patch, abilities_last_updated FROM global_info WHERE id = 'data'")
            row = cursor.fetchone()
            if row:
                return {
                    'patch': row[0],
                    'patchLastUpdated': row[1],
                    'abilitiesPatch': row[2],
                    'abilitiesLastUpdated': row[3]
                }
            return None
        except Exception as e:
            _logger.error(f"Error getting global patch info: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_global_patch_info(self, abilities_patch: Optional[str] = None, patch: Optional[str] = None) -> bool:
        """Update global patch metadata"""
        conn = None
        try:
            conn = self._get_conn()
            if abilities_patch and patch:
                conn.execute('''
                    INSERT INTO global_info (id, abilities_patch, abilities_last_updated, patch, patch_last_updated) 
                    VALUES ('data', ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET 
                        abilities_patch = excluded.abilities_patch,
                        abilities_last_updated = CURRENT_TIMESTAMP,
                        patch = excluded.patch,
                        patch_last_updated = CURRENT_TIMESTAMP
                ''', (abilities_patch, patch))
            elif abilities_patch:
                conn.execute('''
                    INSERT INTO global_info (id, abilities_patch, abilities_last_updated) 
                    VALUES ('data', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET 
                        abilities_patch = excluded.abilities_patch,
                        abilities_last_updated = CURRENT_TIMESTAMP
                ''', (abilities_patch,))
            elif patch:
                conn.execute('''
                    INSERT INTO global_info (id, patch, patch_last_updated) 
                    VALUES ('data', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET 
                        patch = excluded.patch,
                        patch_last_updated = CURRENT_TIMESTAMP
                ''', (patch,))
                
            conn.commit()
            return True
        except Exception as e:
            _logger.error(f"Error updating global patch info: {e}")
            return False
        finally:
            if conn:
                conn.close()

# Global instance for easy imports if needed
_turso_config = TursoConfig.from_environment()
_turso_manager = TursoManager(_turso_config)

def init_turso() -> bool:
    return _turso_manager.initialize()

def get_db() -> TursoManager:
    return _turso_manager
