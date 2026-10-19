"""
SQLite database for MEGA BOT Rubika — کاملاً جدا از MeowBot و نسخه بله.
"""
from __future__ import annotations
import aiosqlite
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("mega_rubika.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username TEXT DEFAULT '',
  first_name TEXT DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  starts_count INTEGER NOT NULL DEFAULT 1,
  xp INTEGER NOT NULL DEFAULT 0,
  level INTEGER NOT NULL DEFAULT 1,
  nickname TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS groups_seen (
  chat_id TEXT PRIMARY KEY,
  title TEXT DEFAULT '',
  username TEXT DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  messages_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admins (
  user_id TEXT PRIMARY KEY,
  username TEXT DEFAULT '',
  display_name TEXT DEFAULT '',
  permissions TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1,
  added_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  title TEXT DEFAULT '',
  description TEXT DEFAULT '',
  username TEXT DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moderation_cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_code INTEGER UNIQUE NOT NULL,
  target_type TEXT NOT NULL CHECK(target_type IN ('user','group')),
  target_id TEXT NOT NULL,
  target_username TEXT,
  target_name TEXT DEFAULT '',
  reason TEXT NOT NULL,
  duration_days INTEGER,
  permanent INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  action TEXT NOT NULL DEFAULT 'ban',
  issued_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  lifted_by TEXT,
  lifted_at TEXT,
  lift_reason TEXT
);

CREATE INDEX IF NOT EXISTS cases_target_idx ON moderation_cases(target_type, target_id, active);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  details TEXT DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  chat_id TEXT NOT NULL,
  chat_type TEXT NOT NULL,
  event_type TEXT NOT NULL DEFAULT 'message',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocked (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  reason TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(target_type, target_id)
);

CREATE TABLE IF NOT EXISTS user_states (
  user_id TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT '',
  data TEXT DEFAULT '{}',
  updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA foreign_keys=ON;")
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        log.info("SQLite ready: %s", self.path)

    async def close(self) -> None:
        if self.db:
            await self.db.close()
            self.db = None

    async def _exec(self, sql: str, params: tuple = ()) -> None:
        assert self.db
        await self.db.execute(sql, params)
        await self.db.commit()

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        assert self.db
        async with self.db.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list:
        assert self.db
        async with self.db.execute(sql, params) as cur:
            return await cur.fetchall()

    # ---------- users ----------
    async def upsert_user(self, user_id: str, username: str = "", first_name: str = "") -> None:
        now = _now()
        row = await self._fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if row:
            await self._exec(
                "UPDATE users SET username=?, first_name=?, last_seen=?, starts_count=starts_count+1 WHERE user_id=?",
                (username or "", first_name or "", now, user_id),
            )
        else:
            await self._exec(
                "INSERT INTO users (user_id, username, first_name, first_seen, last_seen) VALUES (?,?,?,?,?)",
                (user_id, username or "", first_name or "", now, now),
            )

    async def get_user(self, user_id: str) -> Optional[dict]:
        row = await self._fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
        return dict(row) if row else None

    async def count_users(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS c FROM users")
        return int(row["c"]) if row else 0

    # ---------- groups ----------
    async def upsert_group(self, chat_id: str, title: str = "", username: str = "") -> None:
        now = _now()
        row = await self._fetchone("SELECT chat_id FROM groups_seen WHERE chat_id=?", (chat_id,))
        if row:
            await self._exec(
                "UPDATE groups_seen SET title=?, username=?, last_seen=?, messages_count=messages_count+1 WHERE chat_id=?",
                (title or "", username or "", now, chat_id),
            )
        else:
            await self._exec(
                "INSERT INTO groups_seen (chat_id, title, username, first_seen, last_seen) VALUES (?,?,?,?,?)",
                (chat_id, title or "", username or "", now, now),
            )

    async def count_groups(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS c FROM groups_seen")
        return int(row["c"]) if row else 0

    # ---------- settings ----------
    async def get_setting(self, key: str, default: Any = None) -> Any:
        row = await self._fetchone("SELECT value FROM settings WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    async def set_setting(self, key: str, value: Any, updated_by: str | None = None) -> None:
        now = _now()
        val = json.dumps(value, ensure_ascii=False)
        await self._exec(
            "INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (key, val, updated_by, now),
        )

    # ---------- moderation (بن داخلی) ----------
    async def next_case_code(self) -> int:
        row = await self._fetchone("SELECT MAX(case_code) AS m FROM moderation_cases")
        m = int(row["m"] or 999) if row else 999
        code = m + 1
        if code > 9999:
            raise RuntimeError("ظرفیت کد پرونده پر شده (۱۰۰۰–۹۹۹۹)")
        return max(code, 1000)

    async def create_case(
        self,
        target_type: str,
        target_id: str,
        reason: str,
        issued_by: str,
        *,
        permanent: bool = False,
        duration_days: int | None = None,
        target_name: str = "",
        target_username: str = "",
        action: str = "ban",
    ) -> int:
        code = await self.next_case_code()
        now = _now()
        expires = None
        if not permanent and duration_days:
            from datetime import timedelta
            expires = (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat()
        await self._exec(
            """INSERT INTO moderation_cases
            (case_code, target_type, target_id, target_username, target_name, reason,
             duration_days, permanent, active, action, issued_by, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?)""",
            (
                code, target_type, target_id, target_username, target_name, reason,
                duration_days, 1 if permanent else 0, action, issued_by, now, expires,
            ),
        )
        return code

    async def is_banned(self, target_type: str, target_id: str) -> bool:
        row = await self._fetchone(
            """SELECT id FROM moderation_cases
               WHERE target_type=? AND target_id=? AND active=1
               AND (permanent=1 OR expires_at IS NULL OR expires_at > ?)""",
            (target_type, target_id, _now()),
        )
        return row is not None

    async def lift_case(self, case_code: int, lifted_by: str, reason: str = "") -> bool:
        row = await self._fetchone(
            "SELECT id FROM moderation_cases WHERE case_code=? AND active=1", (case_code,)
        )
        if not row:
            return False
        await self._exec(
            "UPDATE moderation_cases SET active=0, lifted_by=?, lifted_at=?, lift_reason=? WHERE case_code=?",
            (lifted_by, _now(), reason, case_code),
        )
        return True

    async def get_case(self, case_code: int) -> Optional[dict]:
        row = await self._fetchone("SELECT * FROM moderation_cases WHERE case_code=?", (case_code,))
        return dict(row) if row else None

    # ---------- audit ----------
    async def log_action(
        self,
        actor_id: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        await self._exec(
            "INSERT INTO audit_logs (actor_id, action, target_type, target_id, details, created_at) VALUES (?,?,?,?,?,?)",
            (actor_id, action, target_type, target_id, json.dumps(details or {}, ensure_ascii=False), _now()),
        )

    # ---------- usage ----------
    async def track_event(self, chat_id: str, chat_type: str, user_id: str | None = None, event_type: str = "message") -> None:
        await self._exec(
            "INSERT INTO usage_events (user_id, chat_id, chat_type, event_type, created_at) VALUES (?,?,?,?,?)",
            (user_id, chat_id, chat_type, event_type, _now()),
        )

    # ---------- state (برای منوهای چندمرحله‌ای) ----------
    async def set_state(self, user_id: str, state: str, data: dict | None = None) -> None:
        await self._exec(
            "INSERT INTO user_states (user_id, state, data, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, data=excluded.data, updated_at=excluded.updated_at",
            (user_id, state, json.dumps(data or {}, ensure_ascii=False), _now()),
        )

    async def get_state(self, user_id: str) -> tuple[str, dict]:
        row = await self._fetchone("SELECT state, data FROM user_states WHERE user_id=?", (user_id,))
        if not row:
            return "", {}
        try:
            return row["state"] or "", json.loads(row["data"] or "{}")
        except Exception:
            return row["state"] or "", {}

    async def clear_state(self, user_id: str) -> None:
        await self._exec("DELETE FROM user_states WHERE user_id=?", (user_id,))

    # ---------- team ----------
    async def list_team(self) -> list[dict]:
        rows = await self._fetchall("SELECT * FROM team_members ORDER BY sort_order, id")
        return [dict(r) for r in rows]

    async def add_team_member(self, name: str, title: str = "", description: str = "", username: str = "") -> int:
        await self._exec(
            "INSERT INTO team_members (name, title, description, username, created_at) VALUES (?,?,?,?,?)",
            (name, title, description, username, _now()),
        )
        row = await self._fetchone("SELECT last_insert_rowid() AS id")
        return int(row["id"]) if row else 0
