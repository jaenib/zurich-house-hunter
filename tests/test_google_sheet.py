import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.google_sheet import GOOGLE_SHEET_HEADERS, build_google_sheet_row, infer_house_flat
from zurich_house_hunter.models import Listing


class GoogleSheetTests(unittest.TestCase):
    def test_google_sheet_headers_match_expected_columns(self):
        self.assertEqual(
            GOOGLE_SHEET_HEADERS,
            ["Adresse", "\u00d6VMinHB", "VeloMinHB", "CHF", "AnzZimmer", "CHF/Zimmer", "HouseFlat", "Link", "BigNoNos"],
        )

    def test_build_google_sheet_row_maps_core_fields(self):
        listing = Listing(
            source_name="alle-immobilien-zuerich-houses",
            url="https://www.homegate.ch/mieten/4003020575",
            canonical_key="https://www.homegate.ch/mieten/4003020575",
            raw_text="Charmantes 7.5-Zimmer-Bauernhaus in ruhiger Lage in Winkel",
            title="Charmantes 7.5-Zimmer-Bauernhaus in ruhiger Lage in Winkel",
            address="Lufingerstrasse 7, 8185 Winkel",
            price_chf=3000.0,
            rooms=7.0,
        )

        self.assertEqual(
            build_google_sheet_row(listing),
            [
                "Lufingerstrasse 7, 8185 Winkel",
                "",
                "",
                3000.0,
                7.0,
                428.57,
                "house",
                "https://www.homegate.ch/mieten/4003020575",
                "",
            ],
        )

    def test_infer_house_flat_detects_flats(self):
        listing = Listing(
            source_name="flat-search",
            url="https://example.com/1",
            canonical_key="https://example.com/1",
            raw_text="Charmante 4.5-Zimmer-Wohnung",
            title="Charmante Wohnung",
        )

        self.assertEqual(infer_house_flat(listing), "flat")


if __name__ == "__main__":
    unittest.main()
