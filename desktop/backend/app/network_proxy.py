"""Optional, service-specific outbound proxies for Docker deployments."""

import os
from urllib.parse import unquote, urlparse

_web_proxy_url = ""
_web_proxy_configured = False


def set_web_proxy_url(value: str) -> None:
    global _web_proxy_url, _web_proxy_configured
    value = value.strip()
    if value:
        try:
            parsed = urlparse(value)
            valid = parsed.scheme.lower() in {"http", "socks5", "socks5h"} and bool(parsed.hostname) and bool(parsed.port)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("代理地址需为 http:// 或 socks5:// 开头，并包含主机与端口")
    _web_proxy_url = value
    _web_proxy_configured = True


def web_proxy_url() -> str:
    return _web_proxy_url


def httpx_proxy(service: str) -> str | None:
    value = _web_proxy_url if _web_proxy_configured else os.environ.get(f"{service.upper()}_PROXY_URL", "").strip()
    return value or None


def telegram_telethon_proxy():
    value = httpx_proxy("tg")
    if not value:
        return None
    import socks

    parsed = urlparse(value)
    kind = {"socks5": socks.SOCKS5, "socks5h": socks.SOCKS5, "http": socks.HTTP}.get(parsed.scheme.lower())
    if kind is None or not parsed.hostname or not parsed.port:
        raise ValueError("TG_PROXY_URL 仅支持 socks5://、socks5h:// 或 http:// 代理地址")
    return (kind, parsed.hostname, parsed.port, True, unquote(parsed.username or "") or None, unquote(parsed.password or "") or None)
