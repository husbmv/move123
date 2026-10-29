import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.transfer_autopublish import file_fastlink, publishable_files, render_reference_caption
from app.session_store import SessionStore
from app.transfer_service import TransferService


def _task(status="success"):
    return {"id": "task-1", "kind": "pan115_share", "status": status, "files": [
        {"name": "Episode.mkv", "size": 123, "path": ["Show"], "targetDirId": "42", "pan123FileId": 77, "status": "success"}
    ]}


class AutoPublishTests(__import__("unittest").TestCase):
 def test_fastlink_single_file_roundtrip(self):
    from app.movie_library import parse_fastlink_text
    link = file_fastlink(_task()["files"][0], "0" * 31 + "1")
    parsed = parse_fastlink_text(link)
    assert parsed["files"][0]["etag"] == "0" * 31 + "1"
    assert parsed["files"][0]["size"] == 123
    assert parsed["files"][0]["path"] == "Episode.mkv"
    assert publishable_files(_task("partial")) == []
    caption = render_reference_caption({"media": {"title": "测试影片", "year": "2026", "tmdbId": 42, "overview": "简介", "genres": ["动作"]}, "metadata": {}}, "Episode.mkv", "123 B", link)
    assert "🏷️ 标签" in caption and "🆔 TMDB：42" in caption
    assert "🔗 分享链接" in caption and link in caption

 def test_completed_transfer_uses_existing_submission_publisher_without_duplicate(self):
    class Store:
        def __init__(self):
            self.values = {}

        def read_submission_config(self):
            return {"botToken": "fake", "channelOwnerUserIds": [123]}

        def has_user_channel_config(self, user_id):
            return user_id == 123

        def read_value(self, key):
            return self.values.get(key)

        def write_value(self, key, value):
            self.values[key] = value

    store = Store()
    client = AsyncMock()
    client.list_files.return_value = [{"name": "Episode.mkv", "size": 123, "fileId": 77, "etag": "0" * 31 + "1"}]
    draft = {"id": "draft-1", "ownerUserId": 123}
    with patch.object(main, "store", store), patch.object(main.transfer_service, "create_status_pan123_client", AsyncMock(return_value=client)), patch.object(
        main, "build_submission_draft", AsyncMock(return_value=draft)
    ), patch.object(main, "route_submission_draft", return_value=({"chatId": "-100123"}, {})), patch.object(
        main, "append_submission_draft", return_value=draft
    ), patch.object(main, "list_submission_drafts", return_value=[]), patch.object(main, "publish_submission_draft", AsyncMock(return_value={"ok": True, "channelId": "movies", "messageId": 88})) as publish:
        first = asyncio.run(main.publish_completed_transfer_fastlinks(_task()))
        second = asyncio.run(main.publish_completed_transfer_fastlinks(_task()))
    assert first == {"published": 1}
    assert second == {"published": 0}
    publish.assert_awaited_once()

 def test_switch_defaults_off_and_partial_tasks_never_publish(self):
    from app.main import normalize_transfer_config
    assert normalize_transfer_config({})["autoPublishFastlink"] is False
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            service = TransferService(SessionStore(Path(directory)))
            notifier = AsyncMock()
            service.set_publish_notifier(notifier)
            await service._publish_completed_transfer(_task("partial"), {"autoPublishFastlink": True})
            await service._publish_completed_transfer(_task(), {"autoPublishFastlink": False})
            notifier.assert_not_awaited()
            await service.close()
    asyncio.run(run())
