import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.session_store import SessionStore
from app.telegram_115_monitor import cursor_key, normalize_channel, process_message, message_text


class Telegram115MonitorTests(unittest.TestCase):
    def test_channel_normalization(self):
        self.assertEqual(normalize_channel("https://t.me/s/Movies115"), "@movies115")
        self.assertEqual(normalize_channel("@Movies115"), "@movies115")
        self.assertEqual(normalize_channel("-1001234567890"), "-1001234567890")
        with self.assertRaises(ValueError):
            normalize_channel("https://example.org/channel")

    def test_hidden_link_entities_and_buttons(self):
        message = SimpleNamespace(raw_text="提取码 1234", entities=[SimpleNamespace(url="https://115cdn.com/s/abcd")], buttons=[[SimpleNamespace(url="https://115cdn.com/s/efgh?password=5678")]])
        text = message_text(message)
        self.assertIn("115cdn.com/s/abcd", text)
        self.assertIn("115cdn.com/s/efgh", text)

    def test_processes_all_links_and_persists_cursor(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                store = SessionStore(Path(directory))
                message = SimpleNamespace(id=12, raw_text="115链接 https://115cdn.com/s/abcd?password=1234; 以及 https://115cdn.com/s/efgh?password=5678")
                enqueue = AsyncMock(return_value=[{"id": "task"}])
                first = await process_message(store, "@movies115", message, enqueue)
                second = await process_message(store, "@movies115", message, enqueue)
                self.assertEqual(first, {"accepted": 2, "skipped": 0})
                self.assertEqual(second, {"accepted": 0, "skipped": 0})
                self.assertEqual(enqueue.await_count, 2)
                self.assertEqual(store.read_value(cursor_key("@movies115")), 12)
        asyncio.run(run())

    def test_failed_enqueue_does_not_advance_cursor(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                store = SessionStore(Path(directory))
                message = SimpleNamespace(id=12, raw_text="https://115cdn.com/s/abcd?password=1234")
                with self.assertRaises(RuntimeError):
                    await process_message(store, "@movies115", message, AsyncMock(side_effect=RuntimeError("network")))
                self.assertIsNone(store.read_value(cursor_key("@movies115")))
        asyncio.run(run())

    def test_missing_code_is_skipped_and_cursor_moves(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                store = SessionStore(Path(directory))
                message = SimpleNamespace(id=12, raw_text="https://115cdn.com/s/abcd")
                enqueue = AsyncMock()
                outcome = await process_message(store, "@movies115", message, enqueue)
                self.assertEqual(outcome["accepted"], 0)
                self.assertEqual(outcome["skipped"], 1)
                self.assertEqual(store.read_value(cursor_key("@movies115")), 12)
                enqueue.assert_not_awaited()
        asyncio.run(run())

    def test_same_share_in_later_post_is_not_requeued(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                store = SessionStore(Path(directory))
                enqueue = AsyncMock(return_value=[{"id": "task"}])
                text = "https://115cdn.com/s/abcd?password=1234"
                await process_message(store, "@movies115", SimpleNamespace(id=12, raw_text=text), enqueue)
                result = await process_message(store, "@movies115", SimpleNamespace(id=13, raw_text=text), enqueue)
                self.assertEqual(result, {"accepted": 0, "skipped": 1})
                enqueue.assert_awaited_once()
                self.assertEqual(store.read_value(cursor_key("@movies115")), 13)
        asyncio.run(run())
