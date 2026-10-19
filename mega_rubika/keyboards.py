"""
کیبوردهای روبیکا — Chat Keypad و Inline Keypad
فرمت رسمی روبیکا با type: Simple
"""
from __future__ import annotations
from typing import List, Tuple


def simple_button(btn_id: str, text: str) -> dict:
    return {"id": btn_id, "type": "Simple", "button_text": text}


def chat_keypad(rows: List[List[Tuple[str, str]]], *, resize: bool = True, on_time: bool = False) -> dict:
    """
    rows: list of rows, each row list of (button_id, button_text)
    """
    return {
        "rows": [
            {"buttons": [simple_button(bid, txt) for bid, txt in row]}
            for row in rows
        ],
        "resize_keyboard": resize,
        "on_time_keyboard": on_time,
    }


def inline_keypad(rows: List[List[Tuple[str, str]]]) -> dict:
    return {
        "rows": [
            {"buttons": [simple_button(bid, txt) for bid, txt in row]}
            for row in rows
        ]
    }


# منوی اصلی کاربر (Reply / Chat Keypad)
USER_MAIN = chat_keypad([
    [("support", "🛰️ ارتباط با مگا"), ("donate", "💜 حمایت مالی")],
    [("team", "🧑‍💻 تیم توسعه"), ("stats", "📊 آمار و اطلاعات")],
    [("more", "🧩 امکانات بیشتر")],
])

MORE_MENU = chat_keypad([
    [("about", "ℹ️ درباره ربات"), ("guide", "📖 راهنما")],
    [("joke", "😂 جوک"), ("hafez", "📜 فال حافظ")],
    [("back_main", "↩️ بازگشت")],
])

OWNER_MENU = chat_keypad([
    [("own_stats", "📈 آمار کامل"), ("own_users", "👥 کاربران")],
    [("own_groups", "👥 گروه‌ها"), ("own_cases", "📁 پرونده‌ها")],
    [("own_broadcast", "📢 پیام همگانی"), ("own_settings", "⚙️ تنظیمات")],
    [("own_team", "🧑‍💻 تیم"), ("close", "✖️ بستن")],
])

ADMIN_MENU = chat_keypad([
    [("adm_stats", "📈 گزارش"), ("adm_search", "🔎 جستجو")],
    [("adm_ban", "🚫 بن کاربر"), ("adm_unban", "✅ آنبن")],
    [("adm_case", "📁 پرونده"), ("close", "✖️ بستن")],
])


def close_row() -> List[Tuple[str, str]]:
    return [("close", "✖️ بستن")]


def back_close(back_id: str = "back_main") -> List[Tuple[str, str]]:
    return [(back_id, "↩️ بازگشت"), ("close", "✖️ بستن")]
