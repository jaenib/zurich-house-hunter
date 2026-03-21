from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RuntimeConfig:
    state_db_path: str = "data/state.sqlite3"
    timeout_seconds: int = 20
    request_pause_seconds: float = 1.5
    user_agent: str = "ZurichHouseHunter/0.1"
    bootstrap_mark_seen: bool = True
    max_notifications_per_run: int = 20
    dry_run: bool = False


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: Optional[str] = None
    message_thread_id: Optional[int] = None
    disable_web_page_preview: bool = False


@dataclass
class MailboxConfig:
    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    use_ssl: bool = True


@dataclass
class SourceConfig:
    name: str
    kind: str
    search_url: str = ""
    enabled: bool = True
    url_prefix: Optional[str] = None
    item_url_regex: Optional[str] = None
    exclude_url_regexes: List[str] = field(default_factory=list)
    same_domain_only: bool = True
    min_card_score: int = 2
    max_items: int = 25
    fetch_details: bool = True
    bootstrap_mark_seen: Optional[bool] = None
    must_contain_any: List[str] = field(default_factory=list)
    exclude_if_contains_any: List[str] = field(default_factory=list)
    min_price_chf: Optional[float] = None
    max_price_chf: Optional[float] = None
    min_rooms: Optional[float] = None
    max_rooms: Optional[float] = None
    min_area_sqm: Optional[float] = None
    max_area_sqm: Optional[float] = None
    mailbox_name: Optional[str] = None
    email_from_contains_any: List[str] = field(default_factory=list)
    email_subject_contains_any: List[str] = field(default_factory=list)
    email_link_domains: List[str] = field(default_factory=list)
    email_max_messages: int = 25


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    telegram: TelegramConfig
    mailbox: Optional[MailboxConfig]
    sources: List[SourceConfig]


@dataclass
class ChatFilters:
    chat_id: str
    min_price_chf: Optional[float] = None
    max_price_chf: Optional[float] = None
    min_rooms: Optional[float] = None
    max_rooms: Optional[float] = None
    min_area_sqm: Optional[float] = None
    max_area_sqm: Optional[float] = None
    include_terms: List[str] = field(default_factory=list)
    exclude_terms: List[str] = field(default_factory=list)


@dataclass
class ChatTarget:
    chat_id: str
    chat_type: str = ""
    title: str = ""
    is_active: bool = True
    default_message_thread_id: Optional[int] = None


@dataclass
class Listing:
    source_name: str
    url: str
    canonical_key: str
    raw_text: str
    title: str = ""
    address: str = ""
    summary: str = ""
    price_text: str = ""
    price_chf: Optional[float] = None
    rooms: Optional[float] = None
    area_sqm: Optional[float] = None
    search_url: str = ""


@dataclass
class SourceRunStats:
    source_name: str
    fetched: int = 0
    matched: int = 0
    new_seen_on_bootstrap: int = 0
    notified: int = 0
    skipped_seen: int = 0
    skipped_filtered: int = 0
    errors: List[str] = field(default_factory=list)
