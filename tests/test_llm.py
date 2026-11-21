from app import llm


def test_claude_env_token_file(tmp_path, monkeypatch):
    """config/claude/token.txt — 값만 한 줄(BOM 괜찮음) 또는 KEY=값. API 키가 있으면 빼서 구독으로 나가게."""
    f = tmp_path / "token.txt"
    monkeypatch.setattr(llm, "TOKEN_FILE", f)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in llm._claude_env()
    f.write_text("﻿tok-1\n", "utf-8")
    env = llm._claude_env()
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-1" and "ANTHROPIC_API_KEY" not in env
    f.write_text("CLAUDE_CODE_OAUTH_TOKEN = tok-2\n", "utf-8")
    assert llm._claude_env()["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-2"



def test_mode_setting(tdb, tmp_path, monkeypatch):
    """설정 › AI 답변이 환경변수를 덮는다 — 자동이면 환경변수, 끔이면 없음, 로컬은 그대로."""
    import pytest
    monkeypatch.setattr(llm, "TOKEN_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("GN_AI", "claude-cli")
    assert llm.mode() == "claude-cli"
    llm.put_setting({"mode": "off"})
    assert llm.mode() is None
    s = llm.put_setting({"mode": "local", "url": "http://127.0.0.1:8080/", "model": "qwen3-8b"})
    assert llm.mode() == "local" and s["url"] == "http://127.0.0.1:8080"
    with pytest.raises(ValueError):
        llm.put_setting({"mode": "local", "url": "file:///x"})
    with pytest.raises(ValueError):
        llm.put_setting({"mode": "gpt"})


def test_openai_strips_think_and_fence(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "<think>음</think>\n```\n■ 지금 판단\n- 할 일\n```"}}]}
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: R())
    assert llm._openai("http://x", "", "", "s", "u") == "■ 지금 판단\n- 할 일"
