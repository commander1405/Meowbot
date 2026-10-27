"""لایه دیتابیس هالووین."""
from __future__ import annotations
import time
from database.pool import fetchrow, fetch, execute, fetchval


async def ensure_hw_user(user_id: int) -> dict:
    await execute(
        """
        INSERT INTO halloween_user (user_id) VALUES ($1)
        ON CONFLICT (user_id) DO NOTHING
        """,
        int(user_id),
    )
    row = await fetchrow("SELECT * FROM halloween_user WHERE user_id = $1", int(user_id))
    return dict(row) if row else {"user_id": int(user_id)}


async def add_pumpkins_collected(user_id: int, n: int = 1) -> None:
    await ensure_hw_user(user_id)
    await execute(
        """
        UPDATE halloween_user SET pumpkins_total = pumpkins_total + $2, updated_at = NOW()
        WHERE user_id = $1
        """,
        int(user_id), int(n),
    )


async def add_chocolate(user_id: int, n: int = 1) -> int:
    await ensure_hw_user(user_id)
    await execute(
        """
        UPDATE halloween_user SET chocolate = chocolate + $2, updated_at = NOW()
        WHERE user_id = $1
        """,
        int(user_id), int(n),
    )
    return int(await fetchval("SELECT chocolate FROM halloween_user WHERE user_id=$1", int(user_id)) or 0)


async def spend_chocolate(user_id: int, n: int) -> bool:
    return await try_spend_chocolate(user_id, n)


async def try_spend_chocolate(user_id: int, n: int) -> bool:
    row = await fetchrow(
        """
        UPDATE halloween_user SET chocolate = chocolate - $2, updated_at = NOW()
        WHERE user_id = $1 AND chocolate >= $2
        RETURNING chocolate
        """,
        int(user_id), int(n),
    )
    return row is not None


async def set_skin(user_id: int, skin_id: str) -> None:
    await ensure_hw_user(user_id)
    await execute(
        "UPDATE halloween_user SET active_skin=$2, updated_at=NOW() WHERE user_id=$1",
        int(user_id), skin_id or "",
    )


async def get_active_skin(user_id: int) -> str:
    await ensure_hw_user(user_id)
    return str(await fetchval("SELECT active_skin FROM halloween_user WHERE user_id=$1", int(user_id)) or "")


async def claim_once(user_id: int, claim_type: str, day_key: str, meta: dict | None = None) -> bool:
    """True اگر برای اولین بار ثبت شد."""
    import json
    try:
        await execute(
            """
            INSERT INTO halloween_claims (user_id, claim_type, day_key, meta)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            int(user_id), claim_type, day_key, json.dumps(meta or {}),
        )
        return True
    except Exception:
        return False


async def has_claim(user_id: int, claim_type: str, day_key: str) -> bool:
    v = await fetchval(
        "SELECT 1 FROM halloween_claims WHERE user_id=$1 AND claim_type=$2 AND day_key=$3",
        int(user_id), claim_type, day_key,
    )
    return bool(v)
