"""
تنظیمات ایونت هالووین — خارج از config.py اصلی پروژه.
وضعیت فعال/غیرفعال توسط Owner در DB (bot_settings) ذخیره می‌شود.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

EVENT_START = datetime(2026, 10, 20, 0, 0, 0, tzinfo=TEHRAN)
EVENT_END = datetime(2026, 11, 10, 23, 59, 59, tzinfo=TEHRAN)

SETTING_KEY = "halloween_enabled"
_flag_cache: bool | None = None

PUMPKIN_MIN = 2
PUMPKIN_MAX = 5
PUMPKIN_SPAWN_COOLDOWN_SEC = 45 * 60
PUMPKIN_EXPIRE_SEC = 20 * 60
PUMPKIN_ITEM_ID = "hw_pumpkin"

BOSS_MAX_HP = 3000
BOSS_ATTACK_COOLDOWN_SEC = 25
BOSS_BASE_DAMAGE = 40
BOSS_DAMAGE_PER_GYM = 8
BOSS_DAMAGE_PER_PET_LV = 3
BOSS_MAX_DAMAGE = 180
BOSS_FATIGUE_LIMIT_BASE = 4
BOSS_FATIGUE_RECOVERY_SEC = 15 * 60
BOSS_EXPIRE_SEC = 2 * 3600  # باس بعد از ۲ ساعت باطل می‌شود

PUMPKIN_SELL_COINS = 12
CHOCOLATE_SELL_COINS = 8
WHEEL_COOLDOWN_HOURS = 24

CHOCOLATE_NIGHT_START_HOUR = 18
CHOCOLATE_NIGHT_END_HOUR = 6
CHOCOLATE_CLAIM_COOLDOWN_SEC = 30 * 60
CHOCOLATE_DAILY_CAP = 8
CHOCOLATE_ITEM_ID = "hw_chocolate"

SKIN_PUMPKIN = "skin_pumpkin_cat"
SKIN_GHOST = "skin_ghost_cat"
SKIN_WITCH = "skin_witch_cat"
SKIN_VAMPIRE = "skin_vampire_cat"

SKIN_CATALOG = {
    SKIN_PUMPKIN: {
        "name": "🎃 گربه کدو",
        "desc": "شانس کمی بیشتر برای جمع‌کردن کدو",
        "price_coins": 180,
        "effect": "pumpkin_bonus",
    },
    SKIN_GHOST: {
        "name": "👻 گربه روح",
        "desc": "کاهش زمان ریکاوری خستگی باس",
        "price_coins": 220,
        "effect": "fatigue_reduce",
    },
    SKIN_WITCH: {
        "name": "🧙 گربه جادوگر",
        "desc": "تخفیف محدود در فروشگاه جادوگر",
        "price_coins": 250,
        "effect": "witch_discount",
    },
    SKIN_VAMPIRE: {
        "name": "🧛 گربه خون‌آشام",
        "desc": "پاداش شبانه شکلات کمی بیشتر",
        "price_coins": 200,
        "effect": "night_bonus",
    },
}

WITCH_SHOP = {
    "hw_potion_small": {"name": "🧪 معجون کوچک", "price_coins": 40, "type": "consumable"},
    "hw_mystery_box": {"name": "🎁 جعبه مرموز", "price_coins": 90, "type": "box"},
    "hw_key": {"name": "🔑 کلید هالووین", "price_coins": 70, "type": "key"},
    "hw_bat_charm": {"name": "🦇 طلسم خفاش", "price_coins": 55, "type": "collectible"},
}


def _in_calendar_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(TEHRAN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TEHRAN)
    return EVENT_START <= now <= EVENT_END


def event_active(now: datetime | None = None) -> bool:
    if not _in_calendar_window(now):
        return False
    if _flag_cache is None:
        return True
    return bool(_flag_cache)


def event_status_text() -> str:
    now = datetime.now(TEHRAN)
    if now < EVENT_START:
        return "⏳ ایونت هنوز شروع نشده"
    if now > EVENT_END:
        return "🏁 ایونت تمام شده"
    if _flag_cache is False:
        return "🔇 ایونت توسط Owner خاموش است"
    return "🎃 ایونت هالووین فعال است"


def is_chocolate_night(now: datetime | None = None) -> bool:
    now = now or datetime.now(TEHRAN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TEHRAN)
    h = now.hour
    return h >= CHOCOLATE_NIGHT_START_HOUR or h < CHOCOLATE_NIGHT_END_HOUR


async def refresh_event_flag() -> bool:
    global _flag_cache
    try:
        from database.settings import get_setting
        raw = await get_setting(SETTING_KEY, None)
        if raw is None or str(raw).strip() == "":
            _flag_cache = _in_calendar_window()
        else:
            _flag_cache = str(raw).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        _flag_cache = _in_calendar_window()
    return bool(_flag_cache)


async def set_event_enabled(enabled: bool) -> bool:
    global _flag_cache
    from database.settings import set_setting
    await set_setting(SETTING_KEY, "1" if enabled else "0")
    _flag_cache = bool(enabled)
    return _flag_cache


def event_flag_cached() -> bool | None:
    return _flag_cache
