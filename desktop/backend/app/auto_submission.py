"""Scan a 123 folder and prepare each direct child as one channel post."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

from .movie_library import hex_to_base62
from .submission import format_size

MAX_ITEMS = 5000
MAX_DEPTH = 12
SEED_DIR_NAME = "自动投稿秒传种子"
MD5 = re.compile(r"^[0-9a-fA-F]{32}$")


def normalize_config(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    root = str(raw.get("rootDirId") or "0").strip()
    if not root.isdigit():
        raise ValueError("123 目录 ID 必须是数字")
    mode = str(raw.get("mode") or "fastlink").strip()
    if mode not in {"fastlink", "share"}:
        raise ValueError("投稿方式必须是秒传或分享链接")
    try:
        owner = int(raw.get("ownerUserId") or 0)
        interval = min(3600, max(60, int(raw.get("intervalSec") or 300)))
    except (TypeError, ValueError) as error:
        raise ValueError("频道所有者 UID 或扫描间隔无效") from error
    if owner < 0:
        raise ValueError("频道所有者 UID 无效")
    return {"enabled": raw.get("enabled") is True, "rootDirId": root,
            "rootDirPath": str(raw.get("rootDirPath") or "").strip()[:300],
            "mode": mode, "ownerUserId": owner, "intervalSec": interval}


def _clean_path(value: str) -> str:
    return "/".join(part for part in (
        re.sub(r'[\\/:*?"<>|#$%]+', " ", segment).strip()
        for segment in str(value or "").replace("\\", "/").split("/")) if part)


def _entry_file(child: Dict[str, Any], path: str) -> Dict[str, Any]:
    return {"fileId": str(child.get("fileId") or ""), "name": str(child.get("name") or ""),
            "path": path, "size": int(child.get("size") or 0),
            "etag": str(child.get("etag") or "").lower()}


def _fingerprint(entry: Dict[str, Any], files: List[Dict[str, Any]]) -> str:
    facts = [str(entry.get("fileId") or ""), str(entry.get("name") or ""), str(entry.get("type") or 0)]
    facts.extend(f"{f['fileId']}|{f['path']}|{f['size']}|{f['etag']}" for f in files)
    return hashlib.sha256("\n".join(facts).encode()).hexdigest()


async def discover(client: Any, root_dir_id: str) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    counter = 0

    async def descend(parent_id: str, prefix: str, depth: int) -> List[Dict[str, Any]]:
        nonlocal counter
        if depth > MAX_DEPTH:
            raise ValueError("目录层级超过 12 层，已停止扫描")
        if parent_id in seen:
            return []
        seen.add(parent_id)
        files: List[Dict[str, Any]] = []
        for child in await client.list_files(parent_id):
            counter += 1
            if counter > MAX_ITEMS:
                raise ValueError("目录内条目超过 5000 个，已停止扫描")
            name = str(child.get("name") or "").strip()
            child_id = str(child.get("fileId") or "")
            if not name or not child_id:
                continue
            path = "/".join([prefix, name]) if prefix else name
            if int(child.get("type") or 0) == 1:
                files.extend(await descend(child_id, path, depth + 1))
            else:
                files.append(_entry_file(child, "/".join([prefix, name]) if prefix else name))
        return files

    groups: List[Dict[str, Any]] = []
    for entry in await client.list_files(str(root_dir_id)):
        counter += 1
        if counter > MAX_ITEMS:
            raise ValueError("目录内条目超过 5000 个，已停止扫描")
        name = str(entry.get("name") or "").strip()
        entry_id = str(entry.get("fileId") or "")
        if not name or not entry_id:
            continue
        is_dir = int(entry.get("type") or 0) == 1
        if is_dir and name == SEED_DIR_NAME:
            continue
        files = await descend(entry_id, "", 1) if is_dir else [_entry_file(entry, name)]
        groups.append({"fileId": entry_id, "name": name, "isDir": is_dir,
                       "files": files, "size": sum(f["size"] for f in files),
                       "fingerprint": _fingerprint(entry, files)})
    return groups


def _fastlink_entry(file: Dict[str, Any]) -> str:
    name = str(file.get("path") or "")
    etag = str(file.get("etag") or "")
    size = int(file.get("size") or 0)
    if not MD5.fullmatch(etag) or size < 0 or not name or _clean_path(name) != name:
        raise ValueError(f"文件缺少有效 MD5、大小或名称含秒传分隔符：{name}")
    return f"{hex_to_base62(etag)}#{size}#{name}"


async def make_link(client: Any, group: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Return a share or V2 fastlink (folder: uploaded short seed link)."""
    name = str(group["name"])
    files = group["files"]
    document = None
    if mode == "share":
        url = await client.create_share(int(group["fileId"]), name)
        provider = "123pan"
    elif len(files) == 1 and not group["isDir"]:
        url = "123FLCPV2$%" + _fastlink_entry(files[0])
        provider = "123fastlink"
    else:
        if not files:
            raise ValueError("空文件夹没有可生成秒传的文件")
        if _clean_path(name) != name:
            raise ValueError(f"文件夹名含秒传格式不支持的字符：{name}")
        entries = []
        for file in files:
            _fastlink_entry(file)
            entries.append({"path": name + "/" + file["path"], "fileName": file["name"],
                            "etag": hex_to_base62(file["etag"]), "size": file["size"], "type": 0})
        payload = json.dumps({"exportVersion": "1.0", "usesBase62EtagsInExport": True,
                              "commonPath": "", "totalFilesCount": len(entries),
                              "totalSize": group["size"], "files": entries}, ensure_ascii=False, indent=2)
        seed_dir = await client.ensure_path("0", [SEED_DIR_NAME])
        safe_name = _clean_path(name).replace("/", " ")[:120] or "自动投稿"
        seed_name = f"{safe_name}-{group['fingerprint'][:12]}.123fastlink.json"
        seed = await client.upload_text_file(seed_dir, seed_name, payload)
        url = f"123FLCPV2$%{hex_to_base62(seed['etag'])}#{seed['size']}#{seed_name}"
        provider = "123fastlink"
        document = {"type": "fastlink_json", "fileName": seed_name, "mimeType": "application/json", "content": payload}
    file_names = [str(file["path"]) for file in files]
    source_text = "\n".join([name, *file_names[:100]])
    inspection = {"title": name, "fileNames": file_names,
                  "size": format_size(group["size"]), "rawText": source_text}
    result = {"link": {"provider": provider, "url": url, "cleanUrl": url,
                       "title": name, "sourceText": source_text}, "inspection": inspection}
    if document:
        result["document"] = document
    return result
