"""
Database module — підтримує і SQLite (локально) і PostgreSQL (Render).
Якщо задана змінна DATABASE_URL — використовує PostgreSQL, інакше SQLite.
"""

import os
import sqlite3
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")  # Render сам задає це для Postgres

# ── Вибираємо драйвер ──────────────────────────────────────────────────────
if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    USE_PG = True
else:
    USE_PG = False


class Database:
    def __init__(self, sqlite_path: str = "/tmp/bot_data.db"):
        self.sqlite_path = sqlite_path
        self._init()

    # ── З'єднання ─────────────────────────────────────────────────────────

    def _conn(self):
        if USE_PG:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        else:
            conn = sqlite3.connect(self.sqlite_path)
            conn.row_factory = sqlite3.Row
            return conn

    def _q(self, sql: str) -> str:
        """Конвертує ? → %s для psycopg2."""
        if USE_PG:
            return sql.replace("?", "%s")
        return sql

    # ── Ініціалізація схеми ───────────────────────────────────────────────

    def _init(self):
        conn = self._conn()
        try:
            cur = conn.cursor()
            if USE_PG:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        api_key TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS characters (
                        user_id      BIGINT PRIMARY KEY,
                        name         TEXT NOT NULL,
                        appearance   TEXT NOT NULL,
                        personality  TEXT NOT NULL,
                        speech_style TEXT NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id      SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        role    TEXT NOT NULL,
                        content TEXT NOT NULL,
                        ts      BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_history_user
                        ON history(user_id, ts)
                """)
            else:
                cur.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        api_key TEXT
                    );
                    CREATE TABLE IF NOT EXISTS characters (
                        user_id      INTEGER PRIMARY KEY,
                        name         TEXT NOT NULL,
                        appearance   TEXT NOT NULL,
                        personality  TEXT NOT NULL,
                        speech_style TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS history (
                        id      INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        role    TEXT NOT NULL,
                        content TEXT NOT NULL,
                        ts      INTEGER DEFAULT (strftime('%s','now'))
                    );
                    CREATE INDEX IF NOT EXISTS idx_history_user
                        ON history(user_id, ts);
                """)
            conn.commit()
        finally:
            conn.close()

    # ── Користувачі ───────────────────────────────────────────────────────

    def ensure_user(self, user_id: int):
        conn = self._conn()
        try:
            cur = conn.cursor()
            if USE_PG:
                cur.execute(
                    "INSERT INTO users(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
                    (user_id,)
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
                    (user_id,)
                )
            conn.commit()
        finally:
            conn.close()

    def set_api_key(self, user_id: int, key: str):
        conn = self._conn()
        try:
            cur = conn.cursor()
            if USE_PG:
                cur.execute(
                    "INSERT INTO users(user_id, api_key) VALUES(%s,%s) "
                    "ON CONFLICT(user_id) DO UPDATE SET api_key=EXCLUDED.api_key",
                    (user_id, key)
                )
            else:
                cur.execute(
                    "INSERT INTO users(user_id, api_key) VALUES(?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET api_key=excluded.api_key",
                    (user_id, key)
                )
            conn.commit()
        finally:
            conn.close()

    def get_api_key(self, user_id: int) -> Optional[str]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(self._q("SELECT api_key FROM users WHERE user_id=?"), (user_id,))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # ── Персонажі ─────────────────────────────────────────────────────────

    def save_character(self, user_id: int, data: dict):
        conn = self._conn()
        try:
            cur = conn.cursor()
            if USE_PG:
                cur.execute(
                    "INSERT INTO characters(user_id,name,appearance,personality,speech_style) "
                    "VALUES(%s,%s,%s,%s,%s) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "name=EXCLUDED.name, appearance=EXCLUDED.appearance, "
                    "personality=EXCLUDED.personality, speech_style=EXCLUDED.speech_style",
                    (user_id, data["name"], data["appearance"],
                     data["personality"], data["speech_style"])
                )
            else:
                cur.execute(
                    "INSERT INTO characters(user_id,name,appearance,personality,speech_style) "
                    "VALUES(?,?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "name=excluded.name, appearance=excluded.appearance, "
                    "personality=excluded.personality, speech_style=excluded.speech_style",
                    (user_id, data["name"], data["appearance"],
                     data["personality"], data["speech_style"])
                )
            conn.commit()
        finally:
            conn.close()

    def get_character(self, user_id: int) -> Optional[dict]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                self._q("SELECT name,appearance,personality,speech_style "
                        "FROM characters WHERE user_id=?"),
                (user_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            if USE_PG:
                return {
                    "name": row[0], "appearance": row[1],
                    "personality": row[2], "speech_style": row[3]
                }
            return dict(row)
        finally:
            conn.close()

    # ── Історія ───────────────────────────────────────────────────────────

    def add_message(self, user_id: int, role: str, content: str):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                self._q("INSERT INTO history(user_id,role,content) VALUES(?,?,?)"),
                (user_id, role, content)
            )
            conn.commit()
        finally:
            conn.close()

    def get_history(self, user_id: int, limit: int = 30) -> list[tuple[str, str]]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                self._q(
                    "SELECT role, content FROM ("
                    "  SELECT role, content, ts FROM history "
                    "  WHERE user_id=? ORDER BY ts DESC LIMIT ?"
                    ") sub ORDER BY ts ASC"
                ),
                (user_id, limit)
            )
            rows = cur.fetchall()
            return [(r[0], r[1]) for r in rows]
        finally:
            conn.close()

    def clear_history(self, user_id: int):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(self._q("DELETE FROM history WHERE user_id=?"), (user_id,))
            conn.commit()
        finally:
            conn.close()
