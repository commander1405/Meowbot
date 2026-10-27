"""
تنظیمات ایونت هالووین — خارج از config.py اصلی پروژه.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

# بازه ایونت (قابل تغییر بدون دست زدن به config.py)
EVENT_START = datetime(2026, 10, 20, 0, 0, 0, tzinfo=TEHRAN)
EVENT_END = datetime(2026, 11, 10, 23, 59, 59, tzinfo=TEHRAN)

# کدو
PUMPKIN_MIN = 2
PUMPKIN_MAX = 5
PUMPKIN_SPAWN_COOLDOWN_SEC = 45 * 60  # حداقل فاصله اسپان در یک گروه
PUMPKIN_EXPIRE_SEC = 20 * 60
PUMPKIN_ITEM_ID = "hw_pumpkin"

# باس
BOSS_MAX_HP = 3000
BOSS_ATTACK_COOLDOWN_SEC = 25
BOSS_BASE_DAMAGE = 40
BOSS_DAMAGE_PER_GYM = 8
BOSS_DAMAGE_PER_PET_LV = 3
BOSS_MAX_DAMAGE = 180
BOSS_FATIGUE_LIMIT_BASE = 4  # حملات قبل از خستگی
BOSS_FATIGUE_RECOVERY_SEC = 15 * 60

# جادوگر / فروش
PUMPKIN_SELL_COINS = 12
CHOCOLATE_SELL_COINS = 8

# گردونه
WHEEL_COOLDOWN_HOURS = 24

# شکلات شبانه
CHOCOLATE_NIGHT_START_HOUR = 18
CHOCOLATE_NIGHT_END_HOUR = 6
CHOCOLATE_CLAIM_COOLDOWN_SEC = 30 * 60
CHOCOLATE_DAILY_CAP = 8
CHOCOLATE_ITEM_ID = "hw_chocolate"

# اسکین‌ها
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


def event_active(now: datetime | None = None) -> bool:
    now = now or datetime.now(TEHRAN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TEHRAN)
    return EVENT_START <= now <= EVENT_END


def event_status_text() -> str:
    now = datetime.now(TEHRAN)
    if now < EVENT_START:
        return "⏳ ایونت هنوز شروع نشده"
    if now > EVENT_END:
        return "🏁 ایونت تمام شده"
    return "🎃 ایونت هالووین فعال است"


def is_chocolate_night(now: datetime | None = None) -> bool:
    now = now or datetime.now(TEHRAN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TEHRAN)
    h = now.hour
    # 18:00–23:59 یا 00:00–05:59
    return h >= CHOCOLATE_NIGHT_START_HOUR or h < CHOCOLATE_NIGHT_END_HOUR
