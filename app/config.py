"""설정과 비밀 로드.

⚠️ 키는 코드에 넣지 않는다. config/api_keys.txt 또는 .env 에서만 읽는다.
   기본값 딕셔너리에 넣으면 그대로 커밋된다(pitfalls 13).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
DB_PATH = DATA / "gnweather.db"

# 기관용 키는 이 호스트에서만 동작한다. 구 호스트(apihub.kma.go.kr)에 쓰면 403.
KMA_HOST = "https://apihub-pub.kma.go.kr"


def _load_keys() -> dict[str, str]:
    """config/api_keys.txt(KEY=VALUE)와 환경변수를 합쳐 읽는다."""
    out: dict[str, str] = {}
    f = ROOT / "config" / "api_keys.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    for k in ("ORG_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


KEYS = _load_keys()
ORG_API_KEY = KEYS.get("ORG_API_KEY", "")

# 수집 주기(초). 자료마다 발표 리듬이 달라 하나로 묶지 않는다.
#   특보 — 발표 리듬이 없다. 아무 때나 나온다.
#   초단기예측 — 발표 주기 10분, 실제로는 발표 +2~8분 뒤에 올라온다.
#   강수량 — 정시 자료 + 최근 구간은 매분자료로 보강.
INTERVALS = {
    "alerts": 60,
    "rain": 600,
    "forecast": 600,
    "qpf": 600,
}

# 화면이 폴링하는 기본 주기(초). 패널마다 따로 두고 화면에서 바꾼다.
# ⚠️ 이 값을 바꿔도 기상청 호출량은 변하지 않는다 — 화면은 DB만 읽는다.
POLL_DEFAULT = {"rain": 600, "forecast": 600, "alerts": 60, "qpf": 600}

HTTP_TIMEOUT = 30.0   # 기상청은 타임아웃이 잦다
HTTP_RETRY = 1        # 재시도는 1회까지. 밀리면 복구 시 알림이 쏟아진다.

CACHE.mkdir(parents=True, exist_ok=True)
