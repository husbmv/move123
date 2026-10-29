from pathlib import Path

from app import web_auth
from app.network_proxy import httpx_proxy, telegram_telethon_proxy, set_web_proxy_url
from app.session_store import SessionStore


def test_web_account_and_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLOUD123_WEB_AUTH", "1")
    store = SessionStore(tmp_path)
    token = web_auth.login(store, "admin", "password")
    assert token

    class Request:
        cookies = {web_auth.COOKIE_NAME: token}

    assert web_auth.authenticated(store, Request())
    web_auth.change_account(store, "admin", "password", "!任意 空格#$%")
    assert not web_auth.authenticated(store, Request())
    assert web_auth.login(store, "admin", "!任意 空格#$%")
    assert not web_auth._matches(store.read_value("web_auth_account"), "admin", "password")
    assert "password" not in str(store.read_value("web_auth_account"))
    web_auth.change_account(store, "admin", "!任意 空格#$%", "new pass", "newadmin")
    assert web_auth.login(store, "newadmin", "new pass")
    assert not web_auth._matches(store.read_value("web_auth_account"), "admin", "new pass")
    assert SessionStore(tmp_path).read_value("web_auth_account") == store.read_value("web_auth_account")


def test_service_specific_proxies(monkeypatch):
    from app import network_proxy
    monkeypatch.setattr(network_proxy, "_web_proxy_configured", False)
    monkeypatch.setattr(network_proxy, "_web_proxy_url", "")
    monkeypatch.setenv("TG_PROXY_URL", "socks5://proxy:1080")
    monkeypatch.setenv("TMDB_PROXY_URL", "http://proxy:7890")
    assert httpx_proxy("tg") == "socks5://proxy:1080"
    assert httpx_proxy("tmdb") == "http://proxy:7890"
    import socks
    assert telegram_telethon_proxy()[:4] == (socks.SOCKS5, "proxy", 1080, True)
    set_web_proxy_url("http://host.docker.internal:3128")
    assert httpx_proxy("tg") == "http://host.docker.internal:3128"
    assert httpx_proxy("tmdb") == "http://host.docker.internal:3128"
    set_web_proxy_url("")
    assert httpx_proxy("tg") is None
