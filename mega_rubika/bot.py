"""
هسته MEGA BOT روبیکا — منطق اصلی، منوها، دسترسی مالک، بن داخلی، آمار، فان
"""
from __future__ import annotations
import asyncio
import logging
import random
import time
from typing import Any, Optional

from .api import RubikaAPI, RubikaAPIError
from .config import (
    OWNER_ID, SUPPORT_TEXT, DONATION_TEXT, ABOUT_TEXT, BOT_VERSION, RATE_LIMIT_PER_USER,
)
from .database import Database
from . import keyboards as kb

log = logging.getLogger("mega_rubika.bot")

# محتوای فان (از فایل‌های استخراج‌شده از MEGA BOT)
try:
    from .content.jokes_content import JOKES as _JOKES_RAW  # type: ignore
    JOKES = [j["text"] if isinstance(j, dict) else str(j) for j in _JOKES_RAW]
except Exception:
    JOKES = [
        "یه روز یه ربات رفت دکتر گفت حالم بده... دکتر گفت باگ داری 😂",
        "چرا برنامه‌نویس از تاریکی می‌ترسه؟ چون باگ توش قایم می‌شه.",
        "ربات گفت به انسان: من باگ ندارم، تو فیچر داری 🗿",
    ]

try:
    from .content.hafez_content import FORTUNES as _FORTUNES  # type: ignore
    HAFEZ_FALS = [
        f"{f.get('title','')}\n\n{f.get('poem','')}\n\n📖 {f.get('meaning','')}"
        for f in _FORTUNES
    ]
except Exception:
    HAFEZ_FALS = [
        "دل می‌رود ز دستم صاحب دلان خدا را\nدردا که راز پنهان خواهد شد آشکارا",
        "اگر آن ترک شیرازی به دست آرد دل ما را\nبه خال هندویش بخشم سمرقند و بخارا را",
    ]


class MegaRubikaBot:
    def __init__(self, api: RubikaAPI, db: Database):
        self.api = api
        self.db = db
        self._offset: str | None = None
        self._running = False
        self._rate: dict[str, float] = {}  # user_id -> last_ts
        self.bot_id: str | None = None
        self.bot_name: str = "MEGA BOT"

    # ---------- helpers ----------
    def _is_owner(self, user_id: str) -> bool:
        return bool(OWNER_ID) and str(user_id) == str(OWNER_ID)

    def _rate_ok(self, user_id: str) -> bool:
        now = time.monotonic()
        last = self._rate.get(user_id, 0)
        if now - last < RATE_LIMIT_PER_USER:
            return False
        self._rate[user_id] = now
        return True

    def _extract_message(self, update: dict) -> dict | None:
        """استخراج پیام از ساختارهای مختلف آپدیت روبیکا."""
        if "message" in update:
            return update["message"]
        if "inline_message" in update:
            return update["inline_message"]
        # بعضی پاسخ‌ها مستقیم فیلد دارند
        if "chat_id" in update and ("text" in update or "aux_data" in update):
            return update
        return None

    def _sender_id(self, msg: dict) -> str:
        return str(
            msg.get("sender_id")
            or msg.get("from", {}).get("user_id")
            or msg.get("from", {}).get("id")
            or ""
        )

    def _chat_id(self, msg: dict) -> str:
        return str(msg.get("chat_id") or msg.get("chat", {}).get("id") or "")

    def _text(self, msg: dict) -> str:
        return (msg.get("text") or "").strip()

    def _button_id(self, msg: dict) -> str | None:
        aux = msg.get("aux_data") or {}
        return aux.get("button_id") or msg.get("button_id")

    def _message_id(self, msg: dict) -> str | None:
        return msg.get("message_id") or msg.get("id")

    async def safe_send(
        self,
        chat_id: str,
        text: str,
        *,
        chat_keypad: dict | None = None,
        inline_keypad: dict | None = None,
        reply_to: str | None = None,
    ) -> dict | None:
        try:
            return await self.api.send_message(
                chat_id,
                text,
                chat_keypad=chat_keypad,
                inline_keypad=inline_keypad,
                reply_to_message_id=reply_to,
            )
        except RubikaAPIError as e:
            log.error("send failed: %s", e)
            return None

    # ---------- lifecycle ----------
    async def run(self, poll_timeout: int = 25) -> None:
        me = await self.api.get_me()
        bot_info = me.get("bot") or me.get("data") or me
        self.bot_id = str(
            bot_info.get("bot_id")
            or bot_info.get("user_id")
            or bot_info.get("id")
            or ""
        )
        self.bot_name = bot_info.get("title") or bot_info.get("name") or "MEGA BOT"
        log.info("Bot started: %s (%s)", self.bot_name, self.bot_id or "?")
        self._running = True
        while self._running:
            try:
                res = await self.api.get_updates(limit=50, offset_id=self._offset)
                updates = (
                    res.get("updates")
                    or res.get("data", {}).get("updates")
                    or res.get("data")
                    or []
                )
                if isinstance(updates, dict):
                    updates = updates.get("updates", [])
                for upd in updates or []:
                    # offset
                    oid = (
                        upd.get("offset_id")
                        or upd.get("update_id")
                        or (upd.get("message") or {}).get("message_id")
                    )
                    if oid:
                        self._offset = str(oid)
                    try:
                        await self._dispatch(upd)
                    except Exception:
                        log.exception("dispatch error")
                await asyncio.sleep(0.35)
            except RubikaAPIError as e:
                log.warning("poll error: %s", e)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("run loop")
                await asyncio.sleep(3)

    def stop(self) -> None:
        self._running = False

    async def _dispatch(self, update: dict) -> None:
        msg = self._extract_message(update)
        if not msg:
            return
        chat_id = self._chat_id(msg)
        user_id = self._sender_id(msg)
        text = self._text(msg)
        btn = self._button_id(msg)
        if not chat_id:
            return

        # ثبت کاربر/گروه
        if user_id:
            await self.db.upsert_user(user_id, first_name=msg.get("first_name") or "")
        is_group = str(chat_id).startswith("g0") or str(chat_id).startswith("c0")
        await self.db.upsert_group(chat_id)
        await self.db.track_event(chat_id, "group" if is_group else "private", user_id)

        # بن داخلی
        if user_id and await self.db.is_banned("user", user_id):
            if not self._is_owner(user_id):
                return
        if await self.db.is_banned("group", chat_id):
            return

        if user_id and not self._rate_ok(user_id):
            return

        # دکمه
        if btn:
            await self._on_button(chat_id, user_id, btn, msg)
            return

        # دستور متنی
        low = text.lower().lstrip("/")
        if text in ("/start", "start", "شروع") or low == "start":
            await self.cmd_start(chat_id, user_id)
        elif text in ("/help", "help", "راهنما"):
            await self.cmd_help(chat_id)
        elif text in ("/owner", "owner") and self._is_owner(user_id):
            await self.cmd_owner(chat_id, user_id)
        elif text in ("/admin", "admin"):
            await self.cmd_admin(chat_id, user_id)
        elif text in ("/stats", "آمار"):
            await self.cmd_stats(chat_id)
        elif text in ("جوک", "joke"):
            await self.cmd_joke(chat_id)
        elif text in ("حافظ", "فال", "hafez"):
            await self.cmd_hafez(chat_id)
        elif text in ("درباره", "about"):
            await self.cmd_about(chat_id)
        elif text:
            # منوهای reply keyboard با متن
            await self._on_menu_text(chat_id, user_id, text)

    # ---------- commands ----------
    async def cmd_start(self, chat_id: str, user_id: str) -> None:
        name = self.bot_name
        text = (
            f"سلام! 👋\n"
            f"من **{name}** نسخه روبیکا هستم.\n"
            f"از منوی پایین استفاده کن یا /help بزن.\n\n"
            f"نسخه: `{BOT_VERSION}`"
        )
        await self.safe_send(chat_id, text, chat_keypad=kb.USER_MAIN)

    async def cmd_help(self, chat_id: str) -> None:
        text = (
            "📖 راهنمای دستورات\n\n"
            "• /start — منوی اصلی\n"
            "• /help — همین راهنما\n"
            "• /stats — آمار ربات\n"
            "• جوک / حافظ — سرگرمی\n"
            "• /owner — فقط مالک\n"
            "• /admin — ادمین‌های مجاز\n\n"
            "دکمه‌های منو هم کار می‌کنن."
        )
        await self.safe_send(chat_id, text, chat_keypad=kb.USER_MAIN)

    async def cmd_about(self, chat_id: str) -> None:
        await self.safe_send(chat_id, ABOUT_TEXT, chat_keypad=kb.USER_MAIN)

    async def cmd_stats(self, chat_id: str) -> None:
        users = await self.db.count_users()
        groups = await self.db.count_groups()
        text = (
            f"📊 آمار MEGA BOT (روبیکا)\n\n"
            f"👤 کاربران: {users}\n"
            f"👥 گروه‌ها: {groups}\n"
            f"🔖 نسخه: {BOT_VERSION}"
        )
        await self.safe_send(chat_id, text)

    async def cmd_joke(self, chat_id: str) -> None:
        joke = random.choice(JOKES) if JOKES else "جوکی ندارم 😅"
        await self.safe_send(chat_id, f"😂 {joke}")

    async def cmd_hafez(self, chat_id: str) -> None:
        fal = random.choice(HAFEZ_FALS) if HAFEZ_FALS else "امروز فال نداری 📜"
        await self.safe_send(chat_id, f"📜 فال حافظ\n\n{fal}")

    async def cmd_owner(self, chat_id: str, user_id: str) -> None:
        if not self._is_owner(user_id):
            await self.safe_send(chat_id, "⛔️ فقط مالک.")
            return
        text = (
            f"👑 پنل مالک\n"
            f"شناسه تو: `{user_id}`\n"
            f"از دکمه‌ها استفاده کن."
        )
        await self.safe_send(chat_id, text, chat_keypad=kb.OWNER_MENU)

    async def cmd_admin(self, chat_id: str, user_id: str) -> None:
        if not self._is_owner(user_id):
            # بعداً جدول admins چک می‌شود
            await self.safe_send(chat_id, "دسترسی نداری.")
            return
        await self.safe_send(chat_id, "🛠 پنل ادمین", chat_keypad=kb.ADMIN_MENU)

    # ---------- buttons & menu text ----------
    async def _on_menu_text(self, chat_id: str, user_id: str, text: str) -> None:
        mapping = {
            "🛰️ ارتباط با مگا": "support",
            "💜 حمایت مالی": "donate",
            "🧑‍💻 تیم توسعه": "team",
            "📊 آمار و اطلاعات": "stats",
            "🧩 امکانات بیشتر": "more",
            "ℹ️ درباره ربات": "about",
            "📖 راهنما": "guide",
            "😂 جوک": "joke",
            "📜 فال حافظ": "hafez",
            "↩️ بازگشت": "back_main",
            "✖️ بستن": "close",
        }
        bid = mapping.get(text)
        if bid:
            await self._on_button(chat_id, user_id, bid, {})

    async def _on_button(self, chat_id: str, user_id: str, btn: str, msg: dict) -> None:
        if btn in ("close",):
            await self.safe_send(chat_id, "منو بسته شد. /start برای بازگشت.")
            return
        if btn in ("back_main", "home"):
            await self.cmd_start(chat_id, user_id)
            return
        if btn == "support":
            await self.safe_send(chat_id, SUPPORT_TEXT, chat_keypad=kb.USER_MAIN)
            return
        if btn == "donate":
            await self.safe_send(chat_id, DONATION_TEXT, chat_keypad=kb.USER_MAIN)
            return
        if btn == "team":
            team = await self.db.list_team()
            if not team:
                await self.safe_send(chat_id, "هنوز عضوی برای تیم ثبت نشده.", chat_keypad=kb.USER_MAIN)
            else:
                lines = [f"• {m['name']} — {m.get('title') or ''}" for m in team]
                await self.safe_send(chat_id, "🧑‍💻 تیم توسعه\n\n" + "\n".join(lines), chat_keypad=kb.USER_MAIN)
            return
        if btn == "stats":
            await self.cmd_stats(chat_id)
            return
        if btn == "more":
            await self.safe_send(chat_id, "امکانات بیشتر:", chat_keypad=kb.MORE_MENU)
            return
        if btn == "about":
            await self.cmd_about(chat_id)
            return
        if btn == "guide":
            await self.cmd_help(chat_id)
            return
        if btn == "joke":
            await self.cmd_joke(chat_id)
            return
        if btn == "hafez":
            await self.cmd_hafez(chat_id)
            return

        # owner buttons
        if btn.startswith("own_") and self._is_owner(user_id):
            await self._owner_action(chat_id, user_id, btn)
            return
        if btn.startswith("adm_") and self._is_owner(user_id):
            await self._owner_action(chat_id, user_id, btn)
            return

        await self.safe_send(chat_id, "دکمه شناخته نشد. /start")

    async def _owner_action(self, chat_id: str, user_id: str, btn: str) -> None:
        if btn in ("own_stats", "adm_stats"):
            users = await self.db.count_users()
            groups = await self.db.count_groups()
            await self.safe_send(
                chat_id,
                f"📈 آمار مالک\nکاربران: {users}\nگروه‌ها: {groups}",
                chat_keypad=kb.OWNER_MENU,
            )
            return
        if btn == "own_users":
            await self.safe_send(chat_id, f"تعداد کاربران ثبت‌شده: {await self.db.count_users()}", chat_keypad=kb.OWNER_MENU)
            return
        if btn == "own_groups":
            await self.safe_send(chat_id, f"تعداد گروه‌ها: {await self.db.count_groups()}", chat_keypad=kb.OWNER_MENU)
            return
        if btn == "own_cases":
            await self.safe_send(
                chat_id,
                "برای بن داخلی:\n`/ban_user <user_id> دلیل`\n`/unban <case_code>`\n(به‌زودی از پنل کامل‌تر می‌شه)",
                chat_keypad=kb.OWNER_MENU,
            )
            return
        if btn == "own_broadcast":
            await self.safe_send(
                chat_id,
                "پیام همگانی: فعلاً از طریق دستور جدا پیاده‌سازی می‌شود تا محدودیت نرخ رعایت شود.",
                chat_keypad=kb.OWNER_MENU,
            )
            return
        if btn == "own_settings":
            await self.safe_send(chat_id, f"نسخه: {BOT_VERSION}\nOWNER_ID: تنظیم شده.", chat_keypad=kb.OWNER_MENU)
            return
        if btn == "own_team":
            team = await self.db.list_team()
            await self.safe_send(chat_id, f"اعضای تیم: {len(team)}", chat_keypad=kb.OWNER_MENU)
            return
        await self.safe_send(chat_id, "در حال توسعه این بخش.", chat_keypad=kb.OWNER_MENU)
