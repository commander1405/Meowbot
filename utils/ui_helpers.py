# ==========================================
# MeowBot — UI Helpers (Channel promo + Studio)
# ==========================================
# دکمه عضویت کانال اطلاع‌رسانی زیر تمام پیام‌های خروجی
# + حفظ دکمه استدیو (قابلیت قبلی)
# ==========================================

from __future__ import annotations

import random
from typing import Optional

from bale import InlineKeyboardMarkup, InlineKeyboardButton


CHANNEL_USERNAME = "@meownewsbot"
CHANNEL_JOIN_URL = "https://ble.ir/join/AGwTW3RLb3"

CHANNEL_BUTTON_TEXTS = [
    "چنل اطلاع رسانی",
    "جوین نمیدی؟",
    "بزن روم",
    "عضو شو مشتی",
    "خبرای میو اینجاست",
    "از دست نده 🐱",
    "کانال رسمی میو",
    "عضو شو، باخبر شو",
    "اینجا خبر می‌دیم",
    "یه جوین بده رفیق",
    "چنل میو بازه",
    "بزن بریم چنل",
    "آپدیت‌ها اینجان",
    "میو نیوز 👇",
    "عضویت در کانال",
    "خبر جدید می‌خوای؟",
    "چنل رو از دست نده",
    "بزن عضو شی",
    "اطلاعیه‌ها اینجا",
    "فقط یه کلیک تا چنل",
    "میو رو دنبال کن",
    "کانال خبری میو",
    "جوین شو الان",
    "چنل رسمی MeowBot",
    "اینجا باشه برات بهتره",
    "خبر اول اینجا میاد",
    "یه سر به چنل بزن",
    "عضو کانال شو",
    "میو منتظرته تو چنل",
    "لینک چنل 👇",
]

STUDIO_BUTTON_TEXT = "🌑 دارک نایت استدیو"
STUDIO_BUTTON_URL = "https://ble.ir/join/FetpvYjpGQ"

_message_patched = False


def channel_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=random.choice(CHANNEL_BUTTON_TEXTS), url=CHANNEL_JOIN_URL)


def studio_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=STUDIO_BUTTON_TEXT, url=STUDIO_BUTTON_URL)


def _iter_keyboard_items(components) -> list:
    out = []
    if components is None:
        return out
    keyboards = getattr(components, "keyboards", None)
    if not keyboards:
        return out
    for item in keyboards:
        btn = getattr(item, "item", item)
        row = getattr(item, "row", None) or 1
        try:
            row = int(row)
        except (TypeError, ValueError):
            row = 1
        out.append((btn, row))
    return out


def _button_url(btn) -> Optional[str]:
    if btn is None:
        return None
    u = getattr(btn, "url", None)
    if u:
        return str(u)
    to_dict = getattr(btn, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            if isinstance(d, dict) and d.get("url"):
                return str(d["url"])
        except Exception:
            pass
    return None


def with_promo(components=None) -> InlineKeyboardMarkup:
    """کیبورد فعلی + ردیف کانال (متن رندوم) + استدیو؛ بدون تکرار URL."""
    markup = InlineKeyboardMarkup()
    max_row = 0
    existing_urls = set()

    for btn, row in _iter_keyboard_items(components):
        if row > max_row:
            max_row = row
        u = _button_url(btn)
        if u:
            existing_urls.add(u)
        try:
            markup.add(btn, row=row)
        except Exception:
            pass

    next_row = max_row + 1
    if CHANNEL_JOIN_URL not in existing_urls:
        try:
            markup.add(channel_button(), row=next_row)
            next_row += 1
        except Exception:
            pass
    if STUDIO_BUTTON_URL not in existing_urls:
        try:
            markup.add(studio_button(), row=next_row)
        except Exception:
            pass
    return markup


def with_studio(components=None) -> InlineKeyboardMarkup:
    return with_promo(components)


async def send_message(bot, chat_id, text, components=None, **kwargs):
    components = with_promo(components)
    return await bot.send_message(chat_id, text, components=components, **kwargs)


def _patch_bot_instance(bot) -> None:
    for attr in (
        "send_message",
        "send_photo",
        "send_document",
        "send_video",
        "send_animation",
        "send_audio",
    ):
        if not hasattr(bot, attr):
            continue
        orig = getattr(bot, attr)
        if getattr(orig, "_meow_promo_patched", False):
            continue

        async def wrapped(*args, _orig=orig, **kwargs):
            if "components" in kwargs:
                kwargs["components"] = with_promo(kwargs.get("components"))
                return await _orig(*args, **kwargs)
            try:
                return await _orig(*args, components=with_promo(None), **kwargs)
            except TypeError:
                return await _orig(*args, **kwargs)

        try:
            wrapped._meow_promo_patched = True  # type: ignore
            setattr(bot, attr, wrapped)
        except Exception as e:
            print(f"⚠️ Could not patch bot.{attr}: {e}")


def patch_bot_messaging(bot=None):
    """پچ Message.reply/edit و bot.send_* برای دکمه کانال زیر همه پیام‌ها."""
    global _message_patched
    if _message_patched:
        if bot is not None:
            _patch_bot_instance(bot)
        return

    try:
        from bale import Message
    except ImportError:
        print("⚠️ ui_helpers: bale.Message not available")
        return

    def _wrap_text(orig):
        async def wrapped(self, text, *args, components=None, **kwargs):
            components = with_promo(components)
            return await orig(self, text, *args, components=components, **kwargs)

        return wrapped

    for attr in ("reply", "edit", "edit_text"):
        if hasattr(Message, attr):
            try:
                setattr(Message, attr, _wrap_text(getattr(Message, attr)))
            except Exception as e:
                print(f"⚠️ Could not patch Message.{attr}: {e}")

    for attr in (
        "reply_photo",
        "reply_document",
        "reply_video",
        "reply_animation",
        "reply_audio",
        "edit_caption",
    ):
        if not hasattr(Message, attr):
            continue
        orig = getattr(Message, attr)

        async def media_wrapped(self, *args, components=None, _orig=orig, **kwargs):
            components = with_promo(components)
            try:
                return await _orig(self, *args, components=components, **kwargs)
            except TypeError:
                return await _orig(self, *args, **kwargs)

        try:
            setattr(Message, attr, media_wrapped)
        except Exception as e:
            print(f"⚠️ Could not patch Message.{attr}: {e}")

    if bot is not None:
        _patch_bot_instance(bot)

    _message_patched = True
    print("✅ Channel promo + studio: messaging patched")


def patch_studio(bot=None):
    return patch_bot_messaging(bot)
