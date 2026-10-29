"""Poll one Telegram channel for 115 shares and enqueue them for transfer.

The cursor and per-link receipts live in SessionStore so a restart does not
replay already processed history. Historical messages are consumed oldest-first
in small batches before the monitor switches to following new posts.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Dict

from .pan115_transfer import extract_115_links
from .session_store import SessionStore, utc_now_iso
from .telegram_history import connect_telegram_client

logger = logging.getLogger(__name__)

CURSOR_PREFIX = "tg115_monitor_cursor:"
RECEIPT_PREFIX = "tg115_monitor_link:"
SHARE_PREFIX = "tg115_monitor_share:"
STATUS_KEY = "tg115_monitor_status"
CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
CHANNEL_ID_RE = re.compile(r"^-100[0-9]{5,}$")
CHANNEL_URL_RE = re.compile(r"^https?://(?:www[.])?t[.]me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})/?$", re.I)


def normalize_channel(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    match = CHANNEL_URL_RE.fullmatch(raw)
    if match:
        raw = match.group(1)
    if CHANNEL_RE.fullmatch(raw):
        return "@" + raw.lower()
    if CHANNEL_ID_RE.fullmatch(raw):
        return raw
    raise ValueError("公开频道填 @字母用户名或 https://t.me/字母用户名；私有频道填 -100 开头的数字 ID，且 TG 用户须已加入")


def cursor_key(channel: str) -> str:
    return CURSOR_PREFIX + channel


def receipt_key(channel: str, message_id: int, share_code: str) -> str:
    return f"{RECEIPT_PREFIX}{channel}:{message_id}:{share_code}"


def share_key(channel: str, share_code: str) -> str:
    return f"{SHARE_PREFIX}{channel}:{share_code}"


def message_text(message: Any) -> str:
    text = str(getattr(message, "raw_text", None) or getattr(message, "message", None) or "").strip()
    urls = []
    for entity in getattr(message, "entities", None) or []:
        url = str(getattr(entity, "url", None) or "").strip()
        if url:
            urls.append(url)
    for row in getattr(message, "buttons", None) or []:
        for button in row if isinstance(row, (list, tuple)) else [row]:
            url = str(getattr(button, "url", None) or "").strip()
            if url:
                urls.append(url)
    return chr(10).join([text, *urls]).strip()


async def process_message(
    store: SessionStore,
    channel: str,
    message: Any,
    enqueue: Callable[[str, str], Awaitable[Any]],
) -> Dict[str, Any]:
    """Enqueue every complete 115 link; advance cursor only after success.

    Missing codes cannot be repaired automatically, so record and skip them.
    Retriable queue failures leave the cursor at this message for next poll.
    """
    message_id = int(getattr(message, "id", 0) or 0)
    if message_id <= 0:
        return {"accepted": 0, "skipped": 0}
    text = message_text(message)
    links = extract_115_links(text)
    accepted = skipped = 0
    for link in links:
        code = str(link.get("share_code") or "")
        receipt = receipt_key(channel, message_id, code)
        if store.read_value(receipt):
            continue
        if store.read_value(share_key(channel, code)):
            skipped += 1
            store.write_value(receipt, {"status": "previously_queued", "at": utc_now_iso()})
            continue
        if not str(link.get("receive_code") or "").strip():
            skipped += 1
            logger.warning("TG 频道消息 %s 的 115 分享缺少提取码，已跳过：%s", message_id, code)
            store.write_value(receipt, {"status": "missing_code", "at": utc_now_iso()})
            continue
        try:
            tasks = await enqueue(str(link["clean_url"]), f"TG频道 {channel}")
        except RuntimeError as error:
            if "已有未完成任务" not in str(error):
                raise
            # Existing queued/running task already covers this share; mark
            # the message consumed, so a restart does not requeue it.
            skipped += 1
            store.write_value(receipt, {"status": "duplicate", "at": utc_now_iso()})
            continue
        if not tasks:
            raise RuntimeError("115 分享未加入搬运队列")
        store.write_value(share_key(channel, code), {"messageId": message_id, "at": utc_now_iso()})
        store.write_value(receipt, {"status": "queued", "at": utc_now_iso()})
        accepted += 1
    store.write_value(cursor_key(channel), message_id)
    return {"accepted": accepted, "skipped": skipped}


async def scan_batch(
    store: SessionStore,
    channel: str,
    tg_config: Dict[str, Any],
    enqueue: Callable[[str, str], Awaitable[Any]],
    *,
    limit: int = 100,
) -> Dict[str, Any]:
    """Fetch one oldest-first page, then disconnect the TG user session."""
    client = await connect_telegram_client(tg_config)
    count = accepted = skipped = 0
    try:
        try:
            peer = await client.get_input_entity(int(channel) if channel.startswith("-100") else channel)
        except ValueError as error:
            raise ValueError("TG 用户 Session 无法访问该频道；私有频道请先加入并在 Telegram 中打开一次") from error
        cursor = int(store.read_value(cursor_key(channel)) or 0)
        async for message in client.iter_messages(peer, min_id=cursor, reverse=True, limit=limit):
            current = store.read_config().get("transfer") or {}
            if current.get("tg115MonitorEnabled") is not True or normalize_channel(current.get("tg115MonitorChannel")) != channel:
                break
            outcome = await process_message(store, channel, message, enqueue)
            count += 1
            accepted += outcome["accepted"]
            skipped += outcome["skipped"]
    finally:
        await client.disconnect()
    return {"messages": count, "accepted": accepted, "skipped": skipped, "cursor": int(store.read_value(cursor_key(channel)) or 0)}


async def monitor_loop(store: SessionStore, transfer_service: Any) -> None:
    """Continuously backfill history and then watch for new channel posts."""
    was_stopped = False
    while True:
        channel = ""
        try:
            transfer = store.read_config().get("transfer") or {}
            enabled = transfer.get("tg115MonitorEnabled") is True
            if not enabled:
                if not was_stopped:
                    store.write_value(STATUS_KEY, {"enabled": False, "state": "stopped", "lastCheckedAt": utc_now_iso()})
                    was_stopped = True
                await asyncio.sleep(5)
                continue
            was_stopped = False
            channel = normalize_channel(transfer.get("tg115MonitorChannel"))
            if transfer.get("enabled") is not True:
                raise RuntimeError("请先启用 115 搬运")
            if not transfer.get("pan115Cookies") and not str(transfer.get("pan115Cookie") or "").strip():
                raise RuntimeError("请先在频道监控或搬运设置里手动填写至少一个 115 Cookie")
            tg = store.read_submission_config().get("telegramApi") or {}
            if not all(str(tg.get(key) or "").strip() for key in ("apiId", "apiHash", "session")):
                raise RuntimeError("请先在投稿机器人配置 TG API ID、API Hash 和用户 Session")
            target_dir_id = str(transfer.get("tg115MonitorTargetDirId") or "0").strip()
            if not re.fullmatch(r"[0-9]+", target_dir_id):
                raise RuntimeError("TG 监控的 123 目标目录 ID 必须是数字")
            async def enqueue(url: str, source: str) -> Any:
                return await transfer_service.enqueue_from_text(url, "tg115-monitor:" + channel, target_dir_id=target_dir_id)
            result = await scan_batch(store, channel, tg, enqueue)
            status = {"channel": channel, "enabled": True, "state": "running", "lastError": "", "lastCheckedAt": utc_now_iso(), **result}
            store.write_value(STATUS_KEY, status)
            if result["accepted"] or result["skipped"]:
                logger.info("TG 频道监控：扫描 %s 条消息，加入搬运 %s 条，跳过无提取码 %s 条", result["messages"], result["accepted"], result["skipped"])
            await asyncio.sleep(2 if result["messages"] >= 100 else 30)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("TG 频道监控暂时无法继续：%s", error)
            store.write_value(STATUS_KEY, {"channel": channel, "enabled": True, "state": "error", "lastError": str(error)[:300], "lastCheckedAt": utc_now_iso(), "cursor": int(store.read_value(cursor_key(channel)) or 0) if channel else 0})
            await asyncio.sleep(30)
