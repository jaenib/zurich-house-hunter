import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.filters import matches_filters
from zurich_house_hunter.models import Listing, SourceConfig


class FilterTests(unittest.TestCase):
    def test_postal_code_allowlist_accepts_matching_listing(self):
        source = SourceConfig(
            name="sample",
            kind="generic_link_cards",
            search_url="https://example.com/search",
            allowed_postal_codes_any=["8008", "8044", "8702"],
        )
        listing = Listing(
            source_name="sample",
            url="https://example.com/listing/1",
            canonical_key="https://example.com/listing/1",
            raw_text="8044 Gockhausen",
            address="Fuchsweg 4b 8044 Gockhausen",
            postal_code="8044",
            title="Family house",
        )

        self.assertTrue(matches_filters(listing, source))

    def test_postal_code_allowlist_rejects_non_matching_listing(self):
        source = SourceConfig(
            name="sample",
            kind="generic_link_cards",
            search_url="https://example.com/search",
            allowed_postal_codes_any=["8008", "8044", "8702"],
        )
        listing = Listing(
            source_name="sample",
            url="https://example.com/listing/2",
            canonical_key="https://example.com/listing/2",
            raw_text="8422 Pfungen",
            address="Rebbergstrasse 1 8422 Pfungen",
            postal_code="8422",
            title="House in Pfungen",
        )

        self.assertFalse(matches_filters(listing, source))


if __name__ == "__main__":
    unittest.main()
