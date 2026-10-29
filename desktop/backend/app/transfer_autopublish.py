"""Build per-file fastlink posts after a completed 115 → 123 transfer."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List

from .movie_library import hex_to_base62
from .submission import build_tags_text


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


def render_reference_caption(draft: Dict[str, Any], filename: str, size_text: str, fastlink: str) -> str:
    """Caption layout inspired by public Pan123Movie posts, retaining available metadata."""
    media = draft.get("media") if isinstance(draft.get("media"), dict) else {}
    metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
    title = str(media.get("title") or metadata.get("title") or filename).strip()
    year = str(media.get("year") or metadata.get("year") or "").strip()
    name = title if not year or f"({year})" in title else f"{title} ({year})"
    episode = str(metadata.get("seasonEpisode") or "").strip()
    if episode and episode not in name:
        name += " " + episode
    if not name:
        name = filename
    tags = build_tags_text(title, media.get("genres") or [])
    media_type = "电影" if str(media.get("mediaType") or metadata.get("mediaType") or "") == "movie" else "剧集"
    region = str(media.get("region") or "").strip()
    lines = [f"<b>{escape(name)}</b>", f"🏷️ 标签：{escape(tags)}", f"📺 类型：{escape(region + media_type if region else media_type)}"]
    first_air_date = str(media.get("firstAirDate") or media.get("releaseDate") or "").strip()
    if first_air_date:
        lines.append(f"📅 首播：{escape(first_air_date)}")
    rating = media.get("voteAverage")
    rating_parts = []
    if rating not in (None, ""):
        rating_parts.append(f"TMDB: {escape(str(rating))}")
    douban_rating = media.get("doubanRating")
    if douban_rating not in (None, ""):
        rating_parts.append(f"豆瓣: {escape(str(douban_rating))}")
    if rating_parts:
        lines.append("⭐ 评分：" + " | ".join(rating_parts))
    tmdb_id = media.get("tmdbId") or metadata.get("tmdbId")
    if tmdb_id:
        lines.append(f"🆔 TMDB：{escape(str(tmdb_id))}")
    overview = str(media.get("overview") or "").strip()
    if overview:
        lines.append(f"📝 简介：{escape(overview[:600])}")
    version = " ".join(str(metadata.get(key) or "").strip() for key in ("quality", "webSource", "resourceType", "videoCodec", "effect", "audioCodec") if str(metadata.get(key) or "").strip())
    lines.extend([f"🖼️ 版本：{escape(version or filename)}", f"💾 体积：{escape(size_text)}", "🔗 分享链接：", escape(fastlink)])
    return chr(10).join(lines)
