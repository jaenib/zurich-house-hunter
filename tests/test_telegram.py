import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.models import Listing, TelegramConfig
from zurich_house_hunter.telegram import TelegramNotifier, build_listing_message


class _DummyHttpClient:
    def __init__(self) -> None:
        self.calls = []

    def post_form(self, url, payload, timeout_seconds=None):
        self.calls.append(
            {
                "url": url,
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"ok": True, "result": {}}


class TelegramTests(unittest.TestCase):
    def test_build_listing_message_is_compact(self):
        listing = Listing(
            source_name="sample-source",
            url="https://example.com/listing/1",
            canonical_key="https://example.com/listing/1",
            raw_text="raw",
            title="Big house",
            address="Fuchsweg 4b 8044 Gockhausen",
            summary="Long summary that should not be shown",
            price_text="CHF 6'100",
            price_chf=6100.0,
            rooms=5.5,
            area_sqm=169.0,
        )

        message = build_listing_message(listing)

        self.assertEqual(
            message,
            '<a href="https://example.com/listing/1">Open listing</a>\n'
            "Address: Fuchsweg 4b 8044 Gockhausen\n"
            "Price: CHF 6&#x27;100\n"
            "Rooms: 5.5",
        )
        self.assertNotIn("Source:", message)
        self.assertNotIn("Area:", message)
        self.assertNotIn("Long summary", message)
        self.assertNotIn("Big house", message)

    def test_send_listing_disables_preview(self):
        http_client = _DummyHttpClient()
        notifier = TelegramNotifier(
            http_client,
            TelegramConfig(
                bot_token="token",
                chat_id="123",
                disable_web_page_preview=False,
            ),
        )
        listing = Listing(
            source_name="sample-source",
            url="https://example.com/listing/1",
            canonical_key="https://example.com/listing/1",
            raw_text="raw",
            address="8044 Gockhausen",
            price_text="CHF 6'100",
            rooms=5.5,
        )

        notifier.send_listing(listing)

        self.assertEqual(len(http_client.calls), 1)
        self.assertEqual(http_client.calls[0]["payload"]["disable_web_page_preview"], "true")


if __name__ == "__main__":
    unittest.main()
