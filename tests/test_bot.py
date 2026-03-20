import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zurich_house_hunter.bot import build_status_message, parse_command, GroupChatBot
from zurich_house_hunter.config import load_config


class BotTests(unittest.TestCase):
    def test_parse_command_strips_bot_suffix(self):
        command, args = parse_command("/set@househunterbot max_price 8000")
        self.assertEqual(command, "set")
        self.assertEqual(args, ["max_price", "8000"])

    def test_status_message_mentions_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            state_path = os.path.join(tmpdir, "state.sqlite3")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
{
  "runtime": {
    "state_db_path": "%s"
  },
  "telegram": {
    "bot_token": "token",
    "chat_id": "-1001"
  },
  "sources": [
    {
      "name": "source-a",
      "kind": "generic_link_cards",
      "search_url": "https://example.com",
      "enabled": true,
      "min_rooms": 4,
      "max_price_chf": 8000
    }
  ]
}
"""
                    % state_path.replace("\\", "\\\\")
                )
            config = load_config(config_path)
            bot = GroupChatBot(config, dry_run=True)
            try:
                response = bot._dispatch_command("set", ["max_price", "7500"], "-1001", None)
                self.assertIn("Updated max_price_chf", response)
                status = build_status_message(
                    config,
                    bot._store.get_chat_filters("-1001"),
                    bot._store.list_active_chat_targets(),
                    current_chat=bot._store.get_chat_target("-1001"),
                )
                self.assertIn("7500", status)
                self.assertIn("source-a", status)
                self.assertIn("Current target", status)
            finally:
                bot.close()

    def test_message_update_registers_private_chat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            state_path = os.path.join(tmpdir, "state.sqlite3")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
{
  "runtime": {
    "state_db_path": "%s"
  },
  "telegram": {
    "bot_token": "token"
  },
  "sources": [
    {
      "name": "source-a",
      "kind": "generic_link_cards",
      "search_url": "https://example.com",
      "enabled": false
    }
  ]
}
"""
                    % state_path.replace("\\", "\\\\")
                )
            config = load_config(config_path)
            bot = GroupChatBot(config, dry_run=True)
            try:
                bot._handle_update(
                    {
                        "update_id": 1,
                        "message": {
                            "message_id": 10,
                            "text": "/start",
                            "chat": {
                                "id": 12345,
                                "type": "private",
                                "first_name": "Jan"
                            }
                        }
                    }
                )
                targets = bot._store.list_active_chat_targets()
                self.assertEqual(len(targets), 1)
                self.assertEqual(targets[0].chat_id, "12345")
                self.assertEqual(targets[0].chat_type, "private")
            finally:
                bot.close()

    def test_membership_update_registers_group_chat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            state_path = os.path.join(tmpdir, "state.sqlite3")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
{
  "runtime": {
    "state_db_path": "%s"
  },
  "telegram": {
    "bot_token": "token"
  },
  "sources": [
    {
      "name": "source-a",
      "kind": "generic_link_cards",
      "search_url": "https://example.com",
      "enabled": false
    }
  ]
}
"""
                    % state_path.replace("\\", "\\\\")
                )
            config = load_config(config_path)
            bot = GroupChatBot(config, dry_run=True)
            try:
                bot._handle_update(
                    {
                        "update_id": 2,
                        "my_chat_member": {
                            "chat": {
                                "id": -100123,
                                "type": "supergroup",
                                "title": "Zurich House Search"
                            },
                            "new_chat_member": {
                                "status": "member"
                            }
                        }
                    }
                )
                target = bot._store.get_chat_target("-100123")
                self.assertIsNotNone(target)
                self.assertEqual(target.chat_type, "supergroup")
                self.assertEqual(target.title, "Zurich House Search")
            finally:
                bot.close()


if __name__ == "__main__":
    unittest.main()
