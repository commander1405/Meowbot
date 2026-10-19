"""
نقطه ورود مستقل MEGA BOT روبیکا.
اجرا: python -m mega_rubika.main
یا:   python mega_rubika/main.py
MeowBot بله را تحت تأثیر قرار نمی‌دهد.
"""
from __future__ import annotations
import asyncio
import logging
import sys
from pathlib import Path

# اجازه import نسبی وقتی مستقیم اجرا می‌شود
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mega_rubika.config import BOT_TOKEN, DATABASE_PATH, LOG_LEVEL, POLL_TIMEOUT, validate
from mega_rubika.api import RubikaAPI
from mega_rubika.database import Database
from mega_rubika.bot import MegaRubikaBot


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # توکن در لاگ نیاید
    logging.getLogger("mega_rubika.api").setLevel(logging.INFO)


async def amain() -> None:
    validate()
    setup_logging()
    log = logging.getLogger("mega_rubika")
    log.info("Starting MEGA BOT Rubika | db=%s", DATABASE_PATH)

    api = RubikaAPI(BOT_TOKEN)
    db = Database(DATABASE_PATH)
    await api.start()
    try:
        await db.connect()
        bot = MegaRubikaBot(api, db)
        await bot.run(POLL_TIMEOUT)
    finally:
        await db.close()
        await api.close()
        log.info("Stopped.")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print("\nMEGA BOT Rubika stopped.")


if __name__ == "__main__":
    main()
