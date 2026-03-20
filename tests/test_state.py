import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.models import ChatFilters
from zurich_house_hunter.state import SeenListingStore


class StateTests(unittest.TestCase):
    def test_mark_seen_and_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.sqlite3")
            store = SeenListingStore(path)
            try:
                self.assertFalse(store.has_seen("homegate", "https://example.com/1"))
                store.mark_seen("homegate", "https://example.com/1", "Title", "https://example.com/1")
                self.assertTrue(store.has_seen("homegate", "https://example.com/1"))
                self.assertEqual(store.source_seen_count("homegate"), 1)
            finally:
                store.close()

    def test_chat_filters_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.sqlite3")
            store = SeenListingStore(path)
            try:
                filters = ChatFilters(
                    chat_id="-1001",
                    max_price_chf=8000,
                    min_rooms=4.5,
                    include_terms=["haus", "villa"],
                    exclude_terms=["wg"],
                )
                store.save_chat_filters(filters)
                loaded = store.get_chat_filters("-1001")
                self.assertEqual(loaded.max_price_chf, 8000)
                self.assertEqual(loaded.min_rooms, 4.5)
                self.assertEqual(loaded.include_terms, ["haus", "villa"])
                self.assertEqual(loaded.exclude_terms, ["wg"])
            finally:
                store.close()

    def test_known_chat_targets_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.sqlite3")
            store = SeenListingStore(path)
            try:
                store.upsert_chat_target("-1001", chat_type="supergroup", title="WG Search", is_active=True)
                store.upsert_chat_target("12345", chat_type="private", title="Jan", is_active=True)
                targets = store.list_active_chat_targets()
                self.assertEqual(len(targets), 2)
                self.assertEqual({target.chat_id for target in targets}, {"-1001", "12345"})
                group = store.get_chat_target("-1001")
                self.assertIsNotNone(group)
                self.assertEqual(group.chat_type, "supergroup")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
