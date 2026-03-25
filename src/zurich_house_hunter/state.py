from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from .models import ChatFilters, ChatTarget

GLOBAL_SCOPE_KEY = "__global__"


class SeenListingStore:
    def __init__(self, path: str) -> None:
        self._path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._ensure_schema()

    def close(self) -> None:
        self._connection.close()

    def get_bot_value(self, key: str) -> Optional[str]:
        cursor = self._connection.execute(
            "SELECT value FROM bot_state WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def set_bot_value(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO bot_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utc_now()),
        )
        self._connection.commit()

    def get_chat_filters(self, chat_id: str) -> ChatFilters:
        cursor = self._connection.execute(
            "SELECT settings_json FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return ChatFilters(chat_id=chat_id)
        payload = json.loads(row[0])
        return ChatFilters(
            chat_id=chat_id,
            min_price_chf=_optional_float(payload.get("min_price_chf")),
            max_price_chf=_optional_float(payload.get("max_price_chf")),
            min_rooms=_optional_float(payload.get("min_rooms")),
            max_rooms=_optional_float(payload.get("max_rooms")),
            min_area_sqm=_optional_float(payload.get("min_area_sqm")),
            max_area_sqm=_optional_float(payload.get("max_area_sqm")),
            include_terms=_string_list(payload.get("include_terms")),
            exclude_terms=_string_list(payload.get("exclude_terms")),
        )

    def save_chat_filters(self, filters: ChatFilters) -> None:
        payload = {
            "min_price_chf": filters.min_price_chf,
            "max_price_chf": filters.max_price_chf,
            "min_rooms": filters.min_rooms,
            "max_rooms": filters.max_rooms,
            "min_area_sqm": filters.min_area_sqm,
            "max_area_sqm": filters.max_area_sqm,
            "include_terms": filters.include_terms,
            "exclude_terms": filters.exclude_terms,
        }
        self._connection.execute(
            """
            INSERT INTO chat_settings (chat_id, settings_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at
            """,
            (filters.chat_id, json.dumps(payload, ensure_ascii=True, sort_keys=True), utc_now()),
        )
        self._connection.commit()

    def upsert_chat_target(
        self,
        chat_id: str,
        chat_type: str = "",
        title: str = "",
        is_active: bool = True,
        default_message_thread_id: Optional[int] = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO known_chats (chat_id, chat_type, title, is_active, default_message_thread_id, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = CASE
                    WHEN excluded.chat_type = '' THEN known_chats.chat_type
                    ELSE excluded.chat_type
                END,
                title = CASE
                    WHEN excluded.title = '' THEN known_chats.title
                    ELSE excluded.title
                END,
                is_active = excluded.is_active,
                default_message_thread_id = COALESCE(excluded.default_message_thread_id, known_chats.default_message_thread_id),
                last_seen_at = excluded.last_seen_at
            """,
            (
                chat_id,
                chat_type,
                title,
                1 if is_active else 0,
                default_message_thread_id,
                utc_now(),
            ),
        )
        self._connection.commit()

    def get_chat_target(self, chat_id: str) -> Optional[ChatTarget]:
        cursor = self._connection.execute(
            """
            SELECT chat_id, chat_type, title, is_active, default_message_thread_id
            FROM known_chats
            WHERE chat_id = ?
            LIMIT 1
            """,
            (chat_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return ChatTarget(
            chat_id=str(row[0]),
            chat_type=str(row[1] or ""),
            title=str(row[2] or ""),
            is_active=bool(row[3]),
            default_message_thread_id=row[4],
        )

    def list_active_chat_targets(self) -> List[ChatTarget]:
        cursor = self._connection.execute(
            """
            SELECT chat_id, chat_type, title, is_active, default_message_thread_id
            FROM known_chats
            WHERE is_active = 1
            ORDER BY chat_id
            """
        )
        rows = cursor.fetchall()
        return [
            ChatTarget(
                chat_id=str(row[0]),
                chat_type=str(row[1] or ""),
                title=str(row[2] or ""),
                is_active=bool(row[3]),
                default_message_thread_id=row[4],
            )
            for row in rows
        ]

    def source_seen_count(self, source_name: str, scope_key: str = GLOBAL_SCOPE_KEY) -> int:
        cursor = self._connection.execute(
            "SELECT COUNT(*) FROM scoped_seen_listings WHERE scope_key = ? AND source_name = ?",
            (scope_key, source_name),
        )
        return int(cursor.fetchone()[0])

    def has_seen(self, source_name: str, canonical_key: str, scope_key: str = GLOBAL_SCOPE_KEY) -> bool:
        cursor = self._connection.execute(
            """
            SELECT 1
            FROM scoped_seen_listings
            WHERE scope_key = ? AND source_name = ? AND canonical_key = ?
            LIMIT 1
            """,
            (scope_key, source_name, canonical_key),
        )
        return cursor.fetchone() is not None

    def mark_seen(
        self,
        source_name: str,
        canonical_key: str,
        title: str,
        url: str,
        scope_key: str = GLOBAL_SCOPE_KEY,
    ) -> None:
        now = utc_now()
        self._connection.execute(
            """
            INSERT INTO scoped_seen_listings (scope_key, source_name, canonical_key, title, url, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_key, source_name, canonical_key)
            DO UPDATE SET title = excluded.title, url = excluded.url, last_seen_at = excluded.last_seen_at
            """,
            (scope_key, source_name, canonical_key, title, url, now, now),
        )
        self._connection.commit()

    def touch(self, source_name: str, canonical_key: str, scope_key: str = GLOBAL_SCOPE_KEY) -> None:
        self._connection.execute(
            """
            UPDATE scoped_seen_listings
            SET last_seen_at = ?
            WHERE scope_key = ? AND source_name = ? AND canonical_key = ?
            """,
            (utc_now(), scope_key, source_name, canonical_key),
        )
        self._connection.commit()

    def has_sink_delivery(self, sink_name: str, canonical_key: str) -> bool:
        cursor = self._connection.execute(
            """
            SELECT 1
            FROM sink_deliveries
            WHERE sink_name = ? AND canonical_key = ?
            LIMIT 1
            """,
            (sink_name, canonical_key),
        )
        return cursor.fetchone() is not None

    def mark_sink_delivery(self, sink_name: str, canonical_key: str, title: str, url: str) -> None:
        now = utc_now()
        self._connection.execute(
            """
            INSERT INTO sink_deliveries (sink_name, canonical_key, title, url, first_delivered_at, last_delivered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sink_name, canonical_key)
            DO UPDATE SET title = excluded.title, url = excluded.url, last_delivered_at = excluded.last_delivered_at
            """,
            (sink_name, canonical_key, title, url, now, now),
        )
        self._connection.commit()

    def _ensure_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                source_name TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (source_name, canonical_key)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scoped_seen_listings (
                scope_key TEXT NOT NULL,
                source_name TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (scope_key, source_name, canonical_key)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT NOT NULL PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id TEXT NOT NULL PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id TEXT NOT NULL PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                default_message_thread_id INTEGER,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sink_deliveries (
                sink_name TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                first_delivered_at TEXT NOT NULL,
                last_delivered_at TEXT NOT NULL,
                PRIMARY KEY (sink_name, canonical_key)
            )
            """
        )
        self._connection.commit()


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _string_list(value) -> list:
    if not value:
        return []
    return [str(item) for item in value]
