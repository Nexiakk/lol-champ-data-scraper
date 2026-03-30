"""
Turso utilities for the champion scraping system.
Handles libsql connection and data operations cleanly using libsql_experimental.
"""

import os
import json
import time
import random
from typing import Dict, List, Optional, Any
from datetime import datetime
from functools import wraps
import libsql_experimental as libsql

from .logging_utils import get_logger

_logger = get_logger(__name__)


# ============================================================
# Error Categorization
# ============================================================

def categorize_error(error: Exception) -> str:
    """
    Categorize error for better handling.
    
    Returns:
        'connection': Connection/stream errors (retryable)
        'transient': Temporary issues like timeouts or rate limits (retryable)
        'fatal': Unrecoverable errors (not retryable)
    """
    error_str = str(error).lower()
    
    # Connection-related errors (retryable)
    connection_patterns = [
        'stream not found',
        'connection',
        'econnreset',
        'econnrefused',
        'broken pipe',
        'network',
        'socket',
    ]
    if any(pattern in error_str for pattern in connection_patterns):
        return 'connection'
    
    # Transient errors (retryable)
    transient_patterns = [
        'timeout',
        '429',  # Rate limited
        '503',  # Service unavailable
        '502',  # Bad gateway
        'busy',
        'locked',
    ]
    if any(pattern in error_str for pattern in transient_patterns):
        return 'transient'
    
    # Default to fatal (not retryable)
    return 'fatal'


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is worth retrying"""
    category = categorize_error(error)
    return category in ('connection', 'transient')


# ============================================================
# Enhanced Retry Decorator
# ============================================================

def retry_on_stream_error(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    jitter_factor: float = 0.5
):
    """
    Enhanced retry decorator with exponential backoff and jitter.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)
        max_delay: Maximum delay cap in seconds
        jitter_factor: Random variance factor (0.5 = ±50%)
    
    Delay progression example (base_delay=1.0):
        Attempt 1: ~1s (±50%)
        Attempt 2: ~2s (±50%)
        Attempt 3: ~4s (±50%)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    last_error = e
                    error_category = categorize_error(e)
                    
                    # Don't retry fatal errors
                    if error_category == 'fatal':
                        _logger.error(f"Fatal error in {func.__name__}: {e}")
                        raise
                    
                    # Check if we have retries left
                    if attempt >= max_retries - 1:
                        _logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}: {e}"
                        )
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = base_delay * (2 ** attempt)
                    delay = min(delay, max_delay)
                    
                    # Add jitter (±jitter_factor)
                    jitter = delay * jitter_factor
                    delay = delay + random.uniform(-jitter, jitter)
                    delay = max(0.1, delay)  # Ensure minimum delay
                    
                    # Log the retry
                    _logger.warning(
                        f"{error_category.upper()} error in {func.__name__}, "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            if last_error:
                raise last_error
                
        return wrapper
    return decorator


# ============================================================
# Configuration
# ============================================================

class TursoConfig:
    """Configuration for Turso connection and retry behavior"""
    
    def __init__(
        self,
        db_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        jitter_factor: Optional[float] = None
    ):
        # Connection settings
        self.db_url = db_url or os.environ.get('TURSO_DB_URL')
        self.auth_token = auth_token or os.environ.get('TURSO_AUTH_TOKEN')
        
        # Retry settings (with defaults)
        self.max_retries = max_retries or int(os.environ.get('TURSO_MAX_RETRIES', '3'))
        self.base_delay = base_delay or float(os.environ.get('TURSO_BASE_DELAY', '1.0'))
        self.max_delay = max_delay or float(os.environ.get('TURSO_MAX_DELAY', '10.0'))
        self.jitter_factor = jitter_factor or float(os.environ.get('TURSO_JITTER_FACTOR', '0.5'))

    @classmethod
    def from_environment(cls) -> 'TursoConfig':
        """Create config from environment variables"""
        return cls()


# ============================================================
# Turso Manager
# ============================================================

class TursoManager:
    """Manages Turso db connection and operations"""
    
    def __init__(self, config: TursoConfig):
        self.config = config
        self._connection_stats = {
            'total_connections': 0,
            'total_operations': 0,
            'total_retries': 0,
            'errors_by_category': {'connection': 0, 'transient': 0, 'fatal': 0}
        }

    def _get_conn(self):
        """Creates a new libsql connection"""
        if not self.config.db_url or not self.config.auth_token:
            raise ValueError("TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")
        
        self._connection_stats['total_connections'] += 1
        return libsql.connect(self.config.db_url, auth_token=self.config.auth_token)

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics for debugging"""
        return self._connection_stats.copy()

    def reset_stats(self):
        """Reset connection statistics"""
        self._connection_stats = {
            'total_connections': 0,
            'total_operations': 0,
            'total_retries': 0,
            'errors_by_category': {'connection': 0, 'transient': 0, 'fatal': 0}
        }

    def initialize(self) -> bool:
        """Validate Turso Connection"""
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            conn.close()
            _logger.info("Turso connection initialized successfully")
            return True
        except Exception as e:
            _logger.error(f"Turso initialization failed: {e}")
            return False

    def _create_retry_decorator(self):
        """Create retry decorator with current config settings"""
        return retry_on_stream_error(
            max_retries=self.config.max_retries,
            base_delay=self.config.base_delay,
            max_delay=self.config.max_delay,
            jitter_factor=self.config.jitter_factor
        )

    def get_champion_data(self, champion_key: str) -> Optional[Dict[str, Any]]:
        """Get champion data from Turso"""
        @self._create_retry_decorator()
        def _execute():
            self._connection_stats['total_operations'] += 1
            conn = None
            try:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT id, name, patch, abilities_patch, roles_json, abilities_json FROM champions WHERE id = ?",
                    (champion_key,)
                )
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
                category = categorize_error(e)
                self._connection_stats['errors_by_category'][category] += 1
                _logger.error(f"Error getting champion data for {champion_key}: {e}")
                raise
            finally:
                if conn:
                    conn.close()
        
        return _execute()

    def store_champion_data(self, champion_key: str, data: Dict[str, Any]) -> bool:
        """Store champion data in Turso"""
        @self._create_retry_decorator()
        def _execute():
            self._connection_stats['total_operations'] += 1
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
                category = categorize_error(e)
                self._connection_stats['errors_by_category'][category] += 1
                _logger.error(f"Error storing champion data for {champion_key}: {e}")
                raise
            finally:
                if conn:
                    conn.close()
        
        return _execute()

    def get_role_containers(self) -> Optional[Dict[str, Any]]:
        """Get all role container data"""
        self._connection_stats['total_operations'] += 1
        conn = None
        try:
            result = {"roles": {}}
            conn = self._get_conn()
            cursor = conn.execute("SELECT role, champion_ids_json, patch FROM role_containers")
            for row in cursor.fetchall():
                role = row[0]
                champion_ids = json.loads(row[1]) if row[1] else []
                result["roles"][role] = champion_ids
                result["patch"] = row[2]
            return result
        except Exception as e:
            category = categorize_error(e)
            self._connection_stats['errors_by_category'][category] += 1
            _logger.error(f"Error getting role containers: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_role_containers(self, role_data: Dict[str, Any]) -> bool:
        """Update role container data"""
        self._connection_stats['total_operations'] += 1
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
            category = categorize_error(e)
            self._connection_stats['errors_by_category'][category] += 1
            _logger.error(f"Error updating role containers: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_global_patch_info(self) -> Optional[Dict[str, Any]]:
        """Get global patch metadata"""
        self._connection_stats['total_operations'] += 1
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT patch, patch_last_updated, abilities_patch, abilities_last_updated FROM global_info WHERE id = 'data'"
            )
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
            category = categorize_error(e)
            self._connection_stats['errors_by_category'][category] += 1
            _logger.error(f"Error getting global patch info: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_global_patch_info(self, abilities_patch: Optional[str] = None, patch: Optional[str] = None) -> bool:
        """Update global patch metadata"""
        self._connection_stats['total_operations'] += 1
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
            category = categorize_error(e)
            self._connection_stats['errors_by_category'][category] += 1
            _logger.error(f"Error updating global patch info: {e}")
            return False
        finally:
            if conn:
                conn.close()


# ============================================================
# Global Instance
# ============================================================

_turso_config = TursoConfig.from_environment()
_turso_manager = TursoManager(_turso_config)

def init_turso() -> bool:
    """Initialize Turso connection"""
    return _turso_manager.initialize()

def get_db() -> TursoManager:
    """Get the global TursoManager instance"""
    return _turso_manager

def get_turso_stats() -> Dict[str, Any]:
    """Get Turso connection statistics"""
    return _turso_manager.get_stats()