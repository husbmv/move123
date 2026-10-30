"""Build per-file fastlink posts after a completed 115 → 123 transfer."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .movie_library import hex_to_base62


MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def publishable_files(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Only fully verified files may be advertised as transferable."""
    if str(task.get("status") or "") != "success" or str(task.get("kind") or "pan115_share") not in {"pan115_share", ""}:
        return []
    files = task.get("files") or []
    if not isinstance(files, list) or any(not isinstance(file, dict) or file.get("status") not in {"success", "skipped"} for file in files):
        return []
    # Existing files were only inferred by name+size, not verified as the
    # current transfer's content. Publish files actually transferred now.
    return [file for file in files if file.get("status") == "success"]


def file_fastlink(file: Dict[str, Any], etag: str) -> str:
    """Single-file V2 link compatible with the project's 123 helper parser."""
    name = str(file.get("name") or "").strip()
    size = int(file.get("size") or 0)
    if not name or size <= 0 or not MD5_RE.fullmatch(str(etag or "")):
        raise ValueError("缺少文件名、大小或已验证的 MD5")
    if any(char in name for char in (chr(10), chr(13), "#", "$")):
        raise ValueError("文件名含秒传链接不支持的分隔符")
    return "123FSLinkV2$" + hex_to_base62(etag) + "#" + str(size) + "#" + name


def file_path(file: Dict[str, Any]) -> str:
    parts = [str(part or "").strip() for part in file.get("path") or []]
    return "/".join([*filter(None, parts), str(file.get("name") or "")])
