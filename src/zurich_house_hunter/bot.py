from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .http import HttpClient
from .logging_utils import log_event
from .models import AppConfig, ChatFilters, ChatTarget, SourceRunStats
from .service import HouseHunterService, apply_chat_filters_to_source
from .state import SeenListingStore
from .telegram import TelegramNotifier

UPDATE_OFFSET_KEY = "telegram_last_update_id"

NUMERIC_FILTER_FIELDS = {
    "min_price": "min_price_chf",
    "max_price": "max_price_chf",
    "budget": "max_price_chf",
    "price": "max_price_chf",
    "min_rooms": "min_rooms",
    "rooms": "min_rooms",
    "max_rooms": "max_rooms",
    "min_area": "min_area_sqm",
    "area": "min_area_sqm",
    "max_area": "max_area_sqm",
}

ACTIVE_MEMBER_STATUSES = {"member", "administrator", "creator"}


class GroupChatBot:
    def __init__(self, config: AppConfig, dry_run: bool = False) -> None:
        self._config = config
        self._dry_run = dry_run
        self._http_client = HttpClient(
            user_agent=config.runtime.user_agent,
            timeout_seconds=config.runtime.timeout_seconds,
            request_pause_seconds=config.runtime.request_pause_seconds,
        )
        self._telegram = TelegramNotifier(self._http_client, config.telegram, dry_run=dry_run)
        self._store = SeenListingStore(config.runtime.state_db_path)
        self._service = HouseHunterService(config, dry_run_override=dry_run)
        self._seed_configured_chat_target()

    def close(self) -> None:
        self._service.close()
        self._store.close()

    def serve(self, scrape_interval_seconds: int = 900, poll_timeout_seconds: int = 20) -> None:
        next_scrape_at = time.time()
        next_update_offset = self._load_next_update_offset()
        log_event(
            "bot",
            "bot loop active; first scrape starts immediately, known chats={0}".format(
                len(self._store.list_active_chat_targets())
            ),
        )

        while True:
            now = time.time()
            if now >= next_scrape_at:
                try:
                    self._run_scheduled_scrape()
                except Exception as exc:
                    self._emit_runtime_warning("scheduled scrape failed: {0}".format(exc))
                next_scrape_at = time.time() + scrape_interval_seconds

            seconds_until_scrape = max(1, int(next_scrape_at - time.time()))
            try:
                updates = self._telegram.get_updates(
                    offset=next_update_offset,
                    timeout_seconds=min(max(1, poll_timeout_seconds), seconds_until_scrape),
                )
            except Exception as exc:
                self._emit_runtime_warning("polling failed: {0}".format(exc))
                time.sleep(2)
                continue
            if updates:
                log_event("bot", "received {0} Telegram update(s)".format(len(updates)))
            for update in updates:
                update_id = int(update.get("update_id", 0))
                next_update_offset = max(next_update_offset, update_id + 1)
                self._save_next_update_offset(next_update_offset)
                try:
                    self._handle_update(update)
                except Exception as exc:
                    self._emit_runtime_warning("update handling failed: {0}".format(exc))

    def _run_scheduled_scrape(self) -> None:
        targets = self._store.list_active_chat_targets()
        if not targets:
            log_event("bot", "no active chat targets registered yet; waiting for DM, group command, or add event")
            return
        log_event("bot", "starting scheduled scrape for {0} active chat target(s)".format(len(targets)))
        for target in targets:
            filters = self._store.get_chat_filters(target.chat_id)
            stats = self._service.run_once(
                chat_filters=filters,
                scope_key=target.chat_id,
                destination_chat_id=target.chat_id,
                destination_thread_id=target.default_message_thread_id,
            )
            errors = [error for item in stats for error in item.errors]
            log_event(
                "bot",
                "target {0}: {1}".format(
                    target.chat_id,
                    build_run_summary(stats).replace("\n", " | "),
                ),
            )
            if errors and not self._dry_run:
                self._telegram.send_text(
                    "Scrape run finished with errors:\n- " + "\n- ".join(errors[:5]),
                    chat_id=target.chat_id,
                    message_thread_id=target.default_message_thread_id,
                )

    def _handle_update(self, update: Dict[str, object]) -> None:
        if isinstance(update.get("my_chat_member"), dict):
            self._handle_membership_update(update["my_chat_member"])
            return

        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        self._handle_message_update(message)

    def _handle_message_update(self, message: Dict[str, object]) -> None:
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return

        incoming_thread_id = _optional_int(message.get("message_thread_id"))
        if not self._chat_is_in_scope(chat_id, incoming_thread_id):
            return

        self._register_chat_from_chat_payload(chat, default_message_thread_id=incoming_thread_id)

        text = message.get("text")
        if not isinstance(text, str) or not text.strip().startswith("/"):
            return

        command, args = parse_command(text)
        if not command:
            return

        log_event("bot", "handling command /{0} from chat {1}".format(command, chat_id))
        response = self._dispatch_command(command, args, chat_id, incoming_thread_id)
        if response:
            self._telegram.send_text(
                response,
                chat_id=chat_id,
                message_thread_id=incoming_thread_id,
                reply_to_message_id=_optional_int(message.get("message_id")),
            )

    def _handle_membership_update(self, payload: Dict[str, object]) -> None:
        chat = payload.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return
        new_chat_member = payload.get("new_chat_member")
        status = ""
        if isinstance(new_chat_member, dict):
            status = str(new_chat_member.get("status", ""))
        is_active = status in ACTIVE_MEMBER_STATUSES if status else True
        self._register_chat_from_chat_payload(chat, is_active=is_active)
        log_event(
            "bot",
            "membership update for chat {0}: status={1}, active={2}".format(chat_id, status or "unknown", is_active),
        )

    def _dispatch_command(
        self,
        command: str,
        args: List[str],
        chat_id: str,
        message_thread_id: Optional[int],
    ) -> str:
        filters = self._store.get_chat_filters(chat_id)

        if command in {"help", "start"}:
            return build_help_message()
        if command in {"status", "filters"}:
            return build_status_message(
                self._config,
                filters,
                self._store.list_active_chat_targets(),
                current_chat=self._store.get_chat_target(chat_id),
                current_message_thread_id=message_thread_id,
            )
        if command in {"whereami", "chat"}:
            return build_whereami_message(
                self._store.get_chat_target(chat_id),
                current_message_thread_id=message_thread_id,
            )
        if command == "set":
            return self._handle_set_command(filters, args)
        if command == "include":
            return self._handle_term_append(filters, args, include=True)
        if command == "exclude":
            return self._handle_term_append(filters, args, include=False)
        if command == "clear":
            return self._handle_clear_command(filters, args)
        if command in {"run", "check"}:
            stats = self._service.run_once(
                chat_filters=filters,
                scope_key=chat_id,
                destination_chat_id=chat_id,
                destination_thread_id=message_thread_id,
            )
            return build_run_summary(stats)

        return "Unknown command. Use /help."

    def _handle_set_command(self, filters: ChatFilters, args: List[str]) -> str:
        if len(args) < 2:
            return "Usage: /set <max_price|min_price|min_rooms|max_rooms|min_area|max_area> <value>"
        field_key = args[0].strip().lower()
        field_name = NUMERIC_FILTER_FIELDS.get(field_key)
        if field_name is None:
            return "Unknown filter field. Use /help."
        try:
            value = float(args[1])
        except ValueError:
            return "Filter values must be numeric."
        setattr(filters, field_name, value)
        self._store.save_chat_filters(filters)
        return "Updated {0} to {1:g}.".format(field_name, value)

    def _handle_term_append(self, filters: ChatFilters, args: List[str], include: bool) -> str:
        if not args:
            return "Usage: /{0} <term>".format("include" if include else "exclude")
        term = " ".join(args).strip()
        if not term:
            return "Term cannot be empty."
        target = filters.include_terms if include else filters.exclude_terms
        if term.lower() not in [item.lower() for item in target]:
            target.append(term)
        self._store.save_chat_filters(filters)
        return "Added {0} term: {1}".format("include" if include else "exclude", term)

    def _handle_clear_command(self, filters: ChatFilters, args: List[str]) -> str:
        if not args:
            return "Usage: /clear <field|include|exclude|all>"
        field_key = args[0].strip().lower()
        if field_key == "all":
            filters.min_price_chf = None
            filters.max_price_chf = None
            filters.min_rooms = None
            filters.max_rooms = None
            filters.min_area_sqm = None
            filters.max_area_sqm = None
            filters.include_terms = []
            filters.exclude_terms = []
            self._store.save_chat_filters(filters)
            return "Cleared all chat overrides."
        if field_key == "include":
            filters.include_terms = []
            self._store.save_chat_filters(filters)
            return "Cleared include terms."
        if field_key == "exclude":
            filters.exclude_terms = []
            self._store.save_chat_filters(filters)
            return "Cleared exclude terms."
        field_name = NUMERIC_FILTER_FIELDS.get(field_key)
        if field_name is None:
            return "Unknown field to clear. Use /help."
        setattr(filters, field_name, None)
        self._store.save_chat_filters(filters)
        return "Cleared {0}.".format(field_name)

    def _seed_configured_chat_target(self) -> None:
        if not self._config.telegram.chat_id:
            return
        self._store.upsert_chat_target(
            self._config.telegram.chat_id,
            chat_type="configured",
            title="Configured default chat",
            is_active=True,
            default_message_thread_id=self._config.telegram.message_thread_id,
        )

    def _register_chat_from_chat_payload(
        self,
        chat: Dict[str, object],
        is_active: bool = True,
        default_message_thread_id: Optional[int] = None,
        ) -> None:
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return
        previous = self._store.get_chat_target(chat_id)
        title = _chat_title(chat)
        chat_type = str(chat.get("type", ""))
        self._store.upsert_chat_target(
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            is_active=is_active,
            default_message_thread_id=default_message_thread_id,
        )
        current = self._store.get_chat_target(chat_id)
        if _should_log_chat_registration(previous, current):
            log_event("bot", "registered chat target: {0}".format(format_chat_target(current)))

    def _chat_is_in_scope(self, chat_id: str, message_thread_id: Optional[int]) -> bool:
        configured_chat_id = self._config.telegram.chat_id
        configured_thread_id = self._config.telegram.message_thread_id
        if configured_chat_id and configured_thread_id is not None and chat_id == configured_chat_id:
            return message_thread_id == configured_thread_id
        return True

    def _load_next_update_offset(self) -> int:
        raw_value = self._store.get_bot_value(UPDATE_OFFSET_KEY)
        if raw_value is None:
            return 0
        try:
            return int(raw_value)
        except ValueError:
            return 0

    def _save_next_update_offset(self, offset: int) -> None:
        self._store.set_bot_value(UPDATE_OFFSET_KEY, str(offset))

    def _emit_runtime_warning(self, message: str) -> None:
        log_event("bot", message)


def parse_command(text: str) -> Tuple[str, List[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    command = parts[0]
    if not command.startswith("/"):
        return "", []
    normalized = command[1:].split("@", 1)[0].lower()
    return normalized, parts[1:]


def build_help_message() -> str:
    return "\n".join(
        [
            "Available commands:",
            "/status or /filters",
            "/whereami",
            "/set max_price 8000",
            "/set min_rooms 4.5",
            "/set min_area 120",
            "/include chalet",
            "/exclude temporary",
            "/clear max_price",
            "/clear include",
            "/clear all",
            "/run",
            "",
            "This bot auto-registers DMs and groups when it sees updates there.",
        ]
    )


def build_status_message(
    config: AppConfig,
    chat_filters: ChatFilters,
    active_targets: List[ChatTarget],
    current_chat: Optional[ChatTarget] = None,
    current_message_thread_id: Optional[int] = None,
) -> str:
    lines = ["Current chat overrides:"]
    if current_chat is not None:
        lines.append("Current target: {0}".format(format_chat_target(current_chat)))
    else:
        lines.append("Current target: {0}".format(chat_filters.chat_id))
    if current_message_thread_id is not None:
        lines.append("Current topic: {0}".format(current_message_thread_id))
    lines.append("")
    lines.append("- min_price_chf: {0}".format(format_optional_number(chat_filters.min_price_chf)))
    lines.append("- max_price_chf: {0}".format(format_optional_number(chat_filters.max_price_chf)))
    lines.append("- min_rooms: {0}".format(format_optional_number(chat_filters.min_rooms)))
    lines.append("- max_rooms: {0}".format(format_optional_number(chat_filters.max_rooms)))
    lines.append("- min_area_sqm: {0}".format(format_optional_number(chat_filters.min_area_sqm)))
    lines.append("- max_area_sqm: {0}".format(format_optional_number(chat_filters.max_area_sqm)))
    lines.append("- include_terms: {0}".format(", ".join(chat_filters.include_terms) if chat_filters.include_terms else "none"))
    lines.append("- exclude_terms: {0}".format(", ".join(chat_filters.exclude_terms) if chat_filters.exclude_terms else "none"))
    lines.append("")
    lines.append("Enabled sources:")
    for source in config.sources:
        if not source.enabled:
            continue
        effective_source = apply_chat_filters_to_source(source, chat_filters)
        lines.append(
            "- {0}: max_price={1}, min_rooms={2}, min_area={3}".format(
                source.name,
                format_optional_number(effective_source.max_price_chf),
                format_optional_number(effective_source.min_rooms),
                format_optional_number(effective_source.min_area_sqm),
            )
        )
    lines.append("")
    lines.append("Active chat targets: {0}".format(len(active_targets)))
    return "\n".join(lines)


def build_whereami_message(current_chat: Optional[ChatTarget], current_message_thread_id: Optional[int] = None) -> str:
    lines = ["Current Telegram target:"]
    if current_chat is None:
        lines.append("- chat: unknown")
    else:
        lines.append("- chat: {0}".format(format_chat_target(current_chat)))
    if current_message_thread_id is not None:
        lines.append("- topic: {0}".format(current_message_thread_id))
    return "\n".join(lines)


def build_run_summary(stats: List[SourceRunStats]) -> str:
    lines = ["Manual run finished:"]
    for item in stats:
        lines.append(
            "- {0}: fetched={1}, matched={2}, notified={3}, seen={4}, filtered={5}".format(
                item.source_name,
                item.fetched,
                item.matched,
                item.notified,
                item.skipped_seen,
                item.skipped_filtered,
            )
        )
        for error in item.errors:
            lines.append("  error: {0}".format(error))
    return "\n".join(lines)


def format_optional_number(value: Optional[float]) -> str:
    if value is None:
        return "source default"
    return "{0:g}".format(value)


def format_chat_target(target: Optional[ChatTarget]) -> str:
    if target is None:
        return "unknown"
    details = [target.chat_id]
    if target.chat_type:
        details.append(target.chat_type)
    if target.title:
        details.append(target.title)
    if target.default_message_thread_id is not None:
        details.append("topic {0}".format(target.default_message_thread_id))
    return " | ".join(details)


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chat_title(chat: Dict[str, object]) -> str:
    title = str(chat.get("title", "")).strip()
    if title:
        return title
    first_name = str(chat.get("first_name", "")).strip()
    last_name = str(chat.get("last_name", "")).strip()
    username = str(chat.get("username", "")).strip()
    combined = " ".join(part for part in [first_name, last_name] if part).strip()
    if combined:
        return combined
    if username:
        return "@{0}".format(username)
    return ""


def _should_log_chat_registration(previous: Optional[ChatTarget], current: Optional[ChatTarget]) -> bool:
    if current is None:
        return False
    if previous is None:
        return True
    return (
        previous.chat_type != current.chat_type
        or previous.title != current.title
        or previous.is_active != current.is_active
        or previous.default_message_thread_id != current.default_message_thread_id
    )
