# ==========================================
# Users Repository
# ==========================================

from .pool import fetchrow, fetch, execute, fetchval
from datetime import datetime, timezone


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


async def create_user(user_id: int, first_name: str = "", username: str = "", chat_id=None):
    await execute(
        """
        INSERT INTO users (user_id, first_name, username)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO UPDATE SET
            first_name = COALESCE(NULLIF($2, ''), users.first_name),
            username = COALESCE(NULLIF($3, ''), users.username),
            updated_at = NOW()
        """,
        int(user_id), first_name or "", username or "",
    )
    if chat_id is not None:
        from .groups import register_group_user
        await register_group_user(user_id, chat_id)
    return await get_user(user_id)


async def get_user(user_id: int, chat_id=None):
    row = await fetchrow("SELECT * FROM users WHERE user_id = $1", int(user_id))
    return _row_to_dict(row)


async def get_user_by_username(username: str):
    """جستجو با یوزرنیم (با یا بدون @). case-insensitive."""
    u = (username or "").strip().lstrip("@").lower()
    if not u:
        return None
    row = await fetchrow(
        "SELECT * FROM users WHERE LOWER(TRIM(LEADING '@' FROM COALESCE(username, ''))) = $1 LIMIT 1",
        u,
    )
    return dict(row) if row else None


async def resolve_user_ref(ref: str):
    """آیدی عددی یا @username → دیکشنری کاربر یا None."""
    text = (ref or "").strip()
    if not text:
        return None
    # numeric id
    try:
        tid = int(text.split()[0].lstrip("@"))
        if str(tid) == text.split()[0].lstrip("@"):
            u = await get_user(tid)
            if u:
                return u
    except ValueError:
        pass
    return await get_user_by_username(text)


async def update_user_info(user_id: int, first_name: str = "", username: str = "", chat_id=None):
    await execute(
        """
        UPDATE users SET
            first_name = COALESCE(NULLIF($2, ''), first_name),
            username = COALESCE(NULLIF($3, ''), username),
            updated_at = NOW()
        WHERE user_id = $1
        """,
        int(user_id), first_name or "", username or "",
    )


async def update_user(user_id: int, **fields):
    if not fields:
        return
    allowed = {
        "meow_points", "meow_coins", "gym_level", "xp", "level",
        "total_meows", "total_battles", "total_wins", "total_losses",
        "last_meow", "last_battle", "last_daily", "daily_streak", "last_game_reward",
        "first_name", "username",
    }
    sets = []
    args = [int(user_id)]
    i = 2
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ${i}")
            args.append(v)
            i += 1
    if not sets:
        return
    sets.append("updated_at = NOW()")
    await execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = $1", *args)


async def add_meow_points(user_id: int, amount: int = 1, chat_id=None):
    """امتیاز فصل سراسری + در صورت وجود chat_id امتیاز گروهی."""
    await execute(
        """
        UPDATE users SET
            meow_points = meow_points + $2,
            total_meows = total_meows + 1,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        int(user_id), int(amount),
    )
    if chat_id is not None:
        try:
            from database.group_stats import add_group_points
            await add_group_points(user_id, chat_id, amount)
        except Exception:
            pass


async def get_meow_points(user_id: int, chat_id=None) -> int:
    val = await fetchval("SELECT meow_points FROM users WHERE user_id = $1", int(user_id))
    return int(val or 0)


async def spend_meow_points(user_id: int, amount: int = 0, chat_id=None) -> bool:
    result = await execute(
        """
        UPDATE users SET meow_points = meow_points - $2, updated_at = NOW()
        WHERE user_id = $1 AND meow_points >= $2
        """,
        int(user_id), int(amount),
    )
    return result != "UPDATE 0"


async def add_meow_coins(user_id: int, amount: int = 0, chat_id=None):
    await execute(
        """
        UPDATE users SET meow_coins = meow_coins + $2, updated_at = NOW()
        WHERE user_id = $1
        """,
        int(user_id), int(amount),
    )


async def get_meow_coins(user_id: int, chat_id=None) -> int:
    val = await fetchval("SELECT meow_coins FROM users WHERE user_id = $1", int(user_id))
    return int(val or 0)


async def spend_meow_coins(user_id: int, amount: int = 0, chat_id=None) -> bool:
    result = await execute(
        """
        UPDATE users SET meow_coins = meow_coins - $2, updated_at = NOW()
        WHERE user_id = $1 AND meow_coins >= $2
        """,
        int(user_id), int(amount),
    )
    # asyncpg returns "UPDATE N"
    return str(result) != "UPDATE 0" and not str(result).endswith(" 0")


async def claim_daily_reward_atomic(user_id: int, today: str, reward: int, new_streak: int):
    """
    Atomic daily claim for Tehran calendar day.
    Returns (ok, streak_or_existing, coins_awarded).
    Only one successful claim per user per day even under concurrent presses.
    """
    row = await fetchrow(
        """
        UPDATE users SET
            meow_coins = meow_coins + $3,
            last_daily = $2,
            daily_streak = $4,
            updated_at = NOW()
        WHERE user_id = $1
          AND (last_daily IS NULL OR last_daily <> $2)
        RETURNING daily_streak, meow_coins
        """,
        int(user_id), today, int(reward), int(new_streak),
    )
    if row:
        return True, int(row["daily_streak"] or new_streak), int(reward)
    # already claimed today
    u = await get_user(user_id)
    return False, int((u or {}).get("daily_streak") or 0), 0


async def try_claim_meow_atomic(
    user_id: int,
    now_ts: float,
    cooldown_sec: float,
    points: int,
    coins: int = 0,
):
    """
    Atomic meow cooldown claim.
    Updates last_meow + points (+ optional coins) only if cooldown elapsed.
    Returns (ok, total_points_after, remaining_sec, total_coins_after).
    """
    threshold = float(now_ts) - float(cooldown_sec)
    row = await fetchrow(
        """
        UPDATE users SET
            last_meow = $2,
            meow_points = meow_points + $3,
            meow_coins = meow_coins + $5,
            total_meows = total_meows + 1,
            updated_at = NOW()
        WHERE user_id = $1
          AND (last_meow IS NULL OR last_meow <= $4)
        RETURNING meow_points, meow_coins, last_meow
        """,
        int(user_id), float(now_ts), int(points), float(threshold), max(0, int(coins)),
    )
    if row:
        return True, int(row["meow_points"] or 0), 0.0, int(row["meow_coins"] or 0)
    last = float(await fetchval("SELECT last_meow FROM users WHERE user_id=$1", int(user_id)) or 0)
    remaining = max(0.0, cooldown_sec - (now_ts - last))
    pts = int(await fetchval("SELECT meow_points FROM users WHERE user_id=$1", int(user_id)) or 0)
    coins_bal = int(await fetchval("SELECT meow_coins FROM users WHERE user_id=$1", int(user_id)) or 0)
    return False, pts, remaining, coins_bal


async def set_gym_level(user_id: int, level: int = 1, chat_id=None):
    await execute(
        "UPDATE users SET gym_level = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), int(level),
    )


async def get_gym_level(user_id: int, chat_id=None) -> int:
    val = await fetchval("SELECT gym_level FROM users WHERE user_id = $1", int(user_id))
    return int(val or 1)


async def admin_set_meow_points(user_id: int, new_value: int):
    row = await fetchrow("SELECT meow_points FROM users WHERE user_id = $1", int(user_id))
    if not row:
        return False, 0, 0
    old = int(row["meow_points"] or 0)
    await execute(
        "UPDATE users SET meow_points = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), max(0, int(new_value)),
    )
    return True, old, max(0, int(new_value))


async def admin_set_meow_coins(user_id: int, new_value: int):
    row = await fetchrow("SELECT meow_coins FROM users WHERE user_id = $1", int(user_id))
    if not row:
        return False, 0, 0
    old = int(row["meow_coins"] or 0)
    await execute(
        "UPDATE users SET meow_coins = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), max(0, int(new_value)),
    )
    return True, old, max(0, int(new_value))


async def admin_set_gym_level(user_id: int, new_value: int, min_level=1, max_level=100):
    row = await fetchrow("SELECT gym_level FROM users WHERE user_id = $1", int(user_id))
    if not row:
        return False, 0, 0
    old = int(row["gym_level"] or 1)
    new_val = max(min_level, min(max_level, int(new_value)))
    await execute(
        "UPDATE users SET gym_level = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), new_val,
    )
    return True, old, new_val


async def set_last_meow(user_id: int, timestamp: float = 0, chat_id=None):
    await execute(
        "UPDATE users SET last_meow = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), float(timestamp),
    )


async def get_last_meow(user_id: int, chat_id=None) -> float:
    val = await fetchval("SELECT last_meow FROM users WHERE user_id = $1", int(user_id))
    return float(val or 0)


async def set_last_battle(user_id: int, timestamp: float = 0, chat_id=None):
    await execute(
        "UPDATE users SET last_battle = $2, updated_at = NOW() WHERE user_id = $1",
        int(user_id), float(timestamp),
    )


async def get_last_battle(user_id: int, chat_id=None) -> float:
    val = await fetchval("SELECT last_battle FROM users WHERE user_id = $1", int(user_id))
    return float(val or 0)


async def get_top_users(chat_id=None, limit: int = 30):
    """Season ranking by meow_points."""
    rows = await fetch(
        """
        SELECT user_id, first_name, username, meow_points, meow_coins, gym_level
        FROM users
        WHERE meow_points > 0
        ORDER BY meow_points DESC, user_id ASC
        LIMIT $1
        """,
        int(limit),
    )
    return [_row_to_dict(r) for r in rows]


async def get_global_top_users(limit: int = 30):
    return await get_top_users(limit=limit)


async def get_all_users(chat_id=None):
    rows = await fetch("SELECT * FROM users ORDER BY user_id")
    return [_row_to_dict(r) for r in rows]


async def count_users() -> int:
    return int(await fetchval("SELECT COUNT(*) FROM users") or 0)


async def count_active_users(days: int = 7) -> int:
    return int(await fetchval(
        """
        SELECT COUNT(*) FROM users
        WHERE updated_at > NOW() - ($1 || ' days')::interval
        """,
        str(days),
    ) or 0)


async def add_meow_points_to_all(chat_id, amount: int):
    """Legacy: add points to all users (used in seasons)."""
    result = await execute(
        "UPDATE users SET meow_points = meow_points + $1, updated_at = NOW()",
        int(amount),
    )
    # result like "UPDATE N"
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


async def add_meow_coins_to_all(chat_id, amount: int):
    result = await execute(
        "UPDATE users SET meow_coins = meow_coins + $1, updated_at = NOW()",
        int(amount),
    )
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


async def add_meow_points_global(amount: int):
    return await add_meow_points_to_all(None, amount)


async def add_meow_coins_global(amount: int):
    return await add_meow_coins_to_all(None, amount)


async def reset_meow_points():
    """
    Season reset: ONLY reset season ranking points (meow_points).
    Does NOT touch coins, pets, inventory, achievements, permanent level/xp.
    """
    await execute("UPDATE users SET meow_points = 0, updated_at = NOW()")
    try:
        from database.group_stats import reset_group_season_points
        await reset_group_season_points()
    except Exception:
        pass


async def increment_daily_meow(user_id: int, points_earned: int, day_date):
    """day_date: str YYYY-MM-DD یا datetime.date"""
    from datetime import date, datetime
    if isinstance(day_date, str):
        d = date.fromisoformat(day_date[:10])
    elif isinstance(day_date, datetime):
        d = day_date.date()
    else:
        d = day_date
    await execute(
        """
        INSERT INTO daily_meow_stats (user_id, day_date, meow_count, points_earned)
        VALUES ($1, $2, 1, $3)
        ON CONFLICT (user_id, day_date) DO UPDATE SET
            meow_count = daily_meow_stats.meow_count + 1,
            points_earned = daily_meow_stats.points_earned + $3
        """,
        int(user_id), d, int(points_earned),
    )


async def get_top_daily_meowers(day_date, limit: int = 10):
    from datetime import date, datetime
    if isinstance(day_date, str):
        d = date.fromisoformat(day_date[:10])
    elif isinstance(day_date, datetime):
        d = day_date.date()
    else:
        d = day_date
    rows = await fetch(
        """
        SELECT d.user_id, d.meow_count, d.points_earned,
               u.first_name, u.username
        FROM daily_meow_stats d
        JOIN users u ON u.user_id = d.user_id
        WHERE d.day_date = $1
        ORDER BY d.points_earned DESC, d.meow_count DESC
        LIMIT $2
        """,
        d, int(limit),
    )
    return [dict(r) for r in rows]


async def get_dashboard_stats():
    """Real stats for Owner Dashboard."""
    stats = {}
    stats["total_users"] = await count_users()
    stats["active_users"] = await count_active_users(7)
    stats["total_groups"] = int(await fetchval("SELECT COUNT(*) FROM groups") or 0)
    stats["total_pets"] = int(await fetchval("SELECT COUNT(*) FROM pets") or 0)
    stats["total_coins"] = int(await fetchval("SELECT COALESCE(SUM(meow_coins),0) FROM users") or 0)
    stats["total_battles"] = int(await fetchval("SELECT COALESCE(SUM(total_battles),0) FROM users") or 0)
    stats["total_meows"] = int(await fetchval("SELECT COALESCE(SUM(total_meows),0) FROM users") or 0)
    stats["total_admins"] = int(await fetchval("SELECT COUNT(*) FROM admins WHERE enabled = TRUE") or 0)
    season = await fetchrow("SELECT season_number FROM seasons WHERE active = TRUE LIMIT 1")
    stats["current_season"] = int(season["season_number"]) if season else 0
    stats["active_events"] = int(await fetchval(
        "SELECT COUNT(*) FROM events WHERE active = TRUE AND end_at > NOW()"
    ) or 0)
    return stats
