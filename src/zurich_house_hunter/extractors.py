from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .html_tools import extract_anchors, extract_metadata
from .models import Listing, SourceConfig

PRICE_RE = re.compile(r"CHF\s*([\d'’.,]+)")
ROOMS_RE = re.compile(
    r"(?:(\d+(?:[.,]\d+)?)\s*[- ]?\s*(?:rooms?|zimmer)\b|(?:rooms?|zimmer)\s*(\d+(?:[.,]\d+)?))",
    re.IGNORECASE,
)
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2|m\s*2|sqm|m\^\{2\})", re.IGNORECASE)
POSTAL_CITY_RE = re.compile(
    r"\d{4}\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+(?:\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+)?"
)
ADDRESS_LABEL_RE = re.compile(
    r"(?:Adresse|Address)\s+(.+?)(?=\s+(?:Fläche|Area|Zimmer|Rooms|Preis|Price)\b|$)",
    re.IGNORECASE,
)
CARD_COUNTER_RE = re.compile(r"^\d+\s*/\s*\d+\s*")
WHITESPACE_RE = re.compile(r"\s+")


class BaseExtractor:
    def extract(self, source: SourceConfig, html: str) -> List[Listing]:
        raise NotImplementedError

    def enrich(self, listing: Listing, html: str) -> Listing:
        metadata = extract_metadata(html)
        if metadata.canonical_url:
            listing.url = canonicalize_url(metadata.canonical_url)
            listing.canonical_key = listing.url
        detail_title = metadata.og_title or metadata.title
        detail_summary = metadata.og_description or metadata.description
        if detail_title:
            listing.title = clean_text(detail_title)
        if detail_summary:
            listing.summary = clean_text(detail_summary)
        return listing


class GenericLinkCardExtractor(BaseExtractor):
    def extract(self, source: SourceConfig, html: str) -> List[Listing]:
        anchors = extract_anchors(html)
        listings: List[Listing] = []
        seen_urls: Dict[str, bool] = {}
        search_host = urlsplit(source.search_url).netloc.lower()
        url_regex = re.compile(source.item_url_regex) if source.item_url_regex else None
        excluded_url_regexes = [re.compile(pattern) for pattern in source.exclude_url_regexes]

        for anchor in anchors:
            href = anchor.href.strip()
            if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                continue
            url = canonicalize_url(urljoin(source.url_prefix or source.search_url, href))
            target_host = urlsplit(url).netloc.lower()
            if source.same_domain_only and target_host != search_host:
                continue
            if any(pattern.search(url) for pattern in excluded_url_regexes):
                continue
            raw_text = clean_text(" ".join(part for part in [anchor.title, anchor.text] if part))
            if not raw_text:
                continue
            score = card_score(raw_text)
            if url_regex and not url_regex.search(urlsplit(url).path):
                if score < max(source.min_card_score, 3):
                    continue
            elif score < source.min_card_score:
                continue
            if url in seen_urls:
                continue
            listing = listing_from_text(source, url, raw_text)
            listings.append(listing)
            seen_urls[url] = True
            if len(listings) >= source.max_items:
                break
        return listings


class HomegateExtractor(GenericLinkCardExtractor):
    def extract(self, source: SourceConfig, html: str) -> List[Listing]:
        effective_source = SourceConfig(
            name=source.name,
            kind=source.kind,
            search_url=source.search_url,
            enabled=source.enabled,
            url_prefix=source.url_prefix or "https://www.homegate.ch",
            item_url_regex=source.item_url_regex or r"^/(rent|buy)/\d+$",
            exclude_url_regexes=source.exclude_url_regexes,
            same_domain_only=source.same_domain_only,
            min_card_score=max(source.min_card_score, 2),
            max_items=source.max_items,
            fetch_details=source.fetch_details,
            bootstrap_mark_seen=source.bootstrap_mark_seen,
            must_contain_any=source.must_contain_any,
            exclude_if_contains_any=source.exclude_if_contains_any,
            min_price_chf=source.min_price_chf,
            max_price_chf=source.max_price_chf,
            min_rooms=source.min_rooms,
            max_rooms=source.max_rooms,
            min_area_sqm=source.min_area_sqm,
            max_area_sqm=source.max_area_sqm,
        )
        return super().extract(effective_source, html)


def build_extractor(kind: str) -> BaseExtractor:
    if kind == "homegate":
        return HomegateExtractor()
    if kind == "generic_link_cards":
        return GenericLinkCardExtractor()
    raise ValueError("Unsupported source kind: {0}".format(kind))


def listing_from_text(source: SourceConfig, url: str, raw_text: str) -> Listing:
    canonical_url = canonicalize_url(url)
    cleaned = clean_text(raw_text)
    price_match = PRICE_RE.search(cleaned)
    rooms_match = ROOMS_RE.search(cleaned)
    area_match = AREA_RE.search(cleaned)
    address = extract_address(cleaned)
    price_text = "CHF {0}".format(price_match.group(1)) if price_match else ""
    price_chf = parse_number(price_match.group(1)) if price_match else None
    rooms = parse_number(first_present_group(rooms_match)) if rooms_match else None
    area_sqm = parse_number(area_match.group(1)) if area_match else None

    title = guess_title(cleaned, address)
    summary = guess_summary(cleaned, title)

    return Listing(
        source_name=source.name,
        url=canonical_url,
        canonical_key=canonical_url,
        raw_text=cleaned,
        title=title,
        address=address,
        summary=summary,
        price_text=price_text,
        price_chf=price_chf,
        rooms=rooms,
        area_sqm=area_sqm,
        search_url=source.search_url,
    )


def clean_text(value: str) -> str:
    repaired = repair_mojibake_text(value)
    return WHITESPACE_RE.sub(" ", repaired.replace("\xa0", " ").strip())


def canonicalize_url(url: str) -> str:
    split = urlsplit(url)
    query_pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        if key.lower().startswith("utm_"):
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs)
    return urlunsplit((split.scheme or "https", split.netloc, split.path, query, ""))


def card_score(text: str) -> int:
    score = 0
    lowered = text.lower()
    if "chf" in lowered:
        score += 1
    if ROOMS_RE.search(text):
        score += 1
    if AREA_RE.search(text):
        score += 1
    if POSTAL_CITY_RE.search(text):
        score += 1
    return score


def repair_mojibake_text(text: str) -> str:
    if not any(marker in text for marker in ["Ã", "Â", "â"]):
        return text
    try:
        repaired = text.encode("latin-1", errors="ignore").decode("utf-8")
    except UnicodeDecodeError:
        return text
    return repaired if repaired.count("Ã") < text.count("Ã") else text


def parse_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    normalized = raw.replace("’", "").replace("'", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        head, tail = normalized.rsplit(",", 1)
        if len(tail) == 3 and head.isdigit():
            normalized = head + tail
        else:
            normalized = normalized.replace(",", ".")
    elif "." in normalized:
        head, tail = normalized.rsplit(".", 1)
        if len(tail) == 3 and head.replace(".", "").isdigit():
            normalized = normalized.replace(".", "")
    normalized = re.sub(r"[^0-9.]", "", normalized).strip(".")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def first_present_group(match: re.Match) -> Optional[str]:
    for group_index in range(1, (match.lastindex or 0) + 1):
        value = match.group(group_index)
        if value:
            return value
    return None


def guess_title(text: str, address: str) -> str:
    trimmed = CARD_COUNTER_RE.sub("", text)
    for marker in ["Travel time", "Travel Time"]:
        trimmed = trimmed.split(marker, 1)[0].strip()

    lead_segment = trimmed
    for marker in [" Adresse ", " Address ", " Fläche ", " Area ", " Zimmer ", " Rooms ", " Preis ", " Price "]:
        if marker in lead_segment:
            lead_segment = lead_segment.split(marker, 1)[0].strip()
    lead_segment = clean_text(lead_segment)

    start_index = 0
    for pattern in [PRICE_RE, ROOMS_RE, AREA_RE]:
        match = pattern.search(trimmed)
        if match:
            start_index = max(start_index, match.end())
    if address:
        address_match = trimmed.find(address)
        if address_match >= 0:
            start_index = max(start_index, address_match + len(address))
    candidate = clean_text(trimmed[start_index:])
    candidate = re.sub(r"^(Premium|Top|New building)\s+", "", candidate, flags=re.IGNORECASE)
    if not candidate:
        candidate = trimmed
    if candidate.lower() in {"pro monat", "per month", "par mois"} or len(candidate) < 10:
        candidate = lead_segment or candidate
    return candidate[:180].strip(" -")


def guess_summary(text: str, title: str) -> str:
    if not title:
        return text[:320]
    summary = text
    if summary.startswith(title):
        summary = summary[len(title) :].strip(" -")
    return summary[:320]


def trim_address(address: str) -> str:
    if not address:
        return ""
    street_postal_match = re.search(
        r"^(.*?,\s*\d{4}\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+(?:\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+)?)",
        address,
    )
    if street_postal_match:
        return clean_text(street_postal_match.group(1))
    postal_only_match = re.search(
        r"^(\d{4}\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+(?:\s+[A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ.-]+)?)",
        address,
    )
    if postal_only_match:
        return clean_text(postal_only_match.group(1))
    return address


def extract_address(text: str) -> str:
    label_match = ADDRESS_LABEL_RE.search(text)
    if label_match:
        return trim_address(clean_text(label_match.group(1)))
    postal_match = POSTAL_CITY_RE.search(text)
    if not postal_match:
        return ""
    postal_city = normalize_postal_city(postal_match.group(0))
    before = text[: postal_match.start()]
    street_match = re.search(
        r"([A-ZÄÖÜÀ-ÿ][A-Za-zÄÖÜÀ-ÿ./-]+(?:\s+[A-Za-zÄÖÜÀ-ÿ./-]+){0,4}\s+\d+[A-Za-z]?)\s*,\s*$",
        before,
    )
    if street_match:
        street = clean_text(street_match.group(1))
        if street:
            return "{0}, {1}".format(street, postal_city)
    return trim_address(postal_city)


def normalize_postal_city(value: str) -> str:
    tokens = clean_text(value).split()
    if len(tokens) <= 2:
        return " ".join(tokens)
    if len(tokens) >= 3 and tokens[1].endswith("."):
        return " ".join(tokens[:3])
    return " ".join(tokens[:2])
