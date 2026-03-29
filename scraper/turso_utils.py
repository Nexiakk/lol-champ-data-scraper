"""
Turso utilities for the champion scraping system.
Handles libsql connection and data operations cleanly using libsql_experimental.
Includes connection pooling and retry logic for reliability.
"""

import os
import json
import time
import threading
import socket
from typing import Dict, List, Optional, Any
from datetime import datetime
from queue import Queue, Empty
from urllib.parse import urlparse
import libsql_experimental as libsql

from .logging_utils import get_logger

_logger = get_logger(__name__)


def check_turso_connectivity(db_url: str, timeout: int = 5) -> bool:
    """
    Check if Turso database endpoint is reachable.
    
    Args:
        db_url: Turso database URL
        timeout: Connection timeout in seconds
        
    Returns:
        True if reachable, False otherwise
    """
    try:
        # Parse the URL to extract host and port
        parsed = urlparse(db_url)
        host = parsed.hostname
        port = parsed.port or 443  # Default to HTTPS port
        
        if not host:
            _logger.error(f"Could not parse host from URL: {db_url[:50]}...")
            return False
        
        _logger.debug(f"Checking connectivity to {host}:{port}...")
        
        # Try to establish a socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        try:
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                _logger.debug(f"Successfully connected to {host}:{port}")
                return True
            else:
                _logger.warning(f"Could not connect to {host}:{port} (error code: {result})")
                return False
        except socket.timeout:
            _logger.warning(f"Connection to {host}:{port} timed out after {timeout}s")
            sock.close()
            return False
        except Exception as e:
            _logger.warning(f"Connection check failed: {e}")
            sock.close()
            return False
            
    except Exception as e:
        _logger.error(f"Error checking Turso connectivity: {e}")
        return False


class ConnectionPool:
    """
    Thread-safe connection pool for managing Turso/libsql connections.
    Prevents "stream not found" errors by reusing connections.
    """
    
    def __init__(self, db_url: str, auth_token: str, max_size: int = 5, timeout: float = 30.0):
        self.db_url = db_url
        self.auth_token = auth_token
        self.max_size = max_size
        self.timeout = timeout
        
        self._pool: Queue = Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._created_count = 0
        self._active_connections = 0
        
    def _create_connection(self):
        """Create a new database connection with timeout handling"""
        import threading
        
        _logger.info(f"Attempting to create database connection...")
        
        result = {'conn': None, 'error': None, 'completed': False}
        
        def _connect():
            """Inner function to create connection"""
            try:
                _logger.debug(f"Connecting to {self.db_url[:50]}...")
                conn = libsql.connect(self.db_url, auth_token=self.auth_token)
                _logger.debug("Connection established successfully")
                result['conn'] = conn
                result['completed'] = True
            except Exception as e:
                result['error'] = e
                result['completed'] = True
        
        # Start connection in a daemon thread
        thread = threading.Thread(target=_connect, daemon=True)
        thread.start()
        
        # Wait for completion with timeout
        thread.join(timeout=30)
        
        if not result['completed']:
            _logger.error("Connection creation timed out after 30 seconds - Turso may be unreachable")
            raise TimeoutError("Database connection timed out after 30 seconds - check network connectivity to Turso")
        
        if result['error']:
            _logger.error(f"Failed to create database connection: {type(result['error']).__name__}: {result['error']}")
            raise result['error']
        
        with self._lock:
            self._created_count += 1
            self._active_connections += 1
        
        _logger.info(f"Successfully created database connection (total created: {self._created_count})")
        return result['conn']
        
    def get_connection(self):
        """
        Get a connection from the pool.
        Creates a new one if pool is empty and under max_size.
        """
        # First, try to get existing connection from pool
        try:
            conn = self._pool.get_nowait()
            # Validate connection is still usable
            try:
                conn.execute("SELECT 1")
                with self._lock:
                    self._active_connections += 1
                _logger.debug(f"Reused connection from pool (active: {self._active_connections})")
                return conn
            except Exception:
                # Connection is stale, discard it
                _logger.debug("Discarded stale connection, creating new one")
                with self._lock:
                    self._created_count -= 1
                return self._create_connection()
        except Empty:
            pass
        
        # Pool is empty, check if we can create a new connection
        with self._lock:
            if self._created_count < self.max_size:
                _logger.debug(f"Pool empty, creating new connection ({self._created_count}/{self.max_size})")
                return self._create_connection()
        
        # At max connections, wait for one to be returned
        _logger.debug(f"Connection pool at max ({self._created_count}/{self._created_count}), waiting up to {self.timeout}s...")
        try:
            conn = self._pool.get(timeout=self.timeout)
            with self._lock:
                self._active_connections += 1
            _logger.debug("Got connection from pool after waiting")
            return conn
        except Empty:
            # Timeout, create a new one anyway (will be cleaned up later)
            _logger.warning(f"Connection pool timeout after {self.timeout}s, creating temporary connection")
            return self._create_connection()
    
    def release_connection(self, conn):
        """Return a connection to the pool"""
        if conn is None:
            return
            
        with self._lock:
            self._active_connections -= 1
            
        try:
            # Validate connection before returning to pool
            conn.execute("SELECT 1")
            self._pool.put_nowait(conn)
        except Exception:
            # Connection is broken, discard it
            _logger.debug("Discarded broken connection on release")
            with self._lock:
                self._created_count -= 1
    
    def close_all(self):
        """Close all connections in the pool"""
        while True:
            try:
                conn = self._pool.get_nowait()
                try:
                    conn.close()
                except Exception:
                    pass
            except Empty:
                break
        
        with self._lock:
            self._created_count = 0
            self._active_connections = 0
        _logger.debug("Closed all pooled connections")
    
    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics"""
        with self._lock:
            return {
                'pool_size': self._pool.qsize(),
                'created_count': self._created_count,
                'active_connections': self._active_connections,
                'max_size': self.max_size
            }


def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to retry (should be a callable)
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)
    
    Returns:
        Result of the function
        
    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                _logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _logger.error(f"All {max_retries + 1} attempts failed")
    
    raise last_exception

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
    """Manages Turso db connection and operations with connection pooling and retry logic"""
    
    def __init__(self, config: TursoConfig):
        self.config = config
        self._pool: Optional[ConnectionPool] = None
    
    def _get_pool(self) -> ConnectionPool:
        """Get or create connection pool"""
        if self._pool is None:
            if not self.config.db_url or not self.config.auth_token:
                raise ValueError("TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")
            self._pool = ConnectionPool(
                db_url=self.config.db_url,
                auth_token=self.config.auth_token,
                max_size=5,  # Match max_workers in lambda_function.py
                timeout=30.0
            )
        return self._pool

    def _get_conn(self):
        """Get a connection from the pool"""
        pool = self._get_pool()
        return pool.get_connection()
    
    def _release_conn(self, conn):
        """Release a connection back to the pool"""
        if conn and self._pool:
            self._pool.release_connection(conn)

    def initialize(self) -> bool:
        """Validate Turso Connection with network connectivity check"""
        # Check network connectivity before attempting connection
        if not check_turso_connectivity(self.config.db_url):
            _logger.error("Turso database is unreachable - check network connectivity")
            return False
        
        conn = None
        try:
            _logger.info("Network connectivity check passed, attempting database connection...")
            conn = self._get_conn()
            conn.execute("SELECT 1")
            _logger.info("Database connection initialized successfully")
            return True
        except Exception as e:
            _logger.error(f"Turso initialization failed: {e}")
            return False
        finally:
            self._release_conn(conn)

    def get_champion_data(self, champion_key: str) -> Optional[Dict[str, Any]]:
        """Get champion data from Turso with retry logic"""
        def _get_data():
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
                _logger.error(f"Error getting champion data for {champion_key}: {e}")
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_get_data, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to get champion data for {champion_key} after retries: {e}")
            return None

    def store_champion_data(self, champion_key: str, data: Dict[str, Any]) -> bool:
        """Store champion data in Turso with retry logic"""
        def _store_data():
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
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_store_data, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to store champion data for {champion_key} after retries: {e}")
            return False

    def get_role_containers(self) -> Optional[Dict[str, Any]]:
        """Get all role container data with retry logic"""
        def _get_roles():
            conn = None
            try:
                result = {"roles": {}}
                conn = self._get_conn()
                cursor = conn.execute("SELECT role, champion_ids_json, patch FROM role_containers")
                for row in cursor.fetchall():
                    role = row[0]
                    champion_ids = json.loads(row[1]) if row[1] else []
                    result["roles"][role] = champion_ids
                    result["patch"] = row[2]  # just grab the last one
                return result
            except Exception as e:
                _logger.error(f"Error getting role containers: {e}")
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_get_roles, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to get role containers after retries: {e}")
            return None

    def update_role_containers(self, role_data: Dict[str, Any]) -> bool:
        """Update role container data with retry logic"""
        def _update_roles():
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
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_update_roles, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to update role containers after retries: {e}")
            return False

    def get_global_patch_info(self) -> Optional[Dict[str, Any]]:
        """Get global patch metadata with retry logic"""
        def _get_patch_info():
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
                _logger.error(f"Error getting global patch info: {e}")
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_get_patch_info, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to get global patch info after retries: {e}")
            return None

    def update_global_patch_info(self, abilities_patch: Optional[str] = None, patch: Optional[str] = None) -> bool:
        """Update global patch metadata with retry logic"""
        def _update_patch_info():
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
                raise
            finally:
                self._release_conn(conn)
        
        try:
            return retry_with_backoff(_update_patch_info, max_retries=3, base_delay=1.0)
        except Exception as e:
            _logger.error(f"Failed to update global patch info after retries: {e}")
            return False
    
    def close(self):
        """Close all connections in the pool"""
        if self._pool:
            self._pool.close_all()
            self._pool = None
    
    def get_pool_stats(self) -> Dict[str, int]:
        """Get connection pool statistics"""
        if self._pool:
            return self._pool.get_stats()
        return {'pool_size': 0, 'created_count': 0, 'active_connections': 0, 'max_size': 0}


# Global instance for easy imports if needed
_turso_config = TursoConfig.from_environment()
_turso_manager = TursoManager(_turso_config)

def init_turso() -> bool:
    return _turso_manager.initialize()

def get_db() -> TursoManager:
    return _turso_manager
