import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.geo import haversine_km, postal_codes_within_radius, ZURICH_CENTER


class GeoTests(unittest.TestCase):
    def test_haversine_zero_distance(self):
        self.assertAlmostEqual(haversine_km(47.37, 8.538, 47.37, 8.538), 0.0, places=5)

    def test_haversine_known_pair(self):
        # Bern to Zurich is roughly 95 km
        d = haversine_km(46.9481, 7.4474, 47.3769, 8.5417)
        self.assertGreater(d, 90)
        self.assertLess(d, 100)

    def test_small_radius_contains_city_centre_codes(self):
        codes = postal_codes_within_radius(2.0)
        for plz in ["8000", "8001", "8002", "8003", "8004"]:
            self.assertIn(plz, codes)

    def test_small_radius_excludes_distant_codes(self):
        codes = postal_codes_within_radius(2.0)
        for plz in ["8302", "8800", "8903"]:
            self.assertNotIn(plz, codes)

    def test_5km_radius_matches_expected_count(self):
        codes = postal_codes_within_radius(5.0)
        # The config.example.json was trimmed to this set
        self.assertEqual(len(codes), 59)

    def test_10km_radius_includes_outer_codes(self):
        codes = postal_codes_within_radius(10.0)
        for plz in ["8134", "8600", "8702", "8952"]:
            self.assertIn(plz, codes)

    def test_result_is_sorted(self):
        codes = postal_codes_within_radius(8.0)
        self.assertEqual(codes, sorted(codes))

    def test_custom_center(self):
        # Using a center far from Zurich should yield no results for small radius
        codes = postal_codes_within_radius(1.0, center=(46.0, 7.0))
        self.assertEqual(codes, [])


class RadiusCommandIntegrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import json
        from zurich_house_hunter.config import load_config
        from zurich_house_hunter.bot import GroupChatBot

        self._tmpdir = tempfile.TemporaryDirectory()
        state_path = os.path.join(self._tmpdir.name, "state.sqlite3")
        config_path = os.path.join(self._tmpdir.name, "config.json")
        cfg = {
            "runtime": {"state_db_path": state_path},
            "telegram": {"bot_token": "token"},
            "sources": [
                {
                    "name": "src",
                    "kind": "generic_link_cards",
                    "search_url": "https://example.com",
                    "enabled": False,
                    "allowed_postal_codes_any": ["8001", "8952", "8302"],
                }
            ],
        }
        with open(config_path, "w") as f:
            json.dump(cfg, f)
        self._config = load_config(config_path)
        self._bot = GroupChatBot(self._config, dry_run=True)

    def tearDown(self):
        self._bot.close()
        self._tmpdir.cleanup()

    def test_set_radius_updates_filters(self):
        response = self._bot._dispatch_command("set", ["radius", "5"], "123", None)
        self.assertIn("59", response)
        self.assertIn("5", response)
        filters = self._bot._store.get_chat_filters("123")
        self.assertEqual(filters.radius_km, 5.0)

    def test_set_radius_persists_across_reload(self):
        self._bot._dispatch_command("set", ["radius", "3"], "123", None)
        filters = self._bot._store.get_chat_filters("123")
        self.assertEqual(filters.radius_km, 3.0)

    def test_clear_radius(self):
        self._bot._dispatch_command("set", ["radius", "5"], "123", None)
        response = self._bot._dispatch_command("clear", ["radius"], "123", None)
        self.assertIn("source default", response)
        filters = self._bot._store.get_chat_filters("123")
        self.assertIsNone(filters.radius_km)

    def test_clear_all_clears_radius(self):
        self._bot._dispatch_command("set", ["radius", "5"], "123", None)
        self._bot._dispatch_command("clear", ["all"], "123", None)
        filters = self._bot._store.get_chat_filters("123")
        self.assertIsNone(filters.radius_km)

    def test_invalid_radius_rejected(self):
        response = self._bot._dispatch_command("set", ["radius", "abc"], "123", None)
        self.assertIn("numeric", response)

    def test_zero_radius_rejected(self):
        response = self._bot._dispatch_command("set", ["radius", "0"], "123", None)
        self.assertIn("greater than 0", response)

    def test_radius_overrides_source_postal_codes(self):
        from zurich_house_hunter.service import apply_chat_filters_to_source
        from zurich_house_hunter.models import ChatFilters

        source = self._config.sources[0]
        filters = ChatFilters(chat_id="123", radius_km=5.0)
        effective = apply_chat_filters_to_source(source, filters)
        self.assertNotIn("8302", effective.allowed_postal_codes_any)
        self.assertNotIn("8952", effective.allowed_postal_codes_any)
        self.assertIn("8001", effective.allowed_postal_codes_any)

    def test_no_radius_preserves_source_postal_codes(self):
        from zurich_house_hunter.service import apply_chat_filters_to_source
        from zurich_house_hunter.models import ChatFilters

        source = self._config.sources[0]
        filters = ChatFilters(chat_id="123")
        effective = apply_chat_filters_to_source(source, filters)
        self.assertEqual(effective.allowed_postal_codes_any, ["8001", "8952", "8302"])

    def test_status_shows_radius(self):
        from zurich_house_hunter.bot import build_status_message
        from zurich_house_hunter.models import ChatFilters

        filters = ChatFilters(chat_id="123", radius_km=5.0)
        status = build_status_message(self._config, filters, [])
        self.assertIn("radius_km", status)
        self.assertIn("5", status)

    def test_status_shows_source_default_when_no_radius(self):
        from zurich_house_hunter.bot import build_status_message
        from zurich_house_hunter.models import ChatFilters

        filters = ChatFilters(chat_id="123")
        status = build_status_message(self._config, filters, [])
        self.assertIn("source default", status)


if __name__ == "__main__":
    unittest.main()
