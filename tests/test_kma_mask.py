"""기상청 요청이 실패해도 오류 글에 인증키가 섞여 나가지 않는다(수집 기록 · /api/status · 로그로 간다)."""
import asyncio

import httpx
import pytest

from app import config, kma


def test_error_text_hides_key(monkeypatch):
    monkeypatch.setattr(config, "ORG_API_KEY", "SECRETKEY1234567890")
    monkeypatch.setattr(kma, "HTTP_RETRY", 0)

    class Cli:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            return httpx.Response(403, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(kma.httpx, "AsyncClient", Cli)
    with pytest.raises(kma.KmaError) as e:
        asyncio.run(kma.fetch_bytes("/x", {"a": 1}))
    assert "SECRETKEY" not in str(e.value) and "***" in str(e.value)
