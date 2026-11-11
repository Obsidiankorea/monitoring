"""위키 폴더 설정 — 그 폴더의 tools/lookup.py 를 서버가 불러 돌리니, 남이 고르게 두지 않는다."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import ai, main


def test_put_only_from_this_pc():
    req = SimpleNamespace(client=SimpleNamespace(host="100.64.0.7"))
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.api_ai_wiki_put({"path": "C:/x"}, req))
    assert e.value.status_code == 403


def test_network_share_refused(monkeypatch):
    monkeypatch.setattr(ai, "wiki_check", lambda p: pytest.fail("공유 폴더를 들여다봤다"))
    assert ai.set_wiki(chr(92) * 2 + "attacker/share/w")["saved"] is False
    assert ai.set_wiki("//attacker/share/w")["saved"] is False
