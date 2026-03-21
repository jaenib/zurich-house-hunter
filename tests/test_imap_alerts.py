import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.imap_alerts import AlertEmailMessage, extract_email_alert_listings, message_matches_source, unwrap_redirect_url
from zurich_house_hunter.models import SourceConfig


EMAIL_HTML = """
<html>
  <body>
    <a href="https://tracking.example/redirect?url=https%3A%2F%2Fwww.homegate.ch%2Frent%2F4002392990%3Futm_source%3Dalert">
      CHF 7,000.– 5.5 rooms 170m² living space 8038 Zürich
      Charmantes 5.5-Zimmer-Doppel-Einfamilienhaus mit Garten in Zürich-Wollishofen
    </a>
    <a href="https://tracking.example/unsubscribe">unsubscribe</a>
  </body>
</html>
"""


class ImapAlertTests(unittest.TestCase):
    def test_unwrap_redirect_url_prefers_embedded_target(self):
        url = unwrap_redirect_url(
            "https://tracking.example/redirect?url=https%3A%2F%2Fwww.homegate.ch%2Frent%2F4002392990%3Futm_source%3Dalert"
        )
        self.assertEqual(url, "https://www.homegate.ch/rent/4002392990")

    def test_extract_email_alert_listings_from_html_anchor(self):
        source = SourceConfig(
            name="homegate-email-alerts",
            kind="imap_link_alerts",
            enabled=True,
            fetch_details=False,
            email_link_domains=["homegate.ch"],
            email_from_contains_any=["homegate"],
            email_subject_contains_any=["Suchabo"],
            exclude_url_regexes=["unsubscribe"],
            max_price_chf=8000,
            min_rooms=4,
        )
        message = AlertEmailMessage(
            uid=101,
            sender="alerts@homegate.ch",
            subject="Suchabo: Neue Treffer in Zürich",
            html_body=EMAIL_HTML,
            text_body="Neue Treffer in Zürich",
        )

        listings = extract_email_alert_listings(source, message)

        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.url, "https://www.homegate.ch/rent/4002392990")
        self.assertEqual(listing.price_chf, 7000.0)
        self.assertEqual(listing.rooms, 5.5)
        self.assertEqual(listing.area_sqm, 170.0)
        self.assertIn("Doppel-Einfamilienhaus", listing.title)

    def test_message_matches_source_uses_sender_and_subject_filters(self):
        source = SourceConfig(
            name="newhome-alerts",
            kind="imap_link_alerts",
            email_from_contains_any=["newhome.ch"],
            email_subject_contains_any=["Suchabo"],
        )
        message = AlertEmailMessage(
            uid=1,
            sender="alerts@newhome.ch",
            subject="Ihr Suchabo hat neue Treffer",
        )
        self.assertTrue(message_matches_source(source, message))
        self.assertFalse(
            message_matches_source(
                source,
                AlertEmailMessage(uid=2, sender="noreply@example.com", subject="Ihr Suchabo hat neue Treffer"),
            )
        )


if __name__ == "__main__":
    unittest.main()
