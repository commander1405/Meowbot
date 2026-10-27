# ==========================================
# 🐱 MeowBot - Meow System (Async + Anti-Repetition)
# ==========================================

import random
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import MEOW_COOLDOWN
from database.users import (
    create_user, get_user, update_user, increment_daily_meow,
    add_meow_points, set_last_meow, get_last_meow, get_meow_points,
)
from database.content import pick_unseen_index

TEHRAN = ZoneInfo("Asia/Tehran")

MEOW_WORDS = {
    "میو", "معو", "ماو", "میومیو", "میو میو", "میو‌میو",
    "میــــو", "میــــــو", "میاو", "میاوو", "mew", "meow",
}

# متن‌های متنوع — {name} {gained} {total}
MEOW_RESPONSES = [
    "🎃 میو در مه... {name}!\n✨ +{gained} امتیاز نفرین‌شده\n👻 امتیاز فصل: {total}",
    "👻 روح‌ها میوت رو شنیدن {name}!\n✨ +{gained}\n🕯️ موجودی: {total}",
    "🦇 از دل شب: میو~\n👤 {name}\n🎃 +{gained} امتیاز\n📊 فصل: {total}",
    "🌙 مهتاب و میو\n{name} امتیاز گرفت: +{gained}\n🐾 جمع: {total}",
    "🐈‍⬛ گربه سیاه میو کرد!\n{name} · +{gained}\n🎃 فصل: {total}",
    "🧙 جادوگر تأیید کرد {name}!\n✨ +{gained} امتیاز هالووین\n📊 {total}",
    "🕯 شمع‌ها روشن شد...\nمیوی {name}: +{gained}\n👻 جمع امتیاز: {total}",
    "🎃 کدوها به احترام {name} غلتیدن!\n+{gained} ⭐\nفصل: {total}",
    "💀 میوی ترسناک از {name}!\n+{gained}\n🐾 {total}",
    "🌑 شب هالووین، میو بزن\n{name} · +{gained}\n📊 {total}",
    "👻 بوو~ میو!\n👤 {name}\n🎁 +{gained}\n🎃 Total: {total}",
    "🦇 خفاش‌ها هم میو گفتن\n{name} +{gained}\n🕯️ {total}",
    "🧹 جاروی جادوگر رد شد...\nامتیاز برای {name}: +{gained}\n{total}",
    "🎃 میو میو در تاریکی~\n{name} · +{gained}\n👻 {total}",
    "🐈‍⬛ پیشی نفرین‌شده تأیید شد\n{name} +{gained} ⭐ · {total}",
]



def normalize_text(text):
    if not text:
        return ""
    text = str(text).replace("\u200c", "").replace("\u200d", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def is_meow(text) -> bool:
    normalized = normalize_text(text)
    if normalized in MEOW_WORDS:
        return True
    if re.fullmatch(r"می[ـ\-]*و+", normalized):
        return True
    if normalized in ("mew", "meow"):
        return True
    return False


def is_allowed_group(chat_id, chat_username):
    return chat_id is not None


def format_cooldown(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m > 0:
        return f"{m} دقیقه و {s} ثانیه"
    return f"{s} ثانیه"


async def register_meow(user_id: int, first_name: str = "", username: str = "", chat_id=None):
    now = time.time()
    user = await get_user(user_id)
    if not user:
        await create_user(user_id, first_name=first_name, username=username, chat_id=chat_id)
        user = await get_user(user_id)

    points = 1
    event_note = ""
    try:
        from database.events import apply_xp_bonus
        points, _mult, event_note = await apply_xp_bonus(points)
    except Exception:
        pass

    from database.users import try_claim_meow_atomic
    ok, total, remaining = await try_claim_meow_atomic(
        int(user_id), now, float(MEOW_COOLDOWN), int(points)
    )
    if not ok:
        msgs = [
            f"🎃 هنوز زوده! {format_cooldown(remaining)} تا میوی بعدی در مه 👻\n🕯️ امتیاز فصل: {total}",
            f"🦇 آروم باش، {format_cooldown(remaining)} تا میوی بعدی در تاریکی!\n👻 امتیاز فصل: {total}",
            f"🕯 روح پیشی هنوز بیداره... {format_cooldown(remaining)}\n🎃 امتیاز: {total}",
            f"⏳ Cooldown در مه: {format_cooldown(remaining)}\n🕯️ {total}",
        ]
        return False, random.choice(msgs), 0

    # group points only after successful claim
    if chat_id is not None:
        try:
            from database.group_stats import add_group_points
            await add_group_points(user_id, chat_id, points)
        except Exception:
            pass

    day = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    try:
        await increment_daily_meow(user_id, points, day)
    except Exception:
        pass

    idx = await pick_unseen_index(user_id, "meow_response", len(MEOW_RESPONSES))
    name = first_name or (user.get("first_name") if user else None) or "پیشی"
    msg = MEOW_RESPONSES[idx].format(name=name, gained=points, total=total)
    if event_note:
        msg += f"\n{event_note}"

    try:
        from database.missions import update_mission_progress
        from database.achievements import update_achievement_progress
        u = await get_user(user_id)
        total_meows = int(u.get("total_meows") or 0) if u else 0
        await update_mission_progress(user_id, "meows", 1)
        await update_achievement_progress(user_id, "meows", total_meows)
    except Exception:
        pass

    return True, msg, points
