from __future__ import annotations

import json
from typing import List

from .http import HttpClient
from .models import GoogleSheetConfig, Listing

GOOGLE_SHEET_HEADERS = [
    "Adresse",
    "\u00d6VMinHB",
    "VeloMinHB",
    "CHF",
    "AnzZimmer",
    "CHF/Zimmer",
    "HouseFlat",
    "Link",
    "BigNoNos",
]

HOUSE_TERMS = [
    "haus",
    "house",
    "einfamilienhaus",
    "doppeleinfamilienhaus",
    "doppel-einfamilienhaus",
    "reihenhaus",
    "bauernhaus",
    "villa",
    "chalet",
    "rustico",
]
FLAT_TERMS = [
    "wohnung",
    "apartment",
    "flat",
    "duplexwohnung",
    "attika",
]


class GoogleSheetWriter:
    def __init__(self, http_client: HttpClient, config: GoogleSheetConfig, dry_run: bool = False) -> None:
        self._http_client = http_client
        self._config = config
        self._dry_run = dry_run

    def append_listing(self, listing: Listing) -> None:
        payload = {
            "sheet_name": self._config.sheet_name,
            "headers_json": json.dumps(GOOGLE_SHEET_HEADERS, ensure_ascii=True),
            "row_json": json.dumps(build_google_sheet_row(listing), ensure_ascii=True),
        }
        if self._config.webhook_secret:
            payload["secret"] = self._config.webhook_secret

        if self._dry_run:
            print("Google Sheet row:")
            print(payload["row_json"])
            print("")
            return

        response = self._http_client.post_form(self._config.webhook_url, payload)
        if response.get("ok") is False:
            raise RuntimeError(
                "Google Sheet append failed: {0}".format(response.get("description") or response.get("error") or "unknown error")
            )


def build_google_sheet_row(listing: Listing) -> List[object]:
    price_per_room = ""
    if listing.price_chf is not None and listing.rooms not in {None, 0}:
        price_per_room = round(listing.price_chf / float(listing.rooms), 2)
    return [
        listing.address or "",
        "",
        "",
        listing.price_chf if listing.price_chf is not None else "",
        listing.rooms if listing.rooms is not None else "",
        price_per_room,
        infer_house_flat(listing),
        listing.url,
        "",
    ]


def infer_house_flat(listing: Listing) -> str:
    haystack = " ".join(part for part in [listing.title, listing.summary, listing.raw_text, listing.source_name] if part).lower()
    if any(term in haystack for term in HOUSE_TERMS):
        return "house"
    if any(term in haystack for term in FLAT_TERMS):
        return "flat"
    return ""
