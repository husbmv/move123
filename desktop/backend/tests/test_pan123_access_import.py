import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app import main
from app.session_store import SessionStore


def fake_access_token(expires_at: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expires_at}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class AccessTokenImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_access_token_is_verified_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            session_store = SessionStore(Path(directory))
            token = fake_access_token(int(time.time()) + 3600)
            response = httpx.Response(200, json={"code": 0, "data": {"uid": 123, "nickname": "Test User"}})
            client = AsyncMock()
            client.get.return_value = response
            client.__aenter__.return_value = client
            with patch.object(main, "store", session_store), patch.object(
                main.transfer_service, "reset_pan123_authorization", new_callable=AsyncMock
            ) as reset, patch.object(main.httpx, "AsyncClient", return_value=client):
                result = await main.import_pan123_access_token(main.Pan123AccessTokenImportRequest(accessToken=token))
                self.assertTrue(result.authenticated)
                self.assertTrue(result.accessOnly)
                self.assertEqual(result.profile["uid"], 123)
                reset.assert_awaited_once()
            saved = SessionStore(Path(directory)).read_session()
            self.assertEqual(saved["accessToken"], token)
            self.assertEqual(saved["refreshToken"], "")

    async def test_expired_access_token_is_rejected(self):
        token = fake_access_token(int(time.time()) - 1)
        with self.assertRaises(HTTPException) as caught:
            await main.import_pan123_access_token(main.Pan123AccessTokenImportRequest(accessToken=token))
        self.assertEqual(caught.exception.status_code, 400)
