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
    for k in ("ORG_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
              "DISABLE_SSL_VERIFICATION", "BANGJAE_ID", "BANGJAE_PW",
              "BANGJAE_BASE"):
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
    "qpf": 60,          # 발표를 놓치지 않으려면 자주 깨야 한다.
                        # 다만 감시 구간 밖에서는 기상청을 부르지 않는다.
    "bangjae": 600,     # 스방 시군 평균. 기상청과 다른 서버라 따로 돈다.
}

# 화면이 폴링하는 기본 주기(초). 패널마다 따로 두고 화면에서 바꾼다.
# ⚠️ 이 값을 바꿔도 기상청 호출량은 변하지 않는다 — 화면은 DB만 읽는다.
POLL_DEFAULT = {"rain": 600, "forecast": 600, "alerts": 60, "qpf": 600,
                "bangjae": 600}

# ── 예측 분포 이미지 — 호출량을 여기서 조절한다 ───────────────────────
# 한 발표분의 장수 = ceil(최대 선행시간 / 간격).
#   10분 간격 · 6시간 → 36장   |   20분 간격 · 3시간 → 9장
# 발표는 10분마다 나오므로 이 숫자가 곧 10분당 호출 수다.
QPF = {
    "step": 10,        # 프레임 간격(분) 10 · 20 · 30
    "ahead": 360,      # 최대 선행시간(분) 180 · 240 · 360
    "size": 1800,      # 받아 올 이미지 크기
    "keep": 3,         # 남겨 둘 발표분 수
    # ⚠️ 이 API는 지금 시각의 발표분을 바로 주지 않는다.
    # 실측: 19:44에 확인한 최신 가용분이 19:30 — 보통 20~30분 뒤처진다.
    # 그래서 '정시 +n분에 확인' 같은 창은 두지 않고, 가진 것 다음 슬롯부터
    # 앞으로 훑어 그림이 있는 마지막 슬롯을 찾는다. docs/02-발표주기.md 참고.
}

HTTP_TIMEOUT = 30.0   # 기상청은 타임아웃이 잦다
HTTP_RETRY = 1        # 재시도는 1회까지. 밀리면 복구 시 알림이 쏟아진다.

# ── TLS 인증서 검증 ───────────────────────────────────────────────────
# ⚠️ **내부망에서는 꺼야 한다.** 기관 프록시가 인증서를 자기 것으로 갈아 끼워서
#    체인에 self-signed 가 섞인다(실측: verify=True → CERTIFICATE_VERIFY_FAILED,
#    verify=False → 200). 옆 프로젝트(재난상황보고서·bangjae)도 같은 이유로 끈다.
#    바깥망에서 쓰거나 사내 CA 를 신뢰 저장소에 넣었다면 아래를 0 으로 바꾼다.
#      config/api_keys.txt 에  DISABLE_SSL_VERIFICATION=0
#      또는 환경변수        DISABLE_SSL_VERIFICATION=0
def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name, KEYS.get(name))
    if v is None:
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")


DISABLE_SSL_VERIFICATION = _flag("DISABLE_SSL_VERIFICATION", True)
VERIFY_SSL = not DISABLE_SSL_VERIFICATION

CACHE.mkdir(parents=True, exist_ok=True)
