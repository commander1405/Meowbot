"""
هندلرها و UI هالووین — سازگار با Glass UI / InlineKeyboard بله.
"""
from __future__ import annotations
import logging
import random
import time
from datetime import datetime

from bale import InlineKeyboardMarkup, InlineKeyboardButton

from halloween.event_settings import (
    TEHRAN, event_active, event_status_text, is_chocolate_night,
    PUMPKIN_MIN, PUMPKIN_MAX, PUMPKIN_EXPIRE_SEC, PUMPKIN_SPAWN_COOLDOWN_SEC, PUMPKIN_ITEM_ID,
    BOSS_MAX_HP, BOSS_ATTACK_COOLDOWN_SEC, BOSS_BASE_DAMAGE, BOSS_DAMAGE_PER_GYM,
    BOSS_DAMAGE_PER_PET_LV, BOSS_MAX_DAMAGE, BOSS_FATIGUE_LIMIT_BASE, BOSS_FATIGUE_RECOVERY_SEC,
    PUMPKIN_SELL_COINS, CHOCOLATE_SELL_COINS, WITCH_SHOP, SKIN_CATALOG,
    CHOCOLATE_CLAIM_COOLDOWN_SEC, CHOCOLATE_DAILY_CAP, CHOCOLATE_ITEM_ID,
    SKIN_PUMPKIN, SKIN_GHOST, SKIN_WITCH, SKIN_VAMPIRE,
)
from halloween import db as hwdb
from database.pool import fetchrow, fetch, execute, fetchval
from database.users import get_user, add_meow_coins, spend_meow_coins, get_meow_coins
from database.inventory import add_item, get_inv_item, get_inventory
from database.pets import get_pet

logger = logging.getLogger("meowbot.halloween")


def _kb(rows) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    rn = 1
    for row in rows:
        if not row:
            continue
        for text, data in row:
            kb.add(InlineKeyboardButton(text=str(text), callback_data=str(data)), row=rn)
        rn += 1
    return kb


def halloween_home_kb():
    return _kb([
        [("🧙 جادوگر", "hw:witch"), ("🎡 گردونه", "hw:wheel")],
        [("🍫 شکلات", "hw:choc"), ("🎭 اسکین", "hw:skins")],
        [("📊 آمار", "hw:stats")],
        [("🏠 منوی اصلی", "menu:main")],
    ])


def halloween_menu_text(user_id: int = 0) -> str:
    return (
        "🎃 **هالووین MeowBot**\n"
        "━━━━━━━━━━━━━━\n"
        f"{event_status_text()}\n\n"
        "در گروه: کدوهای جادویی و باس روح ظاهر می‌شوند.\n"
        "در پیوی: جادوگر، گردونه، شکلات شبانه و اسکین.\n"
        "━━━━━━━━━━━━━━"
    )


# ---------- home / status / stats ----------
async def handle_hw_callback(user_id: int, data: str, first_name: str = "", chat_id=None, bot=None, message=None):
    """بازگشت (text, kb) یا str."""
    if not data.startswith("hw:"):
        return None

    action = data.split(":", 1)[1]
    # پس از خاموشی Owner فقط status/home پیام پایان می‌دهد
    if action not in ("status", "home", "menu") and not event_active():
        from utils.keyboards import main_menu_kb
        return "🔇 ایونت هالووین خاموش است.", main_menu_kb(halloween_on=False)

    if action in ("home", "menu"):
        return halloween_menu_text(user_id), halloween_home_kb()

    if action == "status":
        return f"🎃 {event_status_text()}\nمنطقه زمانی: Asia/Tehran", halloween_home_kb()

    if action == "stats":
        u = await hwdb.ensure_hw_user(user_id)
        skin = u.get("active_skin") or "—"
        skin_name = SKIN_CATALOG.get(skin, {}).get("name", skin)
        return (
            f"📊 **آمار هالووین**\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎃 کدوهای جمع‌شده: `{u.get('pumpkins_total', 0)}`\n"
            f"🍫 شکلات: `{u.get('chocolate', 0)}`\n"
            f"⚔️ دمیج باس: `{u.get('boss_damage', 0)}`\n"
            f"🎭 اسکین فعال: {skin_name}\n"
            f"━━━━━━━━━━━━━━"
        ), halloween_home_kb()

    if action == "witch":
        return await _witch_home(user_id)

    if action.startswith("witch_sell_p"):
        return await _sell_pumpkins(user_id)

    if action.startswith("witch_sell_c"):
        return await _sell_chocolate(user_id)

    if action.startswith("witch_buy:"):
        item_id = action.split(":", 1)[1] if ":" in data else ""
        # data is hw:witch_buy:ITEM
        parts = data.split(":")
        item_id = parts[2] if len(parts) > 2 else ""
        return await _witch_buy(user_id, item_id)

    if action == "wheel":
        return await _wheel_spin(user_id)

    if action == "choc":
        return await _chocolate_panel(user_id)

    if action == "choc_claim":
        return await _chocolate_claim(user_id)

    if action == "skins":
        return await _skins_panel(user_id)

    if action.startswith("skin_buy:"):
        parts = data.split(":")
        sid = parts[2] if len(parts) > 2 else ""
        return await _skin_buy(user_id, sid)

    if action.startswith("skin_eq:"):
        parts = data.split(":")
        sid = parts[2] if len(parts) > 2 else ""
        return await _skin_equip(user_id, sid)

    # group actions
    if action.startswith("pick:"):
        try:
            eid = int(data.split(":")[2])
        except Exception:
            return "❌ ایونت نامعتبر.", None
        return await _pick_pumpkin(user_id, eid, first_name, bot=bot, message=message)

    if action.startswith("atk:"):
        try:
            bid = int(data.split(":")[2])
        except Exception:
            return "❌ باس نامعتبر.", None
        return await _boss_attack(user_id, bid, first_name, chat_id=chat_id, bot=bot, message=message)

    return "🎃 بخش هالووین.", halloween_home_kb()


# ---------- witch ----------
async def _witch_home(user_id: int):
    inv = await get_inv_item(user_id, PUMPKIN_ITEM_ID)
    pqty = int((inv or {}).get("quantity") or 0)
    u = await hwdb.ensure_hw_user(user_id)
    choc = int(u.get("chocolate") or 0)
    coins = await get_meow_coins(user_id)
    lines = [
        "🧙 **جادوگر هالووین**",
        "━━━━━━━━━━━━━━",
        f"🪙 موجودی: `{coins}`",
        f"🎃 کدو در اینونتوری: `{pqty}` (فروش هر کدام `{PUMPKIN_SELL_COINS}` سکه)",
        f"🍫 شکلات: `{choc}` (فروش هر کدام `{CHOCOLATE_SELL_COINS}` سکه)",
        "",
        "🛒 فروشگاه:",
    ]
    rows = [
        [("🎃 فروش ۱ کدو", "hw:witch_sell_p"), ("🍫 فروش ۱ شکلات", "hw:witch_sell_c")],
    ]
    for iid, meta in WITCH_SHOP.items():
        lines.append(f"• {meta['name']} — `{meta['price_coins']}` 🪙")
        rows.append([(f"خرید {meta['name']}", f"hw:witch_buy:{iid}")])
    rows.append([("🔙 هالووین", "hw:home")])
    return "\n".join(lines), _kb(rows)


async def _sell_pumpkins(user_id: int):
    inv = await get_inv_item(user_id, PUMPKIN_ITEM_ID)
    if not inv or int(inv.get("quantity") or 0) < 1:
        return await _pair_witch(user_id, "❌ کدو نداری.")
    row = await fetchrow(
        """
        UPDATE inventory SET quantity = quantity - 1
        WHERE user_id=$1 AND item_id=$2 AND quantity >= 1
        RETURNING quantity
        """,
        int(user_id), PUMPKIN_ITEM_ID,
    )
    if not row:
        return await _pair_witch(user_id, "❌ کدو کافی نیست.")
    await add_meow_coins(user_id, PUMPKIN_SELL_COINS)
    return await _pair_witch(user_id, f"✅ ۱ کدو فروختی و `{PUMPKIN_SELL_COINS}` سکه گرفتی.")


async def _pair_witch(user_id, prefix: str):
    text, kb = await _witch_home(user_id)
    return f"{prefix}\n\n{text}", kb


async def _sell_chocolate(user_id: int):
    if not await hwdb.try_spend_chocolate(user_id, 1):
        return await _pair_witch(user_id, "❌ شکلات نداری.")
    await add_meow_coins(user_id, CHOCOLATE_SELL_COINS)
    return await _pair_witch(user_id, f"✅ ۱ شکلات فروختی و `{CHOCOLATE_SELL_COINS}` سکه گرفتی.")


async def _witch_buy(user_id: int, item_id: str):
    meta = WITCH_SHOP.get(item_id)
    if not meta:
        return await _pair_witch(user_id, "❌ آیتم نامعتبر.")
    price = int(meta["price_coins"])
    skin = await hwdb.get_active_skin(user_id)
    if skin == SKIN_WITCH:
        price = max(1, int(price * 0.9))
    from database.pool import get_pool
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                paid = await conn.fetchrow(
                    """
                    UPDATE users SET meow_coins = meow_coins - $2, updated_at = NOW()
                    WHERE user_id = $1 AND meow_coins >= $2
                    RETURNING meow_coins
                    """,
                    int(user_id), int(price),
                )
                if not paid:
                    return await _pair_witch(user_id, f"❌ سکه کافی نیست. قیمت: `{price}`")
                # inventory upsert inside same tx
                existing = await conn.fetchrow(
                    "SELECT quantity FROM inventory WHERE user_id=$1 AND item_id=$2 FOR UPDATE",
                    int(user_id), item_id,
                )
                if existing:
                    await conn.execute(
                        "UPDATE inventory SET quantity = quantity + 1 WHERE user_id=$1 AND item_id=$2",
                        int(user_id), item_id,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO inventory (user_id, item_id, item_type, quantity, meta)
                        VALUES ($1,$2,$3,1,'{}'::jsonb)
                        ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = inventory.quantity + 1
                        """,
                        int(user_id), item_id, meta.get("type") or "hw",
                    )
    except Exception as e:
        logger.warning("witch_buy failed: %s", e)
        return await _pair_witch(user_id, "❌ خطا در خرید.")
    return await _pair_witch(user_id, f"✅ خریدی: {meta['name']} (−{price} 🪙)")


# ---------- wheel ----------
async def _wheel_spin(user_id: int):
    if not event_active():
        return "🏁 ایونت فعال نیست.", halloween_home_kb()
    day = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    if await hwdb.has_claim(user_id, "wheel", day):
        return "🎡 امروز گردونه را زدی. فردا دوباره بیا!", halloween_home_kb()
    # weighted rewards
    pool = [
        ("coins", 25, 0.28),
        ("points", 5, 0.22),
        ("pumpkin", 1, 0.20),
        ("chocolate", 1, 0.18),
        ("potion", 1, 0.08),
        ("box", 1, 0.04),
    ]
    r = random.random()
    acc = 0.0
    choice = pool[0]
    for c in pool:
        acc += c[2]
        if r <= acc:
            choice = c
            break
    kind, amount = choice[0], choice[1]
    ok = await hwdb.claim_once(user_id, "wheel", day, {"kind": kind, "amount": amount})
    if not ok:
        return "🎡 امروز گردونه را زدی.", halloween_home_kb()
    msg = "🎡 **گردونه هالووین**\n"
    if kind == "coins":
        await add_meow_coins(user_id, amount)
        msg += f"بردی: `{amount}` 🪙 سکه"
    elif kind == "points":
        from database.users import add_meow_points
        await add_meow_points(user_id, amount)
        msg += f"بردی: `{amount}` ⭐ امتیاز فصل"
    elif kind == "pumpkin":
        await add_item(user_id, PUMPKIN_ITEM_ID, "hw", amount)
        await hwdb.add_pumpkins_collected(user_id, amount)
        msg += "بردی: 🎃 یک کدو"
    elif kind == "chocolate":
        await hwdb.add_chocolate(user_id, amount)
        msg += "بردی: 🍫 یک شکلات"
    elif kind == "potion":
        await add_item(user_id, "hw_potion_small", "consumable", 1)
        msg += "بردی: 🧪 معجون کوچک"
    else:
        await add_item(user_id, "hw_mystery_box", "box", 1)
        msg += "بردی: 🎁 جعبه مرموز"
    return msg, halloween_home_kb()


# ---------- chocolate ----------
async def _chocolate_panel(user_id: int):
    u = await hwdb.ensure_hw_user(user_id)
    night = is_chocolate_night()
    status = "🟢 الان می‌تونی جمع کنی" if night else "🔴 فقط ۱۸:۰۰ تا ۰۶:۰۰ تهران"
    return (
        f"🍫 **شکلات شبانه**\n"
        f"━━━━━━━━━━━━━━\n"
        f"{status}\n"
        f"موجودی: `{u.get('chocolate', 0)}`\n"
        f"سقف روزانه: `{CHOCOLATE_DAILY_CAP}`\n"
        f"━━━━━━━━━━━━━━"
    ), _kb([
        [("🍫 جمع‌آوری", "hw:choc_claim")],
        [("🔙 هالووین", "hw:home")],
    ])


async def _chocolate_claim(user_id: int):
    if not is_chocolate_night():
        return await _chocolate_panel_msg(user_id, "❌ الان وقت شکلات نیست (۱۸–۰۶ تهران).")
    day = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    # count claims today
    cnt = int(await fetchval(
        "SELECT COUNT(*) FROM halloween_claims WHERE user_id=$1 AND claim_type='choc' AND day_key=$2",
        int(user_id), day,
    ) or 0)
    if cnt >= CHOCOLATE_DAILY_CAP:
        return await _chocolate_panel_msg(user_id, "❌ سقف روزانه شکلات پر شده.")
    u = await hwdb.ensure_hw_user(user_id)
    last = float(u.get("last_choc_at") or 0)
    if time.time() - last < CHOCOLATE_CLAIM_COOLDOWN_SEC:
        wait = int(CHOCOLATE_CLAIM_COOLDOWN_SEC - (time.time() - last))
        return await _chocolate_panel_msg(user_id, f"⏳ {wait} ثانیه صبر کن.")
    key = f"{day}:{cnt}"
    if not await hwdb.claim_once(user_id, "choc", key, {}):
        return await _chocolate_panel_msg(user_id, "⚠️ تکراری.")
    n = 2 if await hwdb.get_active_skin(user_id) == SKIN_VAMPIRE else 1
    total = await hwdb.add_chocolate(user_id, n)
    await execute(
        "UPDATE halloween_user SET last_choc_at=$2 WHERE user_id=$1",
        int(user_id), time.time(),
    )
    return await _chocolate_panel_msg(user_id, f"✅ +{n} شکلات (موجودی `{total}`)")


async def _chocolate_panel_msg(user_id, prefix):
    text, kb = await _chocolate_panel(user_id)
    return f"{prefix}\n\n{text}", kb


# ---------- skins ----------
async def _skins_panel(user_id: int):
    active = await hwdb.get_active_skin(user_id)
    lines = ["🎭 **اسکین گربه هالووین**", "━━━━━━━━━━━━━━"]
    rows = []
    for sid, meta in SKIN_CATALOG.items():
        owned = await get_inv_item(user_id, sid)
        mark = "✅" if active == sid else ("📦" if owned else "🔒")
        lines.append(f"{mark} {meta['name']} — `{meta['price_coins']}` 🪙\n   {meta['desc']}")
        if owned:
            rows.append([(f"پوشیدن {meta['name']}", f"hw:skin_eq:{sid}")])
        else:
            rows.append([(f"خرید {meta['name']}", f"hw:skin_buy:{sid}")])
    rows.append([("🔙 هالووین", "hw:home")])
    return "\n".join(lines), _kb(rows)


async def _skin_buy(user_id: int, skin_id: str):
    meta = SKIN_CATALOG.get(skin_id)
    if not meta:
        return "❌ اسکین نامعتبر.", halloween_home_kb()
    if await get_inv_item(user_id, skin_id):
        return await _skins_msg(user_id, "قبلاً این اسکین را داری.")
    if not await spend_meow_coins(user_id, int(meta["price_coins"])):
        return await _skins_msg(user_id, "❌ سکه کافی نیست.")
    await add_item(user_id, skin_id, "skin", 1, meta={"effect": meta["effect"]})
    return await _skins_msg(user_id, f"✅ خریدی: {meta['name']}")


async def _skin_equip(user_id: int, skin_id: str):
    if skin_id and not await get_inv_item(user_id, skin_id):
        return await _skins_msg(user_id, "❌ این اسکین را نداری.")
    await hwdb.set_skin(user_id, skin_id)
    return await _skins_msg(user_id, "✅ اسکین فعال شد.")


async def _skins_msg(user_id, prefix):
    text, kb = await _skins_panel(user_id)
    return f"{prefix}\n\n{text}", kb


# ---------- pumpkin group ----------
async def spawn_pumpkin_event(bot, chat_id: str) -> bool:
    if not event_active():
        return False
    meta = await fetchrow("SELECT * FROM halloween_group_meta WHERE chat_id=$1", str(chat_id))
    last = float((meta or {}).get("last_pumpkin_at") or 0)
    if time.time() - last < PUMPKIN_SPAWN_COOLDOWN_SEC:
        return False
    total = random.randint(PUMPKIN_MIN, PUMPKIN_MAX)
    row = await fetchrow(
        """
        INSERT INTO halloween_pumpkins (chat_id, total, remaining, expires_at, active)
        VALUES ($1, $2, $2, NOW() + make_interval(secs => $3), TRUE)
        RETURNING id, remaining, total
        """,
        str(chat_id), total, int(PUMPKIN_EXPIRE_SEC),
    )
    await execute(
        """
        INSERT INTO halloween_group_meta (chat_id, last_pumpkin_at) VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE SET last_pumpkin_at = EXCLUDED.last_pumpkin_at
        """,
        str(chat_id), time.time(),
    )
    eid = int(row["id"])
    text = _pumpkin_message(int(row["remaining"]), int(row["total"]), [])
    kb = _kb([[(f"🎃 برداشتن کدو", f"hw:pick:{eid}")]])
    try:
        msg = await bot.send_message(chat_id, text, components=kb)
        mid = str(getattr(msg, "message_id", None) or getattr(msg, "id", "") or "")
        if mid:
            await execute("UPDATE halloween_pumpkins SET message_id=$2 WHERE id=$1", eid, mid)
        return True
    except Exception as e:
        logger.warning("pumpkin spawn send failed: %s", e)
        await execute("UPDATE halloween_pumpkins SET active=FALSE WHERE id=$1", eid)
        return False


def _pumpkin_message(remaining: int, total: int, names: list[str]) -> str:
    hist = "\n".join(f"• {n}" for n in names[-8:]) or "هنوز کسی برنداشته"
    return (
        "🎃 **کدوهای هالووین!**\n"
        "━━━━━━━━━━━━━━\n"
        "کدوهای جادویی در گروه ظاهر شدند!\n"
        f"باقی‌مانده: `{remaining}` / `{total}`\n\n"
        f"جمع‌کنندگان:\n{hist}\n"
        "━━━━━━━━━━━━━━"
    )


async def _pick_pumpkin(user_id: int, event_id: int, first_name: str = "", bot=None, message=None):
    # atomic claim: lock pumpkin + insert claim in one transaction
    from database.pool import get_pool
    pool = await get_pool()
    row = None
    bonus = 1
    async with pool.acquire() as conn:
        async with conn.transaction():
            ev = await conn.fetchrow(
                """
                SELECT * FROM halloween_pumpkins
                WHERE id=$1 AND active=TRUE AND expires_at > NOW()
                FOR UPDATE
                """,
                int(event_id),
            )
            if not ev:
                return "⌛ این کدوها تمام یا منقضی شدند.", None
            exists = await conn.fetchval(
                "SELECT 1 FROM halloween_pumpkin_claims WHERE event_id=$1 AND user_id=$2",
                int(event_id), int(user_id),
            )
            if exists:
                return "⚠️ قبلاً از این دسته کدو برداشتی.", None
            row = await conn.fetchrow(
                """
                UPDATE halloween_pumpkins
                SET remaining = remaining - 1,
                    active = CASE WHEN remaining - 1 <= 0 THEN FALSE ELSE TRUE END
                WHERE id=$1 AND active=TRUE AND remaining > 0 AND expires_at > NOW()
                RETURNING *
                """,
                int(event_id),
            )
            if not row:
                return "⌛ کدوها تمام شدند.", None
            try:
                await conn.execute(
                    "INSERT INTO halloween_pumpkin_claims (event_id, user_id) VALUES ($1,$2)",
                    int(event_id), int(user_id),
                )
            except Exception:
                return "⚠️ قبلاً برداشتی.", None

    if await hwdb.get_active_skin(user_id) == SKIN_PUMPKIN and random.random() < 0.15:
        bonus = 2
    await add_item(user_id, PUMPKIN_ITEM_ID, "hw", bonus)
    await hwdb.add_pumpkins_collected(user_id, bonus)

    claims = await fetch(
        """
        SELECT c.user_id, u.first_name FROM halloween_pumpkin_claims c
        LEFT JOIN users u ON u.user_id = c.user_id
        WHERE c.event_id=$1 ORDER BY c.claimed_at
        """,
        int(event_id),
    )
    names = []
    for c in claims or []:
        n = (c.get("first_name") or str(c.get("user_id")))[:16]
        names.append(n)
    text = _pumpkin_message(int(row["remaining"]), int(row["total"]), names)
    kb = _kb([[("🎃 برداشتن کدو", f"hw:pick:{event_id}")]]) if int(row["remaining"]) > 0 and row.get("active") else None
    # edit original message if possible
    if message is not None:
        try:
            for method_name in ("edit_text", "edit"):
                method = getattr(message, method_name, None)
                if callable(method):
                    try:
                        if kb is not None:
                            await method(text, components=kb)
                        else:
                            await method(text)
                        break
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("pumpkin edit: %s", e)
    return f"✅ کدو برداشتی! (+{bonus})", None


# ---------- boss ----------
async def spawn_boss(bot, chat_id: str, *, update_schedule: bool = True) -> bool:
    """اسپان باس در یک گروه. در صورت موفقیت True.
    update_schedule=False وقتی اسکجولر خودش claim کرده باشد.
    """
    if not event_active():
        return False
    active = await fetchval(
        "SELECT id FROM halloween_boss WHERE chat_id=$1 AND active=TRUE LIMIT 1",
        str(chat_id),
    )
    if active:
        return False
    row = await fetchrow(
        """
        INSERT INTO halloween_boss (chat_id, max_hp, hp, active)
        VALUES ($1, $2, $2, TRUE) RETURNING id, hp, max_hp
        """,
        str(chat_id), int(BOSS_MAX_HP),
    )
    bid = int(row["id"])
    text = _boss_text(int(row["hp"]), int(row["max_hp"]), [])
    kb = _kb([[("⚔️ حمله", f"hw:atk:{bid}")]])
    try:
        msg = await bot.send_message(chat_id, text, components=kb)
        mid = str(getattr(msg, "message_id", None) or getattr(msg, "id", "") or "")
        if mid:
            await execute("UPDATE halloween_boss SET message_id=$2 WHERE id=$1", bid, mid)
        if update_schedule:
            try:
                from halloween.scheduler import mark_boss_spawned
                await mark_boss_spawned(str(chat_id))
            except Exception as se:
                logger.debug("mark schedule: %s", se)
        return True
    except Exception as e:
        logger.warning("boss spawn: %s", e)
        await execute("UPDATE halloween_boss SET active=FALSE WHERE id=$1", bid)
        return False


def _bar(hp: int, max_hp: int, width: int = 12) -> str:
    if max_hp <= 0:
        return "░" * width
    filled = max(0, min(width, int(round(width * hp / max_hp))))
    return "█" * filled + "░" * (width - filled)


def _boss_text(hp: int, max_hp: int, recent: list[str]) -> str:
    pct = int(100 * hp / max_hp) if max_hp else 0
    hist = "\n".join(recent[-5:]) or "—"
    return (
        "👻 **روح به گربه‌ها حمله کرده!**\n"
        "━━━━━━━━━━━━━━\n"
        f"❤️ HP: `{hp}` / `{max_hp}`\n"
        f"سلامت: `{pct}%`\n"
        f"[{_bar(hp, max_hp)}]\n\n"
        f"حملات اخیر:\n{hist}\n"
        "━━━━━━━━━━━━━━"
    )


async def _boss_attack(user_id: int, boss_id: int, first_name: str = "", chat_id=None, bot=None, message=None):
    boss = await fetchrow("SELECT * FROM halloween_boss WHERE id=$1 AND active=TRUE", int(boss_id))
    if not boss:
        return "🏁 این باس تمام شده.", None

    # fatigue
    chat = str(boss.get("chat_id") or chat_id or "")
    fat = await fetchrow(
        "SELECT * FROM halloween_boss_fatigue WHERE user_id=$1 AND chat_id=$2",
        int(user_id), chat,
    )
    now = time.time()
    attacks = int((fat or {}).get("attacks") or 0)
    recover_at = float((fat or {}).get("recover_at") or 0)
    limit = BOSS_FATIGUE_LIMIT_BASE
    try:
        from database.inventory import find_usable_item, consume_use
        pot, _ = await find_usable_item(user_id, "boss_potion")
        if pot:
            ok_p, _, _ = await consume_use(user_id, pot["item_id"], 1)
            if ok_p:
                limit = BOSS_FATIGUE_LIMIT_BASE + 3
    except Exception:
        pass
    u = await get_user(user_id)
    gym = int((u or {}).get("gym_level") or 1)
    limit += max(0, (gym - 1) // 5)
    if recover_at > now:
        wait_s = max(1, int(recover_at - now))
        return (
            f"😮‍💨 خسته شدی!\nلطفاً {wait_s} ثانیه صبر کنید تا انرژی‌ات برگردد.",
            None,
            True,
        )
    if attacks >= limit:
        rec = now + BOSS_FATIGUE_RECOVERY_SEC
        if await hwdb.get_active_skin(user_id) == SKIN_GHOST:
            rec = now + BOSS_FATIGUE_RECOVERY_SEC * 0.7
        await execute(
            """
            INSERT INTO halloween_boss_fatigue (user_id, chat_id, attacks, recover_at)
            VALUES ($1,$2,0,$3)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET attacks=0, recover_at=$3
            """,
            int(user_id), chat, rec,
        )
        wait_s = max(1, int(rec - now))
        return (
            f"😮‍💨 به لیمیت حمله رسیدی!\nلطفاً {wait_s} ثانیه صبر کنید و دوباره تلاش کنید.",
            None,
            True,
        )

    pet = await get_pet(user_id)
    pet_lv = int((pet or {}).get("level") or 1) if pet and not pet.get("awaiting_name") else 1
    dmg = BOSS_BASE_DAMAGE + gym * BOSS_DAMAGE_PER_GYM + pet_lv * BOSS_DAMAGE_PER_PET_LV
    dmg = min(BOSS_MAX_DAMAGE, max(10, dmg + random.randint(-8, 12)))
    # شمشیر روح: دابل دمیج (مصرف ۱ استفاده)
    try:
        from database.inventory import find_usable_item, consume_use
        sword, smeta = await find_usable_item(user_id, "boss_sword")
        if sword:
            ok_s, _, _ = await consume_use(user_id, sword["item_id"], 1)
            if ok_s:
                dmg = min(BOSS_MAX_DAMAGE * 2, dmg * 2)
    except Exception:
        pass

    row = await fetchrow(
        """
        UPDATE halloween_boss
        SET hp = GREATEST(0, hp - $2),
            active = CASE WHEN hp - $2 <= 0 THEN FALSE ELSE TRUE END,
            finished_by = CASE WHEN hp - $2 <= 0 AND finished_by IS NULL THEN $3 ELSE finished_by END,
            finished_at = CASE WHEN hp - $2 <= 0 THEN NOW() ELSE finished_at END
        WHERE id=$1 AND active=TRUE AND hp > 0
        RETURNING *
        """,
        int(boss_id), int(dmg), int(user_id),
    )
    if not row:
        return "🏁 باس دیگر فعال نیست.", None

    await execute(
        "INSERT INTO halloween_boss_hits (boss_id, user_id, damage) VALUES ($1,$2,$3)",
        int(boss_id), int(user_id), int(dmg),
    )
    await execute(
        """
        INSERT INTO halloween_boss_fatigue (user_id, chat_id, attacks, recover_at)
        VALUES ($1,$2,1,0)
        ON CONFLICT (user_id, chat_id) DO UPDATE SET attacks = halloween_boss_fatigue.attacks + 1
        """,
        int(user_id), chat,
    )
    await execute(
        """
        INSERT INTO halloween_user (user_id, boss_damage) VALUES ($1,$2)
        ON CONFLICT (user_id) DO UPDATE SET boss_damage = halloween_user.boss_damage + $2, updated_at=NOW()
        """,
        int(user_id), int(dmg),
    )

    hits = await fetch(
        """
        SELECT h.damage, u.first_name FROM halloween_boss_hits h
        LEFT JOIN users u ON u.user_id = h.user_id
        WHERE h.boss_id=$1 ORDER BY h.id DESC LIMIT 5
        """,
        int(boss_id),
    )
    recent = []
    for h in hits or []:
        n = (h.get("first_name") or "?")[:12]
        recent.append(f"• {n}: −{h.get('damage')}")

    text = _boss_text(int(row["hp"]), int(row["max_hp"]), list(reversed(recent)))
    finished = int(row["hp"]) <= 0
    kb = None if finished else _kb([[("⚔️ حمله", f"hw:atk:{boss_id}")]])

    if finished:
        await _grant_boss_rewards(boss_id)
        text += "\n\n🏆 **روح شکست خورد!** جوایز توزیع شد."

    if message is not None:
        try:
            for method_name in ("edit_text", "edit"):
                method = getattr(message, method_name, None)
                if callable(method):
                    try:
                        if kb is not None:
                            await method(text, components=kb)
                        else:
                            await method(text)
                        break
                    except Exception:
                        pass
        except Exception:
            pass

    return f"⚔️ −{dmg} دمیج!" + (" 🏆 ضربه نهایی!" if finished and int(row.get("finished_by") or 0) == int(user_id) else ""), None


async def _grant_boss_rewards(boss_id: int):
    """پاداش یک‌بار مصرف با claim_type یکتا."""
    key = f"boss:{boss_id}"
    rows = await fetch(
        """
        SELECT user_id, SUM(damage) AS dmg FROM halloween_boss_hits
        WHERE boss_id=$1 GROUP BY user_id ORDER BY dmg DESC
        """,
        int(boss_id),
    )
    if not rows:
        return
    boss = await fetchrow("SELECT finished_by FROM halloween_boss WHERE id=$1", int(boss_id))
    finisher = int((boss or {}).get("finished_by") or 0)
    for i, r in enumerate(rows):
        uid = int(r["user_id"])
        claim = f"{key}:{uid}"
        if not await hwdb.claim_once(uid, "boss_reward", claim, {"rank": i}):
            continue
        coins = 15
        if i == 0:
            coins += 40
        if i < 3:
            coins += 20
        if uid == finisher:
            coins += 35
        await add_meow_coins(uid, coins)
        if i < 3:
            await add_item(uid, PUMPKIN_ITEM_ID, "hw", 1)
