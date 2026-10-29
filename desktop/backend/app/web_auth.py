"""Cookie authentication for the opt-in Docker/web deployment."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse


COOKIE_NAME = "cloud123_session"
SESSION_TTL = 30 * 24 * 3600


def enabled() -> bool:
    return os.environ.get("CLOUD123_WEB_AUTH", "").lower() in {"1", "true", "yes"}


def _password_record(password: str) -> dict:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return {"salt": salt.hex(), "digest": digest.hex()}


def initialize_account(store) -> dict:
    account = store.read_value("web_auth_account")
    if isinstance(account, dict) and account.get("salt") and account.get("digest"):
        return account
    account = {"username": "admin", "version": secrets.token_hex(16), **_password_record("password")}
    store.write_value("web_auth_account", account)
    return account


def _matches(account: dict, username: str, password: str) -> bool:
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(account["salt"]), 310_000)
        return hmac.compare_digest(str(account["username"]), username) and hmac.compare_digest(bytes.fromhex(account["digest"]), digest)
    except (KeyError, ValueError, TypeError):
        return False


def login(store, username: str, password: str) -> str:
    if not _matches(initialize_account(store), username, password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = secrets.token_urlsafe(32)
    store.write_value("web_auth_session:" + hashlib.sha256(token.encode()).hexdigest(), {"expiry": time.time() + SESSION_TTL, "version": initialize_account(store).get("version")})
    return token


def authenticated(store, request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return False
    expiry = store.read_value("web_auth_session:" + hashlib.sha256(token.encode()).hexdigest())
    return isinstance(expiry, dict) and expiry.get("expiry", 0) > time.time() and expiry.get("version") == initialize_account(store).get("version")


def logout(store, request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        store.delete_value("web_auth_session:" + hashlib.sha256(token.encode()).hexdigest())


def change_account(store, username: str, current_password: str, new_password: str, new_username: str = "") -> None:
    if not _matches(initialize_account(store), username, current_password):
        raise HTTPException(status_code=401, detail="当前账号或密码错误")
    if not new_password:
        raise HTTPException(status_code=400, detail="新密码不能为空")
    next_username = new_username.strip() or username
    store.write_value("web_auth_account", {"username": next_username, "version": secrets.token_hex(16), **_password_record(new_password)})


def unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "请先登录"}, status_code=401)
