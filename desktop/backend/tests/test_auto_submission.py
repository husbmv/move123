import asyncio
import hashlib
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import auto_submission, main
from app.movie_library import parse_fastlink_text
from app.session_store import SessionStore


def run(coro):
    return asyncio.run(coro)


class FakeCloud:
    def __init__(self):
        self.tree = {
            "10": [
                {"fileId": 20, "name": "电影 (2026)", "type": 1},
                {"fileId": 30, "name": "单集.mkv", "type": 0, "size": 12, "etag": "a" * 32},
            ],
            "20": [{"fileId": 21, "name": "Season 1", "type": 1}],
            "21": [{"fileId": 22, "name": "E01.mkv", "type": 0, "size": 34, "etag": "b" * 32}],
        }
        self.shares = []
        self.uploads = []

    async def list_files(self, parent):
        return self.tree.get(str(parent), [])

    async def create_share(self, file_id, name):
        self.shares.append((file_id, name))
        return f"https://www.123pan.com/s/key{file_id}"

    async def ensure_path(self, root, path):
        return "90"

    async def upload_text_file(self, parent, name, content):
        self.uploads.append((parent, name, content))
        data = content.encode()
        return {"etag": hashlib.md5(data).hexdigest(), "size": len(data), "fileId": 91}


def test_discover_direct_children_and_links():
    cloud = FakeCloud()
    groups = run(auto_submission.discover(cloud, "10"))
    assert len(groups) == 2
    assert groups[0]["files"][0]["path"] == "Season 1/E01.mkv"
    assert groups[1]["files"][0]["path"] == "单集.mkv"
    folder = run(auto_submission.make_link(cloud, groups[0], "fastlink"))
    parsed = parse_fastlink_text(folder["link"]["url"])
    assert parsed["files"][0]["fileName"].endswith(".123fastlink.json")
    payload = json.loads(cloud.uploads[0][2])
    assert payload["files"][0]["path"] == "电影 (2026)/Season 1/E01.mkv"
    single = run(auto_submission.make_link(cloud, groups[1], "fastlink"))
    assert parse_fastlink_text(single["link"]["url"])["files"][0]["size"] == 12
    shared = run(auto_submission.make_link(cloud, groups[0], "share"))
    assert shared["link"]["url"].endswith("key20")


def test_scan_receipt_and_failed_retry():
    cloud = FakeCloud()
    with tempfile.TemporaryDirectory() as directory:
        store = SessionStore(Path(directory))
        store.write_value(main.AUTO_SUBMISSION_CONFIG_KEY, {"rootDirId": "10", "mode": "share", "ownerUserId": 123})
        store.write_submission_config({"botToken": "test", "channelOwnerUserIds": [123]})
        store.write_user_channel_config(123, {"channels": [{"id": "m", "title": "movie", "chatId": "-1001", "enabled": True}], "routing": {"fallbackChannelId": "m"}})
        fake_draft = {"id": "draft", "ownerUserId": 123, "routeOwnerUserId": 123,
                      "share": {"provider": "123pan", "url": "https://www.123pan.com/s/x"}}
        publisher = AsyncMock(side_effect=[{"ok": False, "reason": "chat not found"}, {"ok": True, "messageId": 1}, {"ok": True, "messageId": 2}])
        with ExitStack() as stack:
            stack.enter_context(patch.object(main, "store", store))
            stack.enter_context(patch.object(main.transfer_service, "create_status_pan123_client", AsyncMock(return_value=cloud)))
            stack.enter_context(patch.object(main, "build_submission_draft", AsyncMock(return_value=fake_draft)))
            stack.enter_context(patch.object(main, "route_submission_draft", return_value=({"id": "m", "chatId": "-1001"}, {})))
            stack.enter_context(patch.object(main, "publish_submission_draft", publisher))
            first = run(main.run_auto_submission_scan())["status"]
            second = run(main.run_auto_submission_scan())["status"]
        assert (first["published"], first["failed"]) == (1, 1)
        assert (second["published"], second["skipped"]) == (1, 1)
        assert len(cloud.shares) == 2  # failed item's link reused from prepared cache
