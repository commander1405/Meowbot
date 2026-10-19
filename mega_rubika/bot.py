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
    OWNER_ID, OWNER_USERNAME, SUPPORT_TEXT, DONATION_TEXT, ABOUT_TEXT, BOT_VERSION, RATE_LIMIT_PER_USER,
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
        self._owner_uid_cache: str | None = None

    # ---------- helpers ----------
    def _is_owner(self, user_id: str, chat_id: str | None = None, username: str | None = None) -> bool:
        oid = str(OWNER_ID or "")
        if user_id and oid and str(user_id) == oid:
            return True
        if chat_id and oid and str(chat_id) == oid:
            return True
        # تشخیص با یوزرنیم @commander04
        uname = (username or "").lstrip("@").lower().strip()
        if OWNER_USERNAME and uname and uname == OWNER_USERNAME.lower():
            return True
        # کش از دیتابیس: اگر قبلاً یوزرنیم مالک به user_id مپ شده
        cached = getattr(self, "_owner_uid_cache", None)
        if cached and user_id and str(user_id) == str(cached):
            return True
        return False

    async def _refresh_owner_cache(self, user_id: str, username: str) -> None:
        uname = (username or "").lstrip("@").lower().strip()
        if not uname or not user_id:
            return
        await self.db.map_username(uname, user_id)
        if OWNER_USERNAME and uname == OWNER_USERNAME.lower():
            self._owner_uid_cache = str(user_id)
            log.info("owner resolved via @%s -> %s", uname, user_id)

    async def _can_moderate(self, chat_id: str, user_id: str, username: str | None = None) -> bool:
        if self._is_owner(user_id, chat_id, username):
            return True
        if user_id and await self.db.is_group_admin(chat_id, user_id):
            return True
        return False

    def _rate_ok(self, user_id: str) -> bool:
        now = time.monotonic()
        last = self._rate.get(user_id, 0)
        if now - last < RATE_LIMIT_PER_USER:
            return False
        self._rate[user_id] = now
        return True

    def _normalize_update(self, raw: dict) -> dict | None:
        """
        ساختار رسمی روبیکا:
          { "type": "NewMessage", "chat_id": "...", "new_message": { ... } }
        یا webhook-style:
          { "update": { ... } }
          { "inline_message": { chat_id, sender_id, text, aux_data, ... } }
        خروجی یکدست: {chat_id, sender_id, text, message_id, button_id, type}
        """
        if not isinstance(raw, dict):
            return None

        # لایه اضافه
        if "update" in raw and isinstance(raw["update"], dict):
            raw = raw["update"]
        if "data" in raw and isinstance(raw["data"], dict) and (
            "type" in raw["data"] or "new_message" in raw["data"] or "inline_message" in raw["data"]
        ):
            raw = raw["data"]

        def _pick_username(src: dict) -> str:
            return str(
                src.get("username")
                or src.get("user_name")
                or (src.get("author") or {}).get("username")
                or ""
            ).lstrip("@")

        # inline button / keypad tap
        if "inline_message" in raw and isinstance(raw["inline_message"], dict):
            im = raw["inline_message"]
            aux = im.get("aux_data") or {}
            return {
                "chat_id": str(im.get("chat_id") or ""),
                "sender_id": str(im.get("sender_id") or ""),
                "username": _pick_username(im),
                "text": (im.get("text") or "").strip(),
                "message_id": str(im.get("message_id") or ""),
                "button_id": aux.get("button_id") or im.get("button_id"),
                "type": "InlineMessage",
            }

        # NewMessage / UpdatedMessage
        msg = raw.get("new_message") or raw.get("updated_message") or raw.get("message")
        chat_id = raw.get("chat_id")
        if isinstance(msg, dict):
            aux = msg.get("aux_data") or {}
            return {
                "chat_id": str(chat_id or msg.get("chat_id") or ""),
                "sender_id": str(msg.get("sender_id") or ""),
                "username": _pick_username(msg),
                "text": (msg.get("text") or "").strip(),
                "message_id": str(msg.get("message_id") or ""),
                "button_id": aux.get("button_id") or msg.get("button_id"),
                "type": str(raw.get("type") or "NewMessage"),
            }

        # فرم تخت
        if raw.get("chat_id") and (raw.get("text") is not None or raw.get("aux_data")):
            aux = raw.get("aux_data") or {}
            return {
                "chat_id": str(raw.get("chat_id") or ""),
                "sender_id": str(raw.get("sender_id") or ""),
                "username": _pick_username(raw),
                "text": (raw.get("text") or "").strip(),
                "message_id": str(raw.get("message_id") or ""),
                "button_id": aux.get("button_id") or raw.get("button_id"),
                "type": str(raw.get("type") or "Flat"),
            }
        return None

    def _sender_id(self, msg: dict) -> str:
        return str(msg.get("sender_id") or "")

    def _chat_id(self, msg: dict) -> str:
        return str(msg.get("chat_id") or "")

    def _text(self, msg: dict) -> str:
        return (msg.get("text") or "").strip()

    def _button_id(self, msg: dict) -> str | None:
        return msg.get("button_id") or None

    def _message_id(self, msg: dict) -> str | None:
        mid = msg.get("message_id")
        return str(mid) if mid else None

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
        # پاسخ رسمی: { "status": "OK", "data": { "bot": { bot_id, bot_title, ... } } }
        data = me.get("data") if isinstance(me.get("data"), dict) else me
        bot_info = data.get("bot") if isinstance(data, dict) and isinstance(data.get("bot"), dict) else data
        if not isinstance(bot_info, dict):
            bot_info = {}
        self.bot_id = str(
            bot_info.get("bot_id")
            or bot_info.get("user_id")
            or bot_info.get("id")
            or ""
        )
        self.bot_name = (
            bot_info.get("bot_title")
            or bot_info.get("title")
            or bot_info.get("name")
            or "MEGA BOT"
        )
        log.info("Bot started: %s (%s) raw_keys=%s", self.bot_name, self.bot_id or "?", list(me.keys())[:8])
        self._running = True
        empty_polls = 0
        while self._running:
            try:
                res = await self.api.get_updates(limit=50, offset_id=self._offset)
                # { updates, next_offset_id } یا داخل data
                payload = res.get("data") if isinstance(res.get("data"), dict) else res
                if not isinstance(payload, dict):
                    payload = {}
                updates = payload.get("updates") or res.get("updates") or []
                if isinstance(updates, dict):
                    updates = updates.get("updates") or []
                next_off = (
                    payload.get("next_offset_id")
                    or res.get("next_offset_id")
                    or payload.get("offset_id")
                )
                if next_off:
                    self._offset = str(next_off)

                if updates:
                    empty_polls = 0
                    log.info("poll: %s update(s) offset=%s", len(updates), self._offset)
                else:
                    empty_polls += 1
                    if empty_polls % 40 == 1:
                        log.info("poll idle (offset=%s)", self._offset)

                for upd in updates or []:
                    if not isinstance(upd, dict):
                        continue
                    try:
                        await self._dispatch(upd)
                    except Exception:
                        log.exception("dispatch error on keys=%s", list(upd.keys())[:12])
                await asyncio.sleep(0.4)
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
        msg = self._normalize_update(update)
        if not msg:
            log.debug("skip update keys=%s", list(update.keys())[:10] if isinstance(update, dict) else type(update))
            return
        chat_id = self._chat_id(msg)
        user_id = self._sender_id(msg)
        text = self._text(msg)
        btn = self._button_id(msg)
        if not chat_id:
            log.debug("no chat_id in normalized msg: %s", msg)
            return
        log.info("in chat=%s user=%s text=%r btn=%r", chat_id[:16], (user_id or "")[:16], text[:40], btn)
        username = (msg.get("username") or "").lstrip("@")

        # ثبت کاربر/گروه + مپ یوزرنیم
        if user_id:
            await self.db.upsert_user(user_id, username=username, first_name=msg.get("first_name") or "")
            if username:
                await self._refresh_owner_cache(user_id, username)
        is_group = str(chat_id).startswith("g0") or str(chat_id).startswith("c0")
        await self.db.upsert_group(chat_id)
        await self.db.track_event(chat_id, "group" if is_group else "private", user_id)

        # بن داخلی
        if user_id and await self.db.is_banned("user", user_id):
            if not self._is_owner(user_id, chat_id):
                return
        if await self.db.is_banned("group", chat_id):
            return

        # دکمه کیپد
        if btn:
            if user_id and not self._rate_ok(user_id):
                return
            await self._on_button(chat_id, user_id, btn, msg)
            return

        if not text:
            return

        # نرمال‌سازی دستور (گروه/خصوصی)
        cmd = text.strip()
        # حذف منشن احتمالی ربات
        for prefix in ("@",):
            if cmd.startswith(prefix) and " " in cmd:
                cmd = cmd.split(" ", 1)[-1].strip()
        low = cmd.lower().lstrip("/").strip()
        first = low.split()[0] if low else ""

        is_group = str(chat_id).startswith("g0") or str(chat_id).startswith("c0")

        # در گروه فقط به دستورات شناخته‌شده جواب بده (اسپم نشه)
        group_cmds = {
            "start", "شروع", "help", "راهنما", "stats", "آمار", "info", "اطلاعات",
            "joke", "جوک", "hafez", "حافظ", "فال", "about", "درباره", "ping", "پینگ",
            "id", "آیدی", "me", "من", "time", "ساعت", "support", "پشتیبانی",
            "owner", "admin", "team", "تیم",
            "ban", "بن", "unban", "آنبن", "انبن", "mute", "سکوت", "unmute", "رفع‌سکوت", "رفع سکوت",
            "rules", "قوانین", "setrules", "تنظیم‌قوانین", "تنظیم قوانین",
            "welcome", "خوشامد", "setwelcome", "تنظیم‌خوشامد", "تنظیم خوشامد",
            "promote", "ادمین", "demote", "عزل", "mod", "مدیریت",
        }
        # شروع دستورات چندکلمه‌ای فارسی
        group_prefixes = ("تنظیم قوانین", "تنظیم خوشامد", "بن ", "آنبن ", "سکوت ", "قوانین", "خوشامد")
        if is_group and first not in group_cmds and not any(cmd.startswith(px) for px in group_prefixes) and cmd not in (
            "جوک", "حافظ", "فال", "آمار", "راهنما", "درباره", "پینگ", "آیدی", "تیم", "قوانین", "خوشامد",
        ):
            return

        if user_id and not self._rate_ok(user_id):
            return

        if first in ("start", "شروع") or cmd in ("/start", "start", "شروع"):
            await self.cmd_start(chat_id, user_id, is_group=is_group)
        elif first in ("help", "راهنما") or cmd in ("/help", "help", "راهنما"):
            await self.cmd_help(chat_id, is_group=is_group)
        elif first in ("owner",):
            await self.cmd_owner(chat_id, user_id, username)
        elif first in ("admin",):
            await self.cmd_admin(chat_id, user_id, username)
        elif first in ("stats", "آمار", "info", "اطلاعات") or cmd in ("آمار",):
            await self.cmd_stats(chat_id)
        elif first in ("joke", "جوک") or cmd in ("جوک",):
            await self.cmd_joke(chat_id)
        elif first in ("hafez", "حافظ", "فال") or cmd in ("حافظ", "فال"):
            await self.cmd_hafez(chat_id)
        elif first in ("about", "درباره") or cmd in ("درباره",):
            await self.cmd_about(chat_id)
        elif first in ("ping", "پینگ") or cmd in ("پینگ",):
            await self.safe_send(chat_id, "pong ✅")
        elif first in ("id", "آیدی", "me", "من") or cmd in ("آیدی",):
            await self.safe_send(
                chat_id,
                f"شناسه شما:\n`{user_id or '—'}`\nچت:\n`{chat_id}`",
            )
        elif first in ("time", "ساعت"):
            from datetime import datetime, timezone, timedelta
            tehran = datetime.now(timezone(timedelta(hours=3, minutes=30)))
            await self.safe_send(chat_id, f"🕰 {tehran.strftime('%Y-%m-%d %H:%M:%S')} (تهران)")
        elif first in ("support", "پشتیبانی"):
            await self.safe_send(chat_id, SUPPORT_TEXT)
        elif first in ("team", "تیم") or cmd in ("تیم",):
            await self._on_button(chat_id, user_id, "team", msg)
        elif first in ("rules", "قوانین") or cmd in ("قوانین",):
            await self.cmd_rules(chat_id)
        elif first in ("welcome", "خوشامد") or cmd in ("خوشامد",):
            await self.cmd_welcome(chat_id)
        elif first in ("mod", "مدیریت"):
            await self.cmd_mod_help(chat_id)
        elif cmd.startswith("تنظیم قوانین") or first in ("setrules", "تنظیم‌قوانین"):
            body = cmd.split("تنظیم قوانین", 1)[-1].strip() if "تنظیم قوانین" in cmd else cmd.split(maxsplit=1)[-1] if " " in cmd else ""
            await self.cmd_set_rules(chat_id, user_id, username, body)
        elif cmd.startswith("تنظیم خوشامد") or first in ("setwelcome", "تنظیم‌خوشامد"):
            body = cmd.split("تنظیم خوشامد", 1)[-1].strip() if "تنظیم خوشامد" in cmd else cmd.split(maxsplit=1)[-1] if " " in cmd else ""
            await self.cmd_set_welcome(chat_id, user_id, username, body)
        elif first in ("ban", "بن") or cmd.startswith("بن "):
            target = cmd.split(maxsplit=1)[1] if " " in cmd else ""
            await self.cmd_ban(chat_id, user_id, username, target)
        elif first in ("unban", "آنبن", "انبن") or cmd.startswith("آنبن "):
            target = cmd.split(maxsplit=1)[1] if " " in cmd else ""
            await self.cmd_unban(chat_id, user_id, username, target)
        elif first in ("mute", "سکوت") or cmd.startswith("سکوت "):
            target = cmd.split(maxsplit=1)[1] if " " in cmd else ""
            await self.cmd_mute(chat_id, user_id, username, target)
        elif first in ("promote", "ادمین"):
            target = cmd.split(maxsplit=1)[1] if " " in cmd else ""
            await self.cmd_promote(chat_id, user_id, username, target)
        elif first in ("demote", "عزل"):
            target = cmd.split(maxsplit=1)[1] if " " in cmd else ""
            await self.cmd_demote(chat_id, user_id, username, target)
        elif not is_group:
            await self._on_menu_text(chat_id, user_id, text)

    # ---------- commands ----------
    async def cmd_start(self, chat_id: str, user_id: str, is_group: bool = False) -> None:
        name = self.bot_name
        text = (
            f"سلام! 👋\n"
            f"من {name} نسخه روبیکا هستم.\n"
            f"دستورات: /help\n"
            f"نسخه: {BOT_VERSION}"
        )
        if is_group:
            await self.safe_send(chat_id, text)
        else:
            await self.safe_send(chat_id, text, chat_keypad=kb.USER_MAIN)

    async def cmd_help(self, chat_id: str, is_group: bool = False) -> None:
        text = (
            "📖 راهنمای MEGA BOT روبیکا\n\n"
            "عمومی:\n"
            "• /start — شروع\n"
            "• /help — راهنما\n"
            "• /stats یا آمار — آمار\n"
            "• جوک — جوک تصادفی\n"
            "• حافظ / فال — فال حافظ\n"
            "• پینگ — تست آنلاین بودن\n"
            "• آیدی — شناسه شما و چت\n"
            "• ساعت — ساعت تهران\n"
            "• درباره / پشتیبانی / تیم\n\n"
            "مدیریت:\n"
            "• /owner — پنل مالک\n"
            "• /admin — پنل ادمین\n\n"
            "در گروه فقط همین دستورات پاسخ داده می‌شوند."
        )
        if is_group:
            await self.safe_send(chat_id, text)
        else:
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

    async def cmd_owner(self, chat_id: str, user_id: str, username: str = "") -> None:
        if not self._is_owner(user_id, chat_id, username):
            await self.safe_send(
                chat_id,
                "⛔️ فقط مالک.\n"
                f"شناسه شما: `{user_id or '—'}`\n"
                f"یوزرنیم: @{username or '—'}\n"
                f"چت: `{chat_id}`\n"
                f"OWNER_ID: `{OWNER_ID}`\n"
                f"OWNER_USERNAME: @{OWNER_USERNAME}\n"
                "اگر مالک هستی یک‌بار در پیوی پیام بده تا یوزرنیم ثبت شود.",
            )
            return
        text = (
            f"👑 پنل مالک\n"
            f"شناسه: `{user_id}`\n"
            f"یوزرنیم: @{username or OWNER_USERNAME}\n"
            "از دکمه‌ها استفاده کن."
        )
        await self.safe_send(chat_id, text, chat_keypad=kb.OWNER_MENU)

    async def cmd_admin(self, chat_id: str, user_id: str, username: str = "") -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(
                chat_id,
                f"دسترسی نداری.\nشناسه شما: `{user_id or '—'}`",
            )
            return
        await self.safe_send(chat_id, "🛠 پنل ادمین / مدیریت گروه", chat_keypad=kb.ADMIN_MENU)

    async def cmd_mod_help(self, chat_id: str) -> None:
        await self.safe_send(
            chat_id,
            "🛡 دستورات مدیریت گروه\n\n"
            "• قوانین — نمایش قوانین\n"
            "• تنظیم قوانین <متن>\n"
            "• خوشامد — متن خوش‌آمد\n"
            "• تنظیم خوشامد <متن>\n"
            "• بن <user_id|@user> [دلیل]\n"
            "• آنبن <user_id|کدپرونده>\n"
            "• سکوت <user_id> [دلیل]\n"
            "• ادمین <user_id> — ادمین ربات در گروه\n"
            "• عزل <user_id>\n\n"
            "⚠️ بن واقعی پلتفرم فقط اگر API و دسترسی ادمین ربات اجازه بدهد؛ "
            "بن داخلی همیشه جلوی استفاده از ربات را می‌گیرد.",
        )

    async def cmd_rules(self, chat_id: str) -> None:
        gs = await self.db.get_group_settings(chat_id)
        rules = (gs.get("rules") or "").strip() or "هنوز قانونی تنظیم نشده.\nمالک/ادمین: تنظیم قوانین <متن>"
        await self.safe_send(chat_id, f"📜 قوانین گروه\n\n{rules}")

    async def cmd_welcome(self, chat_id: str) -> None:
        gs = await self.db.get_group_settings(chat_id)
        w = (gs.get("welcome") or "").strip() or "خوش‌آمد تنظیم نشده.\nتنظیم خوشامد <متن>"
        await self.safe_send(chat_id, f"👋 {w}")

    async def cmd_set_rules(self, chat_id: str, user_id: str, username: str, body: str) -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک/ادمین گروه.")
            return
        body = (body or "").strip()
        if not body:
            await self.safe_send(chat_id, "مثال: تنظیم قوانین احترام واجب است")
            return
        await self.db.set_group_rules(chat_id, body)
        await self.db.log_action(user_id, "set_rules", "group", chat_id, {"rules": body[:200]})
        await self.safe_send(chat_id, "✅ قوانین ذخیره شد.")

    async def cmd_set_welcome(self, chat_id: str, user_id: str, username: str, body: str) -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک/ادمین گروه.")
            return
        body = (body or "").strip()
        if not body:
            await self.safe_send(chat_id, "مثال: تنظیم خوشامد به گروه خوش اومدی")
            return
        await self.db.set_group_welcome(chat_id, body)
        await self.safe_send(chat_id, "✅ متن خوش‌آمد ذخیره شد.")

    async def _resolve_target(self, token: str) -> str | None:
        token = (token or "").strip()
        if not token:
            return None
        if token.startswith("@"):
            return await self.db.user_id_by_username(token)
        # user id خام
        return token.split()[0]

    async def cmd_ban(self, chat_id: str, user_id: str, username: str, target_raw: str) -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک/ادمین.")
            return
        parts = (target_raw or "").split(maxsplit=1)
        if not parts:
            await self.safe_send(chat_id, "مثال: بن u0xxxx دلیل")
            return
        target = await self._resolve_target(parts[0])
        reason = parts[1] if len(parts) > 1 else "بدون دلیل"
        if not target:
            await self.safe_send(chat_id, "هدف پیدا نشد. از user_id استفاده کن یا یک‌بار کاربر به ربات پیام داده باشد.")
            return
        code = await self.db.create_case("user", target, reason, user_id, permanent=True, action="ban")
        # تلاش برای بن پلتفرمی (ممکن است API رد کند)
        platform_ok = False
        try:
            await self.api.ban_chat_member(chat_id, target)
            platform_ok = True
        except Exception as e:
            log.warning("platform ban failed: %s", e)
        await self.db.log_action(user_id, "ban", "user", target, {"reason": reason, "case": code, "platform": platform_ok})
        extra = " + بن پلتفرم" if platform_ok else " (فقط بن داخلی ربات — API پلتفرم اجازه نداد یا ربات ادمین نیست)"
        await self.safe_send(chat_id, f"🚫 کاربر محدود شد.\nپرونده: #{code}\nدلیل: {reason}{extra}")

    async def cmd_unban(self, chat_id: str, user_id: str, username: str, target_raw: str) -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک/ادمین.")
            return
        token = (target_raw or "").strip().lstrip("#")
        if not token:
            await self.safe_send(chat_id, "مثال: آنبن 1001  یا  آنبن u0xxxx")
            return
        if token.isdigit():
            ok = await self.db.lift_case(int(token), user_id, "unban command")
            await self.safe_send(chat_id, "✅ پرونده بسته شد." if ok else "پرونده فعال پیدا نشد.")
            return
        target = await self._resolve_target(token) or token
        # همه پرونده‌های فعال این کاربر را ببند — ساده‌سازی: lift by creating note
        try:
            await self.api.unban_chat_member(chat_id, target)
        except Exception:
            pass
        await self.db.log_action(user_id, "unban_attempt", "user", target, {})
        await self.safe_send(chat_id, f"درخواست آنبن برای `{target}` ثبت شد. اگر کد پرونده داری با آنبن #کد بزن.")

    async def cmd_mute(self, chat_id: str, user_id: str, username: str, target_raw: str) -> None:
        if not await self._can_moderate(chat_id, user_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک/ادمین.")
            return
        parts = (target_raw or "").split(maxsplit=1)
        if not parts:
            await self.safe_send(chat_id, "مثال: سکوت u0xxxx")
            return
        target = await self._resolve_target(parts[0])
        reason = parts[1] if len(parts) > 1 else "سکوت"
        if not target:
            await self.safe_send(chat_id, "هدف نامعتبر.")
            return
        code = await self.db.create_case("user", target, reason, user_id, duration_days=1, action="mute")
        await self.safe_send(chat_id, f"🔇 سکوت داخلی ثبت شد.\nپرونده: #{code}")

    async def cmd_promote(self, chat_id: str, user_id: str, username: str, target_raw: str) -> None:
        if not self._is_owner(user_id, chat_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک می‌تواند ادمین ربات اضافه کند.")
            return
        target = await self._resolve_target(target_raw)
        if not target:
            await self.safe_send(chat_id, "مثال: ادمین u0xxxx")
            return
        await self.db.add_group_admin(chat_id, target, user_id)
        await self.safe_send(chat_id, f"✅ `{target}` ادمین ربات در این گروه شد.")

    async def cmd_demote(self, chat_id: str, user_id: str, username: str, target_raw: str) -> None:
        if not self._is_owner(user_id, chat_id, username):
            await self.safe_send(chat_id, "⛔️ فقط مالک.")
            return
        target = await self._resolve_target(target_raw)
        if not target:
            await self.safe_send(chat_id, "مثال: عزل u0xxxx")
            return
        await self.db.remove_group_admin(chat_id, target)
        await self.safe_send(chat_id, f"✅ `{target}` از ادمین‌های ربات برداشته شد.")

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
        if btn.startswith("own_") and self._is_owner(user_id, chat_id):
            await self._owner_action(chat_id, user_id, btn)
            return
        if btn.startswith("adm_") and self._is_owner(user_id, chat_id):
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
