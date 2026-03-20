from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from .models import AppConfig, RuntimeConfig, SourceConfig, TelegramConfig

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    rendered = ENV_PATTERN.sub(_replace_env, raw)
    payload = json.loads(rendered)

    runtime = payload.get("runtime", {})
    telegram = payload.get("telegram", {})
    sources = payload.get("sources", [])

    telegram_config = TelegramConfig(
        bot_token=_normalize_bot_token(_require_string(telegram, "bot_token")),
        chat_id=_optional_chat_id(telegram.get("chat_id")),
        message_thread_id=_optional_int(telegram.get("message_thread_id")),
        disable_web_page_preview=bool(telegram.get("disable_web_page_preview", False)),
    )

    runtime_config = RuntimeConfig(
        state_db_path=str(runtime.get("state_db_path", "data/state.sqlite3")),
        timeout_seconds=int(runtime.get("timeout_seconds", 20)),
        request_pause_seconds=float(runtime.get("request_pause_seconds", 1.5)),
        user_agent=str(runtime.get("user_agent", "ZurichHouseHunter/0.1")),
        bootstrap_mark_seen=bool(runtime.get("bootstrap_mark_seen", True)),
        max_notifications_per_run=int(runtime.get("max_notifications_per_run", 20)),
        dry_run=bool(runtime.get("dry_run", False)),
    )

    source_configs: List[SourceConfig] = []
    for source in sources:
        source_configs.append(
            SourceConfig(
                name=_require_string(source, "name"),
                kind=str(source.get("kind", "generic_link_cards")),
                search_url=_require_string(source, "search_url"),
                enabled=bool(source.get("enabled", True)),
                url_prefix=_optional_string(source.get("url_prefix")),
                item_url_regex=_optional_string(source.get("item_url_regex")),
                exclude_url_regexes=_string_list(source.get("exclude_url_regexes")),
                same_domain_only=bool(source.get("same_domain_only", True)),
                min_card_score=int(source.get("min_card_score", 2)),
                max_items=int(source.get("max_items", 25)),
                fetch_details=bool(source.get("fetch_details", True)),
                bootstrap_mark_seen=_optional_bool(source.get("bootstrap_mark_seen")),
                must_contain_any=_string_list(source.get("must_contain_any")),
                exclude_if_contains_any=_string_list(source.get("exclude_if_contains_any")),
                min_price_chf=_optional_float(source.get("min_price_chf")),
                max_price_chf=_optional_float(source.get("max_price_chf")),
                min_rooms=_optional_float(source.get("min_rooms")),
                max_rooms=_optional_float(source.get("max_rooms")),
                min_area_sqm=_optional_float(source.get("min_area_sqm")),
                max_area_sqm=_optional_float(source.get("max_area_sqm")),
            )
        )

    if not source_configs:
        raise ValueError("Config must define at least one source.")

    return AppConfig(runtime=runtime_config, telegram=telegram_config, sources=source_configs)


def _replace_env(match: re.Match) -> str:
    key = match.group(1)
    default = match.group(2)
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError("Missing required environment variable: {0}".format(key))
    return json.dumps(value)[1:-1]


def _require_string(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError("Missing required config value: {0}".format(key))
    return str(value)


def _string_list(value: Any) -> List[str]:
    if not value:
        return []
    return [str(item) for item in value]


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def _optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _normalize_bot_token(value: str) -> str:
    if value.startswith("$") and ":" in value:
        return value[1:]
    return value


def _optional_chat_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "0":
        return None
    return text
