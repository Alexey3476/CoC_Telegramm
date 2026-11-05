import asyncio

import httpx
import pytest

from app.cache import TTLCache
from app.coc_client import (
    RateLimitError,
    UnauthorizedError,
    fetch_with_cache,
    get_clan_games,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.urls: list[str] = []

    async def get(self, url: str):
        self.urls.append(url)
        return self.response


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, UnauthorizedError), (429, RateLimitError)],
)
def test_api_statuses_are_not_success_payloads(status, error):
    client = FakeClient(FakeResponse(status, {}))

    with pytest.raises(error):
        run(fetch_with_cache(client, TTLCache(), "status", "https://example.invalid"))


def test_clan_games_reports_public_api_limitation(monkeypatch):
    monkeypatch.setattr("app.coc_client.settings.coc_clan_tag", "#2PRGP0L22")
    client = FakeClient(FakeResponse(200, {"tag": "#2PRGP0L22", "name": "Test clan"}))

    result = run(get_clan_games(client, TTLCache()))

    assert result["currentGames"] is None
    assert result["unsupported"] is True
    assert "not available" in result["message"]


def test_request_errors_are_explicit():
    class BrokenClient:
        async def get(self, url: str):
            raise httpx.ConnectError("offline")

    with pytest.raises(RuntimeError, match="unavailable"):
        run(fetch_with_cache(BrokenClient(), TTLCache(), "offline", "https://example.invalid"))
