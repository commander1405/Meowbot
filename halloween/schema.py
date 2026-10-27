"""مایگریشن جداول هالووین — سازگار با PostgreSQL فعلی."""
from __future__ import annotations
import logging
from database.pool import get_pool

logger = logging.getLogger("meowbot.halloween")

SQL = """
CREATE TABLE IF NOT EXISTS halloween_pumpkins (
    id              SERIAL PRIMARY KEY,
    chat_id         TEXT NOT NULL,
    message_id      TEXT DEFAULT '',
    total           INTEGER NOT NULL,
    remaining       INTEGER NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hw_pump_chat ON halloween_pumpkins (chat_id, active);

CREATE TABLE IF NOT EXISTS halloween_pumpkin_claims (
    event_id        INTEGER NOT NULL REFERENCES halloween_pumpkins(id) ON DELETE CASCADE,
    user_id         BIGINT NOT NULL,
    claimed_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (event_id, user_id)
);

CREATE TABLE IF NOT EXISTS halloween_boss (
    id              SERIAL PRIMARY KEY,
    chat_id         TEXT NOT NULL,
    message_id      TEXT DEFAULT '',
    max_hp          INTEGER NOT NULL,
    hp              INTEGER NOT NULL,
    active          BOOLEAN DEFAULT TRUE,
    finished_by     BIGINT DEFAULT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_hw_boss_chat ON halloween_boss (chat_id, active);

CREATE TABLE IF NOT EXISTS halloween_boss_hits (
    id              SERIAL PRIMARY KEY,
    boss_id         INTEGER NOT NULL REFERENCES halloween_boss(id) ON DELETE CASCADE,
    user_id         BIGINT NOT NULL,
    damage          INTEGER NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hw_boss_hits ON halloween_boss_hits (boss_id, user_id);

CREATE TABLE IF NOT EXISTS halloween_boss_fatigue (
    user_id         BIGINT NOT NULL,
    chat_id         TEXT NOT NULL,
    attacks         INTEGER DEFAULT 0,
    recover_at      DOUBLE PRECISION DEFAULT 0,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS halloween_claims (
    user_id         BIGINT NOT NULL,
    claim_type      TEXT NOT NULL,
    day_key         TEXT NOT NULL,
    meta            JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, claim_type, day_key)
);

CREATE TABLE IF NOT EXISTS halloween_user (
    user_id         BIGINT PRIMARY KEY,
    pumpkins_total  INTEGER DEFAULT 0,
    chocolate       INTEGER DEFAULT 0,
    boss_damage     INTEGER DEFAULT 0,
    active_skin     TEXT DEFAULT '',
    last_choc_at    DOUBLE PRECISION DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS halloween_group_meta (
    chat_id         TEXT PRIMARY KEY,
    last_pumpkin_at DOUBLE PRECISION DEFAULT 0,
    last_boss_at    DOUBLE PRECISION DEFAULT 0
);
"""


async def ensure_halloween_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SQL)
    logger.info("Halloween schema ready")
