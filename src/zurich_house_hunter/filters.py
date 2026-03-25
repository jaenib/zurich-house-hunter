from __future__ import annotations

from .models import Listing, SourceConfig


def matches_filters(listing: Listing, source: SourceConfig) -> bool:
    haystack = " ".join(
        part for part in [listing.title, listing.address, listing.summary, listing.raw_text] if part
    ).lower()

    if source.allowed_postal_codes_any:
        allowed_codes = {str(code).strip() for code in source.allowed_postal_codes_any if str(code).strip()}
        if not listing.postal_code or listing.postal_code not in allowed_codes:
            return False
    if source.must_contain_any and not any(term.lower() in haystack for term in source.must_contain_any):
        return False
    if source.exclude_if_contains_any and any(term.lower() in haystack for term in source.exclude_if_contains_any):
        return False
    if source.min_price_chf is not None and (listing.price_chf is None or listing.price_chf < source.min_price_chf):
        return False
    if source.max_price_chf is not None and (listing.price_chf is None or listing.price_chf > source.max_price_chf):
        return False
    if source.min_rooms is not None and (listing.rooms is None or listing.rooms < source.min_rooms):
        return False
    if source.max_rooms is not None and (listing.rooms is None or listing.rooms > source.max_rooms):
        return False
    if source.min_area_sqm is not None and (listing.area_sqm is None or listing.area_sqm < source.min_area_sqm):
        return False
    if source.max_area_sqm is not None and (listing.area_sqm is None or listing.area_sqm > source.max_area_sqm):
        return False
    return True
