import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.extractors import HomegateExtractor, listing_from_text
from zurich_house_hunter.models import SourceConfig


HOMEGATE_HTML = """
<html>
  <body>
    <a href="/rent/4002392990">
      1 / 13 CHF 7,000.– Top 5.5 rooms 170m² living space 8038 Zürich
      Charmantes 5.5-Zimmer-Doppel-Einfamilienhaus mit Garten in Zürich-Wollishofen
    </a>
    <a href="/services/something">Create an Ad</a>
  </body>
</html>
"""


class ExtractorTests(unittest.TestCase):
    def test_homegate_extractor_finds_listing_cards(self):
        source = SourceConfig(
            name="homegate-houses-zurich",
            kind="homegate",
            search_url="https://www.homegate.ch/rent/house/city-zurich/matching-list",
            max_items=10,
        )

        listings = HomegateExtractor().extract(source, HOMEGATE_HTML)

        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.url, "https://www.homegate.ch/rent/4002392990")
        self.assertEqual(listing.price_chf, 7000.0)
        self.assertEqual(listing.rooms, 5.5)
        self.assertEqual(listing.area_sqm, 170.0)
        self.assertIn("Doppel-Einfamilienhaus", listing.title)

    def test_listing_from_text_parses_core_fields(self):
        source = SourceConfig(
            name="sample",
            kind="generic_link_cards",
            search_url="https://example.com/search",
        )
        listing = listing_from_text(
            source,
            "https://example.com/listing/1",
            "CHF 3,200.– 3.5 rooms 84m² living space Agleistrasse 9, 8046 Zürich Charmantes 3.5-Zimmer-Einfamilienhaus",
        )

        self.assertEqual(listing.price_chf, 3200.0)
        self.assertEqual(listing.rooms, 3.5)
        self.assertEqual(listing.area_sqm, 84.0)
        self.assertEqual(listing.address, "Agleistrasse 9, 8046 Zürich")

    def test_listing_from_aggregator_style_text_prefers_lead_text(self):
        source = SourceConfig(
            name="sample",
            kind="generic_link_cards",
            search_url="https://example.com/search",
        )
        listing = listing_from_text(
            source,
            "https://example.com/listing/1?utm_source=test",
            "Freistehender Bauernhausteil mit Charme in Bertschikon Dieser freistehende Bauernhausteil befindet sich am Dorfrand. Adresse 8614 Bertschikon Fläche 180 m^{2} Zimmer 5.5 Preis CHF 2'200 pro Monat",
        )

        self.assertEqual(listing.url, "https://example.com/listing/1")
        self.assertIn("Freistehender Bauernhausteil", listing.title)
        self.assertEqual(listing.address, "8614 Bertschikon")
        self.assertEqual(listing.rooms, 5.5)
        self.assertEqual(listing.area_sqm, 180.0)
        self.assertEqual(listing.price_chf, 2200.0)


if __name__ == "__main__":
    unittest.main()
