"""AI 상황판단의 자유 질문 — LLM 백엔드를 고른다(GN_AI). 숫자 계산 · 기준 대조는 LLM 에 맡기지 않는다(app/ai.py).

  GN_AI 없음      — 끔. 예상 질문(규칙)만 답한다
  GN_AI=openai    — OpenAI 호환 /v1/chat/completions. NAS Hermes(API 서버) 등. GN_AI_URL · GN_AI_KEY · GN_AI_MODEL
  GN_AI=claude-cli — 이 PC 에 깔린 `claude -p`(사용자 로그인 · 사용량). **시험용** — 느리고(수십 초) PC 가 켜져 있어야 한다.
                     도구를 다 막고(읽기 · 쓰기 · 웹 없이) 받은 맥락만으로 답하게 한다.
⚠️ 키는 config/api_keys.txt 또는 환경변수로만. 로그 · 화면에 찍지 않는다.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import httpx

from . import config

TIMEOUT = 150
_DENY = "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task Agent"


def mode() -> str | None:
    m = (os.environ.get("GN_AI") or "").strip().lower()
    return m if m in ("openai", "claude-cli") else None


def ask(system: str, user: str) -> str:
    m = mode()
    if m == "openai":
        url = os.environ.get("GN_AI_URL", "").rstrip("/")
        key = os.environ.get("GN_AI_KEY", "")
        if not url:
            raise RuntimeError("GN_AI_URL 이 없다")
        r = httpx.post(f"{url}/v1/chat/completions", timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {key}"} if key else {},
                       json={"model": os.environ.get("GN_AI_MODEL", "default"),
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if m == "claude-cli":
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("claude 명령이 없다")
        p = subprocess.run([exe, "-p", "--output-format", "text", "--no-session-persistence",
                            "--append-system-prompt", system, "--disallowedTools", _DENY],
                           input=user, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
                           cwd=str(config.ROOT / "data"))
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or "claude 실패")[-300:])
        return p.stdout.strip()
    raise RuntimeError("LLM 이 꺼져 있다(GN_AI)")
