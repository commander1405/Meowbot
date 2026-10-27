
"""اطلاع‌رسانی خواب ۲۲ و بیداری ۷ به وقت تهران."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo

from database.pool import fetch, execute

logger = logging.getLogger("meowbot.pet.night")
TEHRAN = ZoneInfo("Asia/Tehran")
_task = None


async def _notify_loop(bot):
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(TEHRAN)
            today = now.date()
            # sleep notify at 22:00-22:05
            if now.hour == 22 and now.minute < 5:
                rows = await fetch(
                    """
                    SELECT user_id, pet_name FROM pets
                    WHERE awaiting_name = FALSE AND COALESCE(pet_name,'') <> ''
                      AND (night_sleep_notified IS NULL OR night_sleep_notified < $1)
                    LIMIT 80
                    """,
                    today,
                )
                for r in rows or []:
                    try:
                        await bot.send_message(
                            int(r["user_id"]),
                            f"🌙 وقت خوابه...\n**{r['pet_name']}** رفت بخوابه (۲۲ تا ۷ تهران).\n"
                            f"اگه صداش کنی باید تأیید کنی که بیدارش کنی 💤",
                        )
                        await execute(
                            "UPDATE pets SET night_sleep_notified=$2, is_sleeping=TRUE WHERE user_id=$1",
                            int(r["user_id"]), today,
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)
            # wake 7:00-7:05
            if now.hour == 7 and now.minute < 5:
                rows = await fetch(
                    """
                    SELECT user_id, pet_name FROM pets
                    WHERE awaiting_name = FALSE AND COALESCE(pet_name,'') <> ''
                      AND (night_wake_notified IS NULL OR night_wake_notified < $1)
                    LIMIT 80
                    """,
                    today,
                )
                for r in rows or []:
                    try:
                        await bot.send_message(
                            int(r["user_id"]),
                            f"☀️ صبح بخیر!\n**{r['pet_name']}** بیدار شد.\n"
                            f"یه غذای تازه و یه حموم یادت نره 🐱",
                        )
                        await execute(
                            "UPDATE pets SET night_wake_notified=$2, is_sleeping=FALSE, sleep_until=0 WHERE user_id=$1",
                            int(r["user_id"]), today,
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("night loop: %s", e)
            await asyncio.sleep(30)


def start_night_scheduler(bot):
    global _task
    try:
        loop = asyncio.get_event_loop()
        if _task is None or _task.done():
            _task = loop.create_task(_notify_loop(bot))
            logger.info("pet night scheduler started")
    except Exception as e:
        logger.error("start_night_scheduler: %s", e)
