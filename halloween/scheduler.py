"""
اسکجولر مستقل باس روح برای هر گروه.
هر گروه next_boss_at جدا دارد؛ اسپان یک گروه بقیه را جابه‌جا نمی‌کند.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from halloween.event_settings import event_active, TEHRAN
from database.pool import fetch, fetchrow, execute, fetchval
from database.groups import get_all_groups

logger = logging.getLogger("meowbot.halloween.scheduler")

# پیش‌فرض: هر ۴ ساعت + جیتتر ۰–۶۰ دقیقه
DEFAULT_BOSS_INTERVAL_SEC = 4 * 3600
DEFAULT_BOSS_JITTER_SEC = 60 * 60
CHECK_EVERY_SEC = 90
SETTING_INTERVAL = "halloween_boss_interval_sec"
SETTING_JITTER = "halloween_boss_jitter_sec"

_task = None
_bot_ref = None


async def _interval_sec() -> int:
    try:
        from database.settings import get_setting
        raw = await get_setting(SETTING_INTERVAL, str(DEFAULT_BOSS_INTERVAL_SEC))
        v = int(float(raw or DEFAULT_BOSS_INTERVAL_SEC))
        return max(1800, v)  # حداقل ۳۰ دقیقه
    except Exception:
        return DEFAULT_BOSS_INTERVAL_SEC


async def _jitter_sec() -> int:
    try:
        from database.settings import get_setting
        raw = await get_setting(SETTING_JITTER, str(DEFAULT_BOSS_JITTER_SEC))
        return max(0, int(float(raw or DEFAULT_BOSS_JITTER_SEC)))
    except Exception:
        return DEFAULT_BOSS_JITTER_SEC


def next_boss_timestamp(from_ts: float | None = None, interval: int | None = None, jitter: int | None = None) -> float:
    base = float(from_ts if from_ts is not None else time.time())
    iv = int(interval if interval is not None else DEFAULT_BOSS_INTERVAL_SEC)
    jt = int(jitter if jitter is not None else DEFAULT_BOSS_JITTER_SEC)
    return base + iv + (random.randint(0, jt) if jt > 0 else 0)


async def ensure_group_boss_schedule(chat_id: str) -> None:
    """اگر next_boss_at صفر است، زمان بعدی را ست کن (بدون اسپان فوری)."""
    iv = await _interval_sec()
    jt = await _jitter_sec()
    # stagger اولیه تا همه گروه‌ها همزمان اسپان نشوند
    initial = time.time() + random.randint(120, max(120, iv // 3))
    await execute(
        """
        INSERT INTO halloween_group_meta (chat_id, last_boss_at, next_boss_at)
        VALUES ($1, 0, $2)
        ON CONFLICT (chat_id) DO UPDATE SET
            next_boss_at = CASE
                WHEN halloween_group_meta.next_boss_at IS NULL
                  OR halloween_group_meta.next_boss_at <= 0
                THEN EXCLUDED.next_boss_at
                ELSE halloween_group_meta.next_boss_at
            END
        """,
        str(chat_id), float(initial),
    )


async def mark_boss_spawned(chat_id: str) -> None:
    """بعد از اسپان موفق/دستی: last و next فقط برای همین گروه."""
    iv = await _interval_sec()
    jt = await _jitter_sec()
    now = time.time()
    nxt = next_boss_timestamp(now, iv, jt)
    await execute(
        """
        INSERT INTO halloween_group_meta (chat_id, last_boss_at, next_boss_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (chat_id) DO UPDATE SET
            last_boss_at = EXCLUDED.last_boss_at,
            next_boss_at = EXCLUDED.next_boss_at
        """,
        str(chat_id), float(now), float(nxt),
    )


async def claim_due_group(chat_id: str) -> bool:
    """
    اتمیک: اگر due بود next را جلو ببر و True برگردان.
    جلوگیری از اسپان دوبل هنگام چند worker/restart.
    """
    iv = await _interval_sec()
    jt = await _jitter_sec()
    now = time.time()
    nxt = next_boss_timestamp(now, iv, jt)
    row = await fetchrow(
        """
        UPDATE halloween_group_meta
        SET last_boss_at = $2,
            next_boss_at = $3
        WHERE chat_id = $1
          AND (next_boss_at IS NULL OR next_boss_at <= $2)
        RETURNING chat_id
        """,
        str(chat_id), float(now), float(nxt),
    )
    return row is not None


async def boss_loop(bot):
    logger.info("👻 Halloween boss scheduler started")
    while True:
        try:
            await asyncio.sleep(CHECK_EVERY_SEC)
            if not event_active():
                continue
            groups = await get_all_groups()
            now = time.time()
            for g in groups or []:
                if not event_active():
                    break
                cid = str(g.get("chat_id") or "")
                if not cid:
                    continue
                try:
                    meta = await fetchrow(
                        "SELECT next_boss_at FROM halloween_group_meta WHERE chat_id=$1",
                        cid,
                    )
                    if not meta or float(meta.get("next_boss_at") or 0) <= 0:
                        await ensure_group_boss_schedule(cid)
                        continue
                    if float(meta["next_boss_at"]) > now:
                        continue
                    # active boss?
                    active = await fetchval(
                        "SELECT id FROM halloween_boss WHERE chat_id=$1 AND active=TRUE LIMIT 1",
                        cid,
                    )
                    if active:
                        # فقط next را عقب بینداز بدون اسپان
                        await mark_boss_spawned(cid)
                        continue
                    claimed = await claim_due_group(cid)
                    if not claimed:
                        continue
                    from halloween.handlers import spawn_boss
                    ok = await spawn_boss(bot, cid, update_schedule=False)
                    if not ok:
                        # شکست موقت: کمی بعد دوباره تلاش (next را نزدیک بگذار)
                        await execute(
                            """
                            UPDATE halloween_group_meta
                            SET next_boss_at = $2
                            WHERE chat_id = $1
                            """,
                            cid, float(time.time() + random.randint(300, 900)),
                        )
                    else:
                        logger.info("boss auto-spawned chat=%s", cid)
                except Exception as e:
                    logger.warning("boss schedule group %s: %s", cid, e)
                await asyncio.sleep(0.35)  # pacing
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("boss_loop: %s", e)
            await asyncio.sleep(60)


def start_boss_scheduler(bot):
    global _task, _bot_ref
    _bot_ref = bot
    try:
        loop = asyncio.get_event_loop()
        if _task is None or _task.done():
            _task = loop.create_task(boss_loop(bot))
            logger.info("boss scheduler task created")
    except Exception as e:
        logger.error("start_boss_scheduler: %s", e)
