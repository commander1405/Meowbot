# ==========================================
# Inventory + Shop
# ==========================================

from .pool import fetch, fetchrow, execute, fetchval
import json


async def get_inventory(user_id: int):
    rows = await fetch(
        "SELECT * FROM inventory WHERE user_id = $1 AND quantity > 0 ORDER BY item_type, item_id",
        int(user_id),
    )
    return [dict(r) for r in rows]


async def get_inv_item(user_id: int, item_id: str):
    row = await fetchrow(
        "SELECT * FROM inventory WHERE user_id = $1 AND item_id = $2",
        int(user_id), item_id,
    )
    return dict(row) if row else None


def _meta(row) -> dict:
    if not row:
        return {}
    m = row.get("meta") if isinstance(row, dict) else None
    if m is None:
        return {}
    if isinstance(m, dict):
        return m
    if isinstance(m, str):
        try:
            parsed = json.loads(m)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    try:
        return dict(m)
    except Exception:
        return {}


async def add_item(user_id: int, item_id: str, item_type: str, quantity: int = 1, meta: dict = None):
    """اضافه کردن آیتم. اگر meta.uses_left باشد، روی خرید جدید ست می‌شود / جمع می‌شود."""
    meta = dict(meta or {})
    existing = await get_inv_item(user_id, item_id)
    if existing:
        old_meta = _meta(existing)
        # اگر durability دارد، uses را جمع کن
        if "uses_left" in meta or "uses_left" in old_meta:
            old_uses = int(old_meta.get("uses_left") or 0)
            add_uses = int(meta.get("uses_left") or meta.get("max_uses") or 0)
            if add_uses <= 0 and "max_uses" in meta:
                add_uses = int(meta["max_uses"])
            new_uses = old_uses + add_uses
            max_u = int(meta.get("max_uses") or old_meta.get("max_uses") or new_uses)
            new_meta = {**old_meta, **meta, "uses_left": new_uses, "max_uses": max_u}
            await execute(
                """
                UPDATE inventory SET quantity = quantity + $3, meta = $4::jsonb
                WHERE user_id = $1 AND item_id = $2
                """,
                int(user_id), item_id, int(quantity), json.dumps(new_meta),
            )
            return
        await execute(
            """
            UPDATE inventory SET quantity = quantity + $3
            WHERE user_id = $1 AND item_id = $2
            """,
            int(user_id), item_id, int(quantity),
        )
        return

    # آیتم جدید
    if "max_uses" in meta and "uses_left" not in meta:
        meta["uses_left"] = int(meta["max_uses"])
    await execute(
        """
        INSERT INTO inventory (user_id, item_id, item_type, quantity, meta)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (user_id, item_id) DO UPDATE SET
            quantity = inventory.quantity + EXCLUDED.quantity
        """,
        int(user_id), item_id, item_type, int(quantity), json.dumps(meta),
    )


async def remove_item(user_id: int, item_id: str, quantity: int = 1) -> bool:
    """Atomic remove. Returns False if not enough quantity (no negative stock)."""
    row = await fetchrow(
        """
        UPDATE inventory
        SET quantity = quantity - $3
        WHERE user_id = $1 AND item_id = $2 AND quantity >= $3
        RETURNING quantity
        """,
        int(user_id), item_id, int(quantity),
    )
    if not row:
        return False
    if int(row["quantity"] or 0) <= 0:
        await execute(
            "DELETE FROM inventory WHERE user_id = $1 AND item_id = $2 AND quantity <= 0",
            int(user_id), item_id,
        )
    return True


async def consume_use(user_id: int, item_id: str, amount: int = 1) -> tuple:
    """
    Atomic consume of durable item (uses_left) or quantity-based item.
    Returns (ok, uses_left, message). Effect must only apply when ok=True.
    """
    from .pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM inventory WHERE user_id = $1 AND item_id = $2 FOR UPDATE",
                int(user_id), item_id,
            )
            if not row or int(row.get("quantity") or 0) <= 0:
                return False, 0, "نداری"
            meta = _meta(dict(row))
            uses = meta.get("uses_left")
            if uses is None:
                # quantity-based: decrement one
                q = int(row["quantity"] or 0)
                if q < 1:
                    return False, 0, "نداری"
                if q == 1:
                    await conn.execute(
                        "DELETE FROM inventory WHERE user_id = $1 AND item_id = $2",
                        int(user_id), item_id,
                    )
                    return True, 0, "مصرف شد"
                await conn.execute(
                    "UPDATE inventory SET quantity = quantity - 1 WHERE user_id = $1 AND item_id = $2",
                    int(user_id), item_id,
                )
                return True, 0, "مصرف شد"

            if meta.get("needs_repair"):
                return False, 0, "نیاز به تعمیر"
            uses = int(uses or 0)
            if uses < amount:
                return False, uses, "مصرف باقی‌مانده کافی نیست"
            uses -= amount
            meta["uses_left"] = uses
            if uses <= 0 and meta.get("repairable"):
                meta["uses_left"] = 0
                meta["needs_repair"] = True
                await conn.execute(
                    "UPDATE inventory SET meta = $3::jsonb WHERE user_id = $1 AND item_id = $2",
                    int(user_id), item_id, json.dumps(meta),
                )
                return True, 0, "خراب شد — نیاز به تعمیر"
            if uses <= 0:
                await conn.execute(
                    "DELETE FROM inventory WHERE user_id = $1 AND item_id = $2",
                    int(user_id), item_id,
                )
                return True, 0, "تموم شد"
            await conn.execute(
                "UPDATE inventory SET meta = $3::jsonb WHERE user_id = $1 AND item_id = $2",
                int(user_id), item_id, json.dumps(meta),
            )
            return True, uses, "ok"


async def purchase_shop_item(user_id: int, item_id: str) -> tuple:
    """
    Atomic shop purchase: validate price/stock from DB, charge coins, decrement stock, add inventory.
    Returns (ok, message, item_dict_or_None).
    Never charges without granting; never grants without charging.
    """
    from .pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            item = await conn.fetchrow(
                "SELECT * FROM shop_items WHERE item_id = $1 AND active = TRUE FOR UPDATE",
                item_id,
            )
            if not item:
                return False, "❌ آیتم پیدا نشد.", None
            item = dict(item)
            price = int(item.get("price") or 0)
            stock = int(item.get("stock") if item.get("stock") is not None else -1)

            if stock == 0:
                return False, "❌ این آیتم موجودی ندارد.", None

            # charge coins (row lock user)
            paid = await conn.fetchrow(
                """
                UPDATE users SET meow_coins = meow_coins - $2, updated_at = NOW()
                WHERE user_id = $1 AND meow_coins >= $2
                RETURNING meow_coins
                """,
                int(user_id), price,
            )
            if not paid:
                return False, f"❌ کوین کافی نیست. قیمت: `{price}`", None

            if stock > 0:
                dec = await conn.fetchrow(
                    """
                    UPDATE shop_items SET stock = stock - 1
                    WHERE item_id = $1 AND stock > 0
                    RETURNING stock
                    """,
                    item_id,
                )
                if not dec:
                    # rollback via transaction exit — raise to abort
                    raise RuntimeError("stock_race")

            effect = item.get("effect") or {}
            if isinstance(effect, str):
                try:
                    effect = json.loads(effect)
                except Exception:
                    effect = {}
            effect = dict(effect)
            max_uses = int(effect.get("max_uses") or 1)
            if max_uses < 1:
                max_uses = 1
            effect["max_uses"] = max_uses
            effect["uses_left"] = max_uses
            effect["display_name"] = item.get("name") or item_id
            item_type = item.get("item_type") or "item"

            existing = await conn.fetchrow(
                "SELECT * FROM inventory WHERE user_id = $1 AND item_id = $2 FOR UPDATE",
                int(user_id), item_id,
            )
            if existing:
                old_meta = _meta(dict(existing))
                if "uses_left" in effect or "uses_left" in old_meta:
                    old_uses = int(old_meta.get("uses_left") or 0)
                    add_uses = int(effect.get("uses_left") or max_uses)
                    new_uses = old_uses + add_uses
                    max_u = int(effect.get("max_uses") or old_meta.get("max_uses") or new_uses)
                    new_meta = {**old_meta, **effect, "uses_left": new_uses, "max_uses": max_u}
                    await conn.execute(
                        """
                        UPDATE inventory SET quantity = quantity + 1, meta = $3::jsonb
                        WHERE user_id = $1 AND item_id = $2
                        """,
                        int(user_id), item_id, json.dumps(new_meta),
                    )
                else:
                    await conn.execute(
                        "UPDATE inventory SET quantity = quantity + 1 WHERE user_id = $1 AND item_id = $2",
                        int(user_id), item_id,
                    )
            else:
                await conn.execute(
                    """
                    INSERT INTO inventory (user_id, item_id, item_type, quantity, meta)
                    VALUES ($1, $2, $3, 1, $4::jsonb)
                    ON CONFLICT (user_id, item_id) DO UPDATE SET
                        quantity = inventory.quantity + 1
                    """,
                    int(user_id), item_id, item_type, json.dumps(effect),
                )

            return True, (
                f"✅ **{item.get('name')}** خریدی!\n"
                f"📝 {item.get('description') or ''}\n"
                f"🪙 -{price}\n"
                f"🔋 تعداد استفاده این بسته: `{max_uses}`\n"
                f"📦 برو Pet و استفاده کن!"
            ), item


async def find_usable_item(user_id: int, item_type: str):
    rows = await get_inventory(user_id)
    for r in rows:
        if (r.get("item_type") or "") != item_type:
            continue
        meta = _meta(r)
        if meta.get("needs_repair"):
            continue
        uses = meta.get("uses_left")
        if uses is None or int(uses) > 0:
            return r, meta
    return None, None


async def has_item_type(user_id: int, item_type: str) -> bool:
    item, _ = await find_usable_item(user_id, item_type)
    return item is not None


async def has_item_id(user_id: int, item_id: str) -> bool:
    row = await get_inv_item(user_id, item_id)
    if not row or int(row.get("quantity") or 0) <= 0:
        return False
    meta = _meta(row)
    uses = meta.get("uses_left")
    if uses is None:
        return True
    return int(uses) > 0


# ---------- Shop catalog (Pet-focused) ----------
# max_uses: تعداد استفاده (مثلاً ۲۰)
# effect: اثر روی Pet

PET_SHOP_CATALOG = [
    # غذا — هر خرید = یک وعده (۱ بار مصرف)
    {
        "item_id": "food_kibble",
        "name": "🥣 خوراک خشک",
        "description": "یک وعده ساده. فقط ۱ بار مصرف می‌شود.",
        "price": 12,
        "rarity": "common",
        "item_type": "food",
        "effect": {"hunger": 12, "mood": 1, "max_uses": 1},
    },
    {
        "item_id": "food_fish",
        "name": "🐟 ماهی تازه",
        "description": "یک وعده ماهی. ۱ بار مصرف.",
        "price": 28,
        "rarity": "rare",
        "item_type": "food",
        "effect": {"hunger": 22, "relationship": 2, "mood": 3, "max_uses": 1},
    },
    {
        "item_id": "food_premium",
        "name": "🍣 سوشی ویژه",
        "description": "وعده لوکس یک‌نفره. ۱ بار مصرف.",
        "price": 55,
        "rarity": "epic",
        "item_type": "food",
        "effect": {"hunger": 35, "mood": 6, "relationship": 4, "xp": 6, "max_uses": 1},
    },
    {
        "item_id": "food_steak",
        "name": "🥩 استیک گربه",
        "description": "وعده سنگین. ۱ بار مصرف.",
        "price": 40,
        "rarity": "epic",
        "item_type": "food",
        "effect": {"hunger": 40, "mood": 7, "relationship": 3, "xp": 4, "max_uses": 1},
    },
    # اسباب‌بازی — دوام محدود
    {
        "item_id": "toy_ball",
        "name": "🎾 توپ ساده",
        "description": "حدود ۱۲ بار بازی دوام می‌آورد.",
        "price": 35,
        "rarity": "common",
        "item_type": "toy",
        "effect": {"energy": 6, "mood": 3, "xp": 2, "play_kind": "ball", "max_uses": 12},
    },
    {
        "item_id": "toy_mouse",
        "name": "🐭 موش پارچه‌ای",
        "description": "حدود ۸ بار بازی.",
        "price": 50,
        "rarity": "rare",
        "item_type": "toy",
        "effect": {"energy": 10, "relationship": 4, "mood": 4, "xp": 4, "play_kind": "yarn", "max_uses": 8},
    },
    {
        "item_id": "toy_laser",
        "name": "🔴 لیزر دستی",
        "description": "باتری محدود — ۵ جلسه بازی.",
        "price": 85,
        "rarity": "epic",
        "item_type": "toy",
        "effect": {"energy": 14, "mood": 8, "xp": 7, "play_kind": "laser", "max_uses": 5},
    },
    # جای خواب — دائمی تا خرابی؛ بعد تعمیر
    {
        "item_id": "bed_basic",
        "name": "🛏 تشک ساده",
        "description": "حدود ۳۵ خواب دوام دارد؛ بعد باید تعمیر شود (۲۰ کوین).",
        "price": 80,
        "rarity": "common",
        "item_type": "bed",
        "effect": {"energy": 22, "sleep_bonus_sec": 0, "max_uses": 35, "repairable": True, "repair_cost": 20},
    },
    {
        "item_id": "bed_cozy",
        "name": "🧺 سبد نرم",
        "description": "حدود ۴۰ خواب؛ قابل تعمیر با ۲۵ کوین.",
        "price": 120,
        "rarity": "rare",
        "item_type": "bed",
        "effect": {"energy": 28, "sleep_bonus_sec": 30, "mood": 3, "max_uses": 40, "repairable": True, "repair_cost": 25},
    },
    # هدیه
    {
        "item_id": "gift_ribbon",
        "name": "🎀 روبان",
        "description": "هدیه کوچک. ۱ بار.",
        "price": 30,
        "rarity": "common",
        "item_type": "gift",
        "effect": {"relationship": 8, "mood": 5, "max_uses": 1},
    },
    {
        "item_id": "gift_diamond",
        "name": "💎 نشان ویژه",
        "description": "هدیه لوکس. ۱ بار.",
        "price": 150,
        "rarity": "legendary",
        "item_type": "gift",
        "effect": {"relationship": 18, "mood": 10, "xp": 12, "max_uses": 1},
    },
    # مبارزه با روح
    {
        "item_id": "boss_sword",
        "name": "⚔️ شمشیر روح",
        "description": "هر ضربه به روح ۲ برابر قوی‌تر می‌شود. ۵ استفاده.",
        "price": 120,
        "rarity": "epic",
        "item_type": "boss_sword",
        "effect": {"max_uses": 5, "boss_damage_mult": 2},
    },
    {
        "item_id": "boss_potion",
        "name": "🧪 پوشن خستگی",
        "description": "هر بار حمله، خستگی کمتر می‌شود (+۳ ضربه مجاز). ۴ استفاده.",
        "price": 90,
        "rarity": "rare",
        "item_type": "boss_potion",
        "effect": {"max_uses": 4, "fatigue_bonus": 3},
    },
    # حمام
    {
        "item_id": "bath_soap",
        "name": "🧼 صابون گربه",
        "description": "یک بار حموم — کثیفی را کم می‌کند.",
        "price": 22,
        "rarity": "common",
        "item_type": "bath",
        "effect": {"cleanliness": 35, "mood": 2, "max_uses": 1},
    },
]


async def seed_shop():
    for it in PET_SHOP_CATALOG:
        await execute(
            """
            INSERT INTO shop_items (item_id, name, description, price, stock, rarity, item_type, effect, active)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb, TRUE)
            ON CONFLICT (item_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                price = EXCLUDED.price,
                rarity = EXCLUDED.rarity,
                item_type = EXCLUDED.item_type,
                effect = EXCLUDED.effect,
                active = TRUE
            """,
            it["item_id"], it["name"], it["description"], it["price"],
            -1, it["rarity"], it["item_type"], json.dumps(it["effect"]),
        )


async def get_shop_items():
    rows = await fetch(
        "SELECT * FROM shop_items WHERE active = TRUE ORDER BY item_type, price"
    )
    return [dict(r) for r in rows]


async def get_shop_item(item_id: str):
    row = await fetchrow("SELECT * FROM shop_items WHERE item_id = $1", item_id)
    return dict(row) if row else None


async def repair_item(user_id: int, item_id: str) -> tuple:
    """تعمیر آیتم repairable. Returns (ok, message)."""
    from database.users import spend_meow_coins
    row = await fetchrow(
        "SELECT * FROM inventory WHERE user_id=$1 AND item_id=$2",
        int(user_id), item_id,
    )
    if not row:
        return False, "این آیتم را نداری."
    meta = _meta(dict(row))
    if not meta.get("needs_repair") and int(meta.get("uses_left") or 0) > 0:
        return False, "نیازی به تعمیر نیست."
    cost = int(meta.get("repair_cost") or 20)
    max_u = int(meta.get("max_uses") or 30)
    ok = await spend_meow_coins(user_id, cost)
    if not ok:
        return False, f"کوین کافی نیست. هزینه تعمیر: `{cost}` 🪙"
    meta["needs_repair"] = False
    meta["uses_left"] = max_u
    await execute(
        "UPDATE inventory SET meta=$3::jsonb WHERE user_id=$1 AND item_id=$2",
        int(user_id), item_id, json.dumps(meta),
    )
    return True, f"✅ تعمیر شد! دوام دوباره `{max_u}` — هزینه `{cost}` 🪙"
