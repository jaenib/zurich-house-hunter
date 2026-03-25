from __future__ import annotations

import json
from html import escape
from typing import Dict, List, Optional

from .http import HttpClient
from .models import Listing, TelegramConfig


class TelegramNotifier:
    def __init__(self, http_client: HttpClient, config: TelegramConfig, dry_run: bool = False) -> None:
        self._http_client = http_client
        self._config = config
        self._dry_run = dry_run

    def send_listing(
        self,
        listing: Listing,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
    ) -> None:
        message = build_listing_message(listing)
        self.send_html(
            message,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            disable_web_page_preview=True,
        )

    def send_html(
        self,
        message: str,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        disable_web_page_preview: Optional[bool] = None,
    ) -> None:
        if self._dry_run:
            print(message)
            print("")
            return

        effective_chat_id = chat_id or self._config.chat_id
        if not effective_chat_id:
            raise RuntimeError("Telegram chat_id is missing. Use bot-loop to auto-register chats or set telegram.chat_id.")

        effective_disable_web_page_preview = self._config.disable_web_page_preview
        if disable_web_page_preview is not None:
            effective_disable_web_page_preview = disable_web_page_preview
        payload = {
            "chat_id": effective_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true" if effective_disable_web_page_preview else "false",
        }
        effective_thread_id = message_thread_id
        if effective_thread_id is None:
            effective_thread_id = self._config.message_thread_id
        if effective_thread_id is not None:
            payload["message_thread_id"] = str(effective_thread_id)
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        url = "https://api.telegram.org/bot{0}/sendMessage".format(self._config.bot_token)
        response = self._http_client.post_form(url, payload)
        if not response.get("ok"):
            raise RuntimeError("Telegram send failed: {0}".format(response.get("description", "unknown error")))

    def send_text(
        self,
        message: str,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        self.send_html(
            escape(message),
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
        )

    def get_updates(self, offset: Optional[int] = None, timeout_seconds: int = 20) -> List[Dict[str, object]]:
        payload = {
            "timeout": str(timeout_seconds),
            "allowed_updates": json.dumps(["message", "edited_message", "my_chat_member"]),
        }
        if offset is not None:
            payload["offset"] = str(offset)
        url = "https://api.telegram.org/bot{0}/getUpdates".format(self._config.bot_token)
        response = self._http_client.post_form(url, payload, timeout_seconds=timeout_seconds + 15)
        if not response.get("ok"):
            raise RuntimeError("Telegram getUpdates failed: {0}".format(response.get("description", "unknown error")))
        result = response.get("result", [])
        return result if isinstance(result, list) else []


def build_listing_message(listing: Listing) -> str:
    lines = ['<a href="{0}">Open listing</a>'.format(escape(listing.url, quote=True))]
    if listing.address:
        lines.append("Address: {0}".format(escape(listing.address)))
    if listing.price_text:
        lines.append("Price: {0}".format(escape(listing.price_text)))
    elif listing.price_chf is not None:
        lines.append("Price: CHF {0:g}".format(listing.price_chf))
    if listing.rooms is not None:
        lines.append("Rooms: {0:g}".format(listing.rooms))
    return "\n".join(lines)
