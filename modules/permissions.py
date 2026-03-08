import sqlite3
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)
logger.info("🔥 PERMISSIONS DB LOADED")  # Test logger works
class PermissionsDB:
    def __init__(self, db_path: str = "rexy_permissions.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS permissions (
                    user_id TEXT,
                    cap_name TEXT,
                    mode TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (user_id, cap_name)
                )
            """)
            # Phase 5.3: EXPLICIT always permissions for user1
            defaults = [
                ("user1", "get_time", "always"),
                ("user1", "echo", "always"),
                ("user1", "list_files", "always"),      # ← THIS!
                ("user1", "calculate", "always"),
                ("user1", "*", "confirm")               # Fallback
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO permissions (user_id, cap_name, mode, updated_at) 
                VALUES (?, ?, ?, ?)
            """, [(uid, cap, mode, datetime.now().isoformat()) for uid, cap, mode in defaults])
            conn.commit()
            logger.info("🔥 PERMISSIONS DB INITIALIZED")

    def get_permission(self, user_id: str, cap_name: str) -> str:
        with sqlite3.connect(self.db_path) as conn:
            # DEBUG ALL
            all_perms = conn.execute("SELECT * FROM permissions WHERE user_id=?", (user_id,)).fetchall()

            logger.info(f"DEBUG DB DEBUG | user1 perms: {all_perms}")            
            row = conn.execute(
                "SELECT mode FROM permissions WHERE user_id=? AND cap_name=?",
                (user_id, cap_name)
            ).fetchone()
            mode = row[0] if row else "confirm"
            logger.info(f"DEBUG DB PERM | {user_id}:{cap_name} = {mode}")
            return mode

    def list_all(self):
        """Phase 5.8: List ALL permissions for UI"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # FIX: cap_name → capability (your table has cap_name)
            cursor.execute("SELECT user_id, cap_name AS capability, mode, updated_at AS timestamp FROM permissions ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            conn.close()
            logger.info(f"DEBUG DB DEBUG | user1 perms: {rows}")
            return rows
        except Exception as e:
            logger.error(f"DB list_all error: {e}")
            return []

    def set_permission(self, user_id: str, cap_name: str, mode: str):
        """Phase 5.8: LIVE UI permission toggle"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO permissions (user_id, cap_name, mode, updated_at) 
                VALUES (?, ?, ?, ?)
            """, (user_id, cap_name, mode, datetime.now().isoformat()))
            conn.commit()
            logger.info(f"🔐 PERMISSION SET | {user_id}:{cap_name}={mode}")

    def get_capabilities(self) -> list:
        """Get all unique capabilities for UI"""
        with sqlite3.connect(self.db_path) as conn:
            caps = conn.execute("SELECT DISTINCT cap_name FROM permissions").fetchall()
            return [cap[0] for cap in caps]

permissions_db = PermissionsDB()
