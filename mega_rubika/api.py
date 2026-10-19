"""
Rubika Bot API client — مستقل از بله.
مستندات پایه: https://botapi.rubika.ir/v3/{token}/{method}
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Optional

import aiohttp

from .config import RUBIKA_API_BASE, REQUEST_TIMEOUT

log = logging.getLogger("mega_rubika.api")


class RubikaAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class RubikaAPI:
    """کلاینت async ساده و مقاوم برای Bot API روبیکا."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("token خالی است")
        self.token = token
        self.base = f"{RUBIKA_API_BASE}/{token}"
        self.session: aiohttp.ClientSession | None = None
        self._failures = 0

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***TOKEN***") if text else text

    async def start(self) -> None:
        await self._ensure_session(force=True)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def _ensure_session(self, force: bool = False) -> aiohttp.ClientSession:
        if self.session and not self.session.closed and not force:
            return self.session
        if self.session and not self.session.closed:
            try:
                await self.session.close()
            except Exception:
                pass
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT + 5,
            connect=10,
            sock_connect=10,
            sock_read=REQUEST_TIMEOUT,
        )
        connector = aiohttp.TCPConnector(limit=25, ttl_dns_cache=300, enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self.session

    async def _post(self, method: str, data: dict | None = None) -> dict:
        await self._ensure_session()
        url = f"{self.base}/{method}"
        payload = data or {}
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                assert self.session is not None
                async with self.session.post(url, json=payload) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status >= 400:
                        raise RubikaAPIError(
                            f"HTTP {resp.status} on {method}: {self._redact(str(body))}",
                            status=resp.status,
                            payload=body,
                        )
                    if not isinstance(body, dict):
                        self._failures = 0
                        return {"data": body}
                    status = body.get("status")
                    # statusهای موفق رایج روبیکا
                    if status is not None and str(status).upper() not in (
                        "OK", "SUCCESS", "200", "TRUE", "1"
                    ) and body.get("success") is False:
                        raise RubikaAPIError(
                            f"API error on {method}: {self._redact(str(body))}",
                            payload=body,
                        )
                    self._failures = 0
                    return body
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                self._failures += 1
                log.warning("network error %s (attempt %s): %s", method, attempt + 1, e)
                if self._failures >= 3:
                    await self._ensure_session(force=True)
                await asyncio.sleep(0.6 * (attempt + 1))
        raise RubikaAPIError(f"failed after retries: {method}: {last_err}")

    # ---------- متدهای اصلی ----------

    async def get_me(self) -> dict:
        return await self._post("getMe")

    async def get_updates(self, limit: int = 100, offset_id: str | None = None) -> dict:
        data: dict[str, Any] = {"limit": limit}
        if offset_id:
            data["offset_id"] = offset_id
        return await self._post("getUpdates", data)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        chat_keypad: dict | None = None,
        inline_keypad: dict | None = None,
        chat_keypad_type: str | None = None,
        reply_to_message_id: str | None = None,
        disable_notification: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        if chat_keypad is not None:
            payload["chat_keypad"] = chat_keypad
            payload["chat_keypad_type"] = chat_keypad_type or "New"
        if inline_keypad is not None:
            payload["inline_keypad"] = inline_keypad
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self._post("sendMessage", payload)

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        *,
        inline_keypad: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if inline_keypad is not None:
            payload["inline_keypad"] = inline_keypad
        return await self._post("editMessageText", payload)

    async def delete_message(self, chat_id: str, message_id: str) -> dict:
        return await self._post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    async def answer_callback(
        self,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {"callback_id": callback_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        # نام متد در نسخه‌های مختلف ممکن است فرق کند؛ رایج‌ترین:
        for method in ("answerCallbackQuery", "sendAction", "answerInlineQuery"):
            try:
                return await self._post(method, payload)
            except RubikaAPIError:
                continue
        return {}

    async def ban_chat_member(self, chat_id: str, user_id: str) -> dict:
        """در صورت پشتیبانی API. اگر خطا داد، مدیریت در لایه بالاتر."""
        return await self._post("banChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def unban_chat_member(self, chat_id: str, user_id: str) -> dict:
        return await self._post("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def get_chat(self, chat_id: str) -> dict:
        return await self._post("getChat", {"chat_id": chat_id})

    async def get_chat_administrators(self, chat_id: str) -> dict:
        return await self._post("getChatAdministrators", {"chat_id": chat_id})
