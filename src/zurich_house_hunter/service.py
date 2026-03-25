from __future__ import annotations

from dataclasses import replace
import time
from typing import List

from .extractors import build_extractor
from .filters import matches_filters
from .google_sheet import GoogleSheetWriter
from .http import HttpClient
from .imap_alerts import ImapAlertClient, extract_email_alert_listings, message_matches_source
from .logging_utils import log_event
from .models import AppConfig, ChatFilters, Listing, SourceConfig, SourceRunStats
from .state import GLOBAL_SCOPE_KEY, SeenListingStore
from .telegram import TelegramNotifier

GOOGLE_SHEET_SINK_NAME = "google_sheet"


class HouseHunterService:
    def __init__(self, config: AppConfig, dry_run_override: bool = False) -> None:
        self._config = config
        effective_dry_run = config.runtime.dry_run or dry_run_override
        self._http_client = HttpClient(
            user_agent=config.runtime.user_agent,
            timeout_seconds=config.runtime.timeout_seconds,
            request_pause_seconds=config.runtime.request_pause_seconds,
        )
        self._store = SeenListingStore(config.runtime.state_db_path)
        self._notifier = TelegramNotifier(self._http_client, config.telegram, dry_run=effective_dry_run)
        self._google_sheet = (
            GoogleSheetWriter(self._http_client, config.google_sheet, dry_run=effective_dry_run)
            if config.google_sheet is not None and config.google_sheet.enabled
            else None
        )
        self._imap_client = ImapAlertClient(config.mailbox) if config.mailbox is not None else None
        self._dry_run = effective_dry_run

    def close(self) -> None:
        self._store.close()

    def run_once(
        self,
        chat_filters: ChatFilters = None,
        scope_key: str = GLOBAL_SCOPE_KEY,
        destination_chat_id: str = None,
        destination_thread_id: int = None,
    ) -> List[SourceRunStats]:
        run_started_at = time.time()
        stats: List[SourceRunStats] = []
        notifications_sent = 0
        log_event(
            "scraper",
            "run started (dry_run={0}, chat_filters={1})".format(
                "yes" if self._dry_run else "no",
                "yes" if chat_filters is not None else "no",
            ),
        )

        for source in self._effective_sources(chat_filters):
            if not source.enabled:
                continue
            source_stats = SourceRunStats(source_name=source.name)
            source_started_at = time.time()
            try:
                if source.kind == "imap_link_alerts":
                    notifications_sent = self._run_imap_source(
                        source=source,
                        source_stats=source_stats,
                        scope_key=scope_key,
                        destination_chat_id=destination_chat_id,
                        destination_thread_id=destination_thread_id,
                        notifications_sent=notifications_sent,
                    )
                else:
                    notifications_sent = self._run_web_source(
                        source=source,
                        source_stats=source_stats,
                        scope_key=scope_key,
                        destination_chat_id=destination_chat_id,
                        destination_thread_id=destination_thread_id,
                        notifications_sent=notifications_sent,
                    )
            except Exception as exc:
                source_stats.errors.append(str(exc))
                log_event(
                    "scraper",
                    "source {0}: error after {1:.1f}s: {2}".format(
                        source.name,
                        time.time() - source_started_at,
                        exc,
                    ),
                )
            stats.append(source_stats)
        log_event(
            "scraper",
            "run finished in {0:.1f}s with {1} total notifications".format(
                time.time() - run_started_at,
                notifications_sent,
            ),
        )
        return stats

    def _run_web_source(
        self,
        source: SourceConfig,
        source_stats: SourceRunStats,
        scope_key: str,
        destination_chat_id: str,
        destination_thread_id: int,
        notifications_sent: int,
    ) -> int:
        log_event("scraper", "fetching source {0}".format(source.name))
        page_html = self._http_client.get_text(source.search_url)
        extractor = build_extractor(source.kind)
        candidates = extractor.extract(source, page_html)
        source_stats.fetched = len(candidates)
        log_event("scraper", "source {0}: fetched {1} candidate links".format(source.name, source_stats.fetched))
        return self._process_candidate_listings(
            source=source,
            source_stats=source_stats,
            candidates=candidates,
            scope_key=scope_key,
            destination_chat_id=destination_chat_id,
            destination_thread_id=destination_thread_id,
            notifications_sent=notifications_sent,
            extractor=extractor,
        )

    def _run_imap_source(
        self,
        source: SourceConfig,
        source_stats: SourceRunStats,
        scope_key: str,
        destination_chat_id: str,
        destination_thread_id: int,
        notifications_sent: int,
    ) -> int:
        if self._imap_client is None:
            raise RuntimeError("No mailbox config loaded for imap_link_alerts source.")
        cursor_key = "imap_last_uid:{0}".format(source.name)
        min_uid = _safe_int(self._store.get_bot_value(cursor_key))
        log_event("scraper", "fetching email alerts for source {0} (last_uid={1})".format(source.name, min_uid))
        messages = self._imap_client.fetch_messages(source, min_uid=min_uid)
        candidates: List[Listing] = []
        last_uid = min_uid
        for message in messages:
            last_uid = max(last_uid, message.uid)
            if not message_matches_source(source, message):
                if not self._dry_run:
                    self._store.set_bot_value(cursor_key, str(message.uid))
                continue
            candidates.extend(extract_email_alert_listings(source, message))
            if not self._dry_run:
                self._store.set_bot_value(cursor_key, str(message.uid))
        source_stats.fetched = len(candidates)
        log_event(
            "scraper",
            "source {0}: fetched {1} candidate links from {2} email(s), last_uid={3}".format(
                source.name,
                source_stats.fetched,
                len(messages),
                last_uid,
            ),
        )
        return self._process_candidate_listings(
            source=source,
            source_stats=source_stats,
            candidates=candidates,
            scope_key=scope_key,
            destination_chat_id=destination_chat_id,
            destination_thread_id=destination_thread_id,
            notifications_sent=notifications_sent,
            extractor=None,
        )

    def _process_candidate_listings(
        self,
        source: SourceConfig,
        source_stats: SourceRunStats,
        candidates: List[Listing],
        scope_key: str,
        destination_chat_id: str,
        destination_thread_id: int,
        notifications_sent: int,
        extractor,
    ) -> int:
        filtered = []
        for listing in candidates:
            if matches_filters(listing, source):
                filtered.append(listing)
            else:
                source_stats.skipped_filtered += 1
        source_stats.matched = len(filtered)
        log_event(
            "scraper",
            "source {0}: {1} matched, {2} filtered out".format(
                source.name,
                source_stats.matched,
                source_stats.skipped_filtered,
            ),
        )

        if self._should_bootstrap(source, scope_key=scope_key) and not self._dry_run:
            for listing in filtered:
                self._store.mark_seen(
                    source.name,
                    listing.canonical_key,
                    listing.title,
                    listing.url,
                    scope_key=scope_key,
                )
            source_stats.new_seen_on_bootstrap = len(filtered)
            log_event(
                "scraper",
                "source {0}: bootstrap mode marked {1} listings as seen".format(
                    source.name,
                    source_stats.new_seen_on_bootstrap,
                ),
            )
            return notifications_sent

        for listing in filtered:
            if self._store.has_seen(source.name, listing.canonical_key, scope_key=scope_key):
                if not self._dry_run:
                    self._store.touch(source.name, listing.canonical_key, scope_key=scope_key)
                source_stats.skipped_seen += 1
                continue
            if notifications_sent >= self._config.runtime.max_notifications_per_run:
                log_event("scraper", "notification cap reached for this run")
                break
            final_listing = self._maybe_enrich_listing(source, listing, extractor)
            if not matches_filters(final_listing, source):
                source_stats.skipped_filtered += 1
                continue
            self._notifier.send_listing(
                final_listing,
                chat_id=destination_chat_id,
                message_thread_id=destination_thread_id,
            )
            self._append_google_sheet_row(final_listing, source_stats)
            if not self._dry_run:
                self._store.mark_seen(
                    source.name,
                    final_listing.canonical_key,
                    final_listing.title,
                    final_listing.url,
                    scope_key=scope_key,
                )
            source_stats.notified += 1
            notifications_sent += 1
        log_event(
            "scraper",
            "source {0}: notified={1}, seen={2}, finished".format(
                source.name,
                source_stats.notified,
                source_stats.skipped_seen,
            ),
        )
        return notifications_sent

    def _should_bootstrap(self, source: SourceConfig, scope_key: str = GLOBAL_SCOPE_KEY) -> bool:
        bootstrap_setting = source.bootstrap_mark_seen
        if bootstrap_setting is None:
            bootstrap_setting = self._config.runtime.bootstrap_mark_seen
        if not bootstrap_setting:
            return False
        return self._store.source_seen_count(source.name, scope_key=scope_key) == 0

    def _maybe_enrich_listing(self, source: SourceConfig, listing: Listing, extractor) -> Listing:
        if not source.fetch_details or extractor is None:
            return listing
        detail_html = self._http_client.get_text(listing.url)
        return extractor.enrich(listing, detail_html)

    def _append_google_sheet_row(self, listing: Listing, source_stats: SourceRunStats) -> None:
        if self._google_sheet is None:
            return
        if self._store.has_sink_delivery(GOOGLE_SHEET_SINK_NAME, listing.canonical_key):
            return
        try:
            self._google_sheet.append_listing(listing)
        except Exception as exc:
            message = "google_sheet append failed for {0}: {1}".format(listing.canonical_key, exc)
            source_stats.errors.append(message)
            log_event("scraper", message)
            return
        if not self._dry_run:
            self._store.mark_sink_delivery(
                GOOGLE_SHEET_SINK_NAME,
                listing.canonical_key,
                listing.title,
                listing.url,
            )

    def _effective_sources(self, chat_filters: ChatFilters = None) -> List[SourceConfig]:
        if chat_filters is None:
            return list(self._config.sources)
        return [apply_chat_filters_to_source(source, chat_filters) for source in self._config.sources]


def apply_chat_filters_to_source(source: SourceConfig, chat_filters: ChatFilters) -> SourceConfig:
    return replace(
        source,
        min_price_chf=chat_filters.min_price_chf
        if chat_filters.min_price_chf is not None
        else source.min_price_chf,
        max_price_chf=chat_filters.max_price_chf
        if chat_filters.max_price_chf is not None
        else source.max_price_chf,
        min_rooms=chat_filters.min_rooms if chat_filters.min_rooms is not None else source.min_rooms,
        max_rooms=chat_filters.max_rooms if chat_filters.max_rooms is not None else source.max_rooms,
        min_area_sqm=chat_filters.min_area_sqm
        if chat_filters.min_area_sqm is not None
        else source.min_area_sqm,
        max_area_sqm=chat_filters.max_area_sqm
        if chat_filters.max_area_sqm is not None
        else source.max_area_sqm,
        must_contain_any=merge_terms(source.must_contain_any, chat_filters.include_terms),
        exclude_if_contains_any=merge_terms(source.exclude_if_contains_any, chat_filters.exclude_terms),
    )


def merge_terms(base_terms: List[str], extra_terms: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for term in list(base_terms) + list(extra_terms):
        normalized = term.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
