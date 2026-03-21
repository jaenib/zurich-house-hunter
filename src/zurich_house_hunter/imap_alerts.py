from __future__ import annotations

from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
import imaplib
import re
from typing import List, Optional
from urllib.parse import parse_qsl, unquote, urlsplit

from .extractors import canonicalize_url, clean_text, listing_from_text
from .html_tools import extract_anchors
from .models import Listing, MailboxConfig, SourceConfig

PLAIN_URL_RE = re.compile(r"https?://[^\s<>\"]+")
REDIRECT_PARAM_KEYS = {
    "url",
    "u",
    "target",
    "redirect",
    "redirect_url",
    "destination",
    "dest",
    "href",
    "link",
    "continue",
}


@dataclass
class AlertEmailMessage:
    uid: int
    sender: str
    subject: str
    html_body: str = ""
    text_body: str = ""


class ImapAlertClient:
    def __init__(self, config: MailboxConfig) -> None:
        self._config = config

    def fetch_messages(self, source: SourceConfig, min_uid: int = 0) -> List[AlertEmailMessage]:
        mailbox_name = source.mailbox_name or self._config.mailbox
        connection = self._connect()
        try:
            self._login(connection)
            status, _ = connection.select(mailbox_name, readonly=True)
            if status != "OK":
                raise RuntimeError("Failed to select IMAP mailbox: {0}".format(mailbox_name))
            status, data = connection.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError("Failed to search IMAP mailbox: {0}".format(mailbox_name))
            raw_uids = data[0].split() if data and data[0] else []
            candidate_uids = [int(item) for item in raw_uids if int(item) > min_uid]
            candidate_uids = candidate_uids[-source.email_max_messages :]

            messages: List[AlertEmailMessage] = []
            for uid in candidate_uids:
                status, fetch_data = connection.uid("fetch", str(uid), "(BODY.PEEK[])")
                if status != "OK":
                    raise RuntimeError("Failed to fetch IMAP message UID {0}".format(uid))
                raw_message = _extract_raw_message(fetch_data)
                if raw_message is None:
                    continue
                messages.append(_decode_email_message(uid, raw_message))
            return messages
        finally:
            try:
                connection.close()
            except Exception:
                pass
            try:
                connection.logout()
            except Exception:
                pass

    def _connect(self):
        if self._config.use_ssl:
            return imaplib.IMAP4_SSL(self._config.host, self._config.port)
        return imaplib.IMAP4(self._config.host, self._config.port)

    def _login(self, connection) -> None:
        status, _ = connection.login(self._config.username, self._config.password)
        if status != "OK":
            raise RuntimeError("Failed to authenticate against IMAP server.")


def message_matches_source(source: SourceConfig, message: AlertEmailMessage) -> bool:
    if source.email_from_contains_any:
        sender = message.sender.lower()
        if not any(pattern.lower() in sender for pattern in source.email_from_contains_any):
            return False
    if source.email_subject_contains_any:
        subject = message.subject.lower()
        if not any(pattern.lower() in subject for pattern in source.email_subject_contains_any):
            return False
    return True


def extract_email_alert_listings(source: SourceConfig, message: AlertEmailMessage) -> List[Listing]:
    seen_urls = set()
    listings: List[Listing] = []
    compiled_exclusions = [re.compile(pattern) for pattern in source.exclude_url_regexes]

    if message.html_body:
        for anchor in extract_anchors(message.html_body):
            listing = _listing_from_link(
                source=source,
                href=anchor.href,
                raw_text=" ".join(part for part in [anchor.title, anchor.text] if part),
                fallback_text=_email_fallback_text(message),
                compiled_exclusions=compiled_exclusions,
            )
            if listing is None or listing.url in seen_urls:
                continue
            seen_urls.add(listing.url)
            listings.append(listing)

    if not listings and message.text_body:
        for url in PLAIN_URL_RE.findall(message.text_body):
            listing = _listing_from_link(
                source=source,
                href=url,
                raw_text=message.subject,
                fallback_text=_email_fallback_text(message),
                compiled_exclusions=compiled_exclusions,
            )
            if listing is None or listing.url in seen_urls:
                continue
            seen_urls.add(listing.url)
            listings.append(listing)

    return listings


def _listing_from_link(
    source: SourceConfig,
    href: str,
    raw_text: str,
    fallback_text: str,
    compiled_exclusions,
) -> Optional[Listing]:
    url = unwrap_redirect_url(href)
    if not url:
        return None
    if any(pattern.search(url) for pattern in compiled_exclusions):
        return None
    if source.email_link_domains and not _url_matches_domains(url, source.email_link_domains):
        return None
    effective_text = clean_text(raw_text) or fallback_text or url
    listing = listing_from_text(source, url, effective_text)
    if listing.summary == effective_text and fallback_text and fallback_text != effective_text:
        listing.summary = fallback_text[:320]
    if not listing.title:
        listing.title = effective_text[:180]
    return listing


def unwrap_redirect_url(url: str, max_depth: int = 3) -> str:
    current = clean_text(url).strip("<>.,;")
    for _ in range(max_depth):
        split = urlsplit(current)
        if split.scheme not in {"http", "https"}:
            return ""
        next_url = ""
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            if key.lower() not in REDIRECT_PARAM_KEYS:
                continue
            decoded = unquote(value).strip()
            if decoded.startswith("http://") or decoded.startswith("https://"):
                next_url = decoded
                break
        if not next_url:
            return canonicalize_url(current)
        current = next_url
    return canonicalize_url(current)


def _url_matches_domains(url: str, domains: List[str]) -> bool:
    hostname = urlsplit(url).netloc.lower()
    for domain in domains:
        normalized = domain.lower().strip()
        if not normalized:
            continue
        if hostname == normalized or hostname.endswith(".{0}".format(normalized)):
            return True
    return False


def _decode_email_message(uid: int, raw_message: bytes) -> AlertEmailMessage:
    message = message_from_bytes(raw_message)
    html_parts: List[str] = []
    text_parts: List[str] = []

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                continue
            decoded = _decode_message_part(part)
            if not decoded:
                continue
            content_type = part.get_content_type()
            if content_type == "text/html":
                html_parts.append(decoded)
            elif content_type == "text/plain":
                text_parts.append(decoded)
    else:
        decoded = _decode_message_part(message)
        if message.get_content_type() == "text/html":
            html_parts.append(decoded)
        else:
            text_parts.append(decoded)

    return AlertEmailMessage(
        uid=uid,
        sender=_decode_header_value(message.get("From", "")),
        subject=_decode_header_value(message.get("Subject", "")),
        html_body="\n".join(part for part in html_parts if part),
        text_body="\n".join(part for part in text_parts if part),
    )


def _decode_message_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _decode_header_value(value: str) -> str:
    decoded_parts: List[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                decoded_parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded_parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(chunk)
    return clean_text("".join(decoded_parts))


def _extract_raw_message(fetch_data) -> Optional[bytes]:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def _email_fallback_text(message: AlertEmailMessage) -> str:
    base = clean_text(" ".join(part for part in [message.subject, message.text_body] if part))
    return base[:320]
