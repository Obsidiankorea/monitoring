"""화면(설정 › 시스템 › API 키)에서 API 키를 보고 바꾼다 — config/api_keys.txt 에 쓴다(저장소에는 올라가지 않는 파일).

⚠️ 값은 화면으로 돌려주지 않는다(설정됨 · 끝 네 글자만). 쓸 수 있는 이름은 아래 목록뿐이다.
   환경변수로 준 키는 그 값이 우선이라 이 화면에서 바꿔도 다시 켤 때 환경변수가 이긴다.
"""
from __future__ import annotations

import os
import re
from datetime import date

from . import config

# (이름, 화면에 보일 말, 어디에 쓰나, docs/api/ 안 문서 이름) — 만료 · 발급처 · 계정은 그 문서 맨 위 칸에서 읽는다
EDITABLE = [
    ("ORG_API_KEY", "기상청 API허브(기관용)", "특보 · 격자 · 관측 수집 전부", "kma-apihub"),
    ("LAW_OC", "법제처 국가법령정보(OC)", "법령 · 행정규칙 · 자치법규 변경 감시 — 서버 공인 IP 등록 필요", "law-go-kr"),
    ("HRFCO_KEY", "홍수통제소(HRFCO)", "하천 수위 · 댐 · 보 · 홍수예보 — 지도 레이어 '하천·댐'", "hrfco"),
    ("ITS_KEY", "국가교통정보센터 재난상황정보", "호우특보 중 지하차도 침수 위험 경보 — NAS 서버에만", "its"),
    ("DATA_GO_KR_KEY", "공공데이터포털", "조위(해양조사원)", "data-go-kr"),
    ("SD_SLIDE_FCST_KEY", "재난안전데이터 · 산사태 예보", "시군 산사태 주의보 · 경보 — 레이어 '산사태'(J), 호우 · 태풍 특보 때만", "safetydata"),
    ("SD_SLIDE_PRED_KEY", "재난안전데이터 · 산사태 예측", "산림청 예측정보 — 레이어 '산사태'(J), 호우 · 태풍 특보 때만", "safetydata"),
    ("SD_RESERVOIR_KEY", "재난안전데이터 · 위험저수지", "저수지 계측기 경보 — 레이어 '위험저수지'(K)", "safetydata"),
    ("SD_FLOODMAP_KEY", "재난안전데이터 · 침수흔적도", "과거 침수 구역 — 레이어 '침수흔적'(N), 7일마다", "safetydata"),
    ("TELEGRAM_BOT_TOKEN", "텔레그램 봇 토큰", "AI 알림 · 법령 알림", "telegram"),
    ("TELEGRAM_CHAT_ID", "텔레그램 채팅 번호", "알림 받을 곳", "telegram"),
]
NAMES = {n for n, *_ in EDITABLE}
DOCS = config.ROOT / "docs" / "api"
SLUGS = {d for *_, d in EDITABLE}
FILE = config.ROOT / "config" / "api_keys.txt"


def front(slug: str) -> dict:
    """문서 맨 위 `---` 칸(줄마다 `이름: 값`)을 읽는다. 문서가 없거나 칸이 없으면 빈 값."""
    try:
        t = (DOCS / f"{slug}.md").read_text("utf-8-sig")
    except OSError:
        return {}
    m = re.match(r"---\r?\n(.*?)\r?\n---", t, re.S)
    return {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in m.group(1).splitlines())} if m else {}


def dday(text: str) -> int | None:
    try:
        return (date.fromisoformat(text) - date.today()).days
    except ValueError:
        return None


def status() -> list[dict]:
    out = []
    for name, label, use, doc in EDITABLE:
        v, f = config.KEYS.get(name, ""), front(doc)
        out.append({"name": name, "label": label, "use": use, "set": bool(v), "tail": v[-4:] if len(v) > 8 else "",
                    "env": bool(os.environ.get(name)), "doc": doc, "site": f.get("관리URL", ""), "acct": f.get("계정", ""),
                    "expire": f.get("만료", ""), "dday": dday(f.get("만료", "")), "state": f.get("상태", "")})
    return out


def save(name: str, value: str) -> None:
    """한 키를 파일에 쓰고 지금 돌고 있는 서버에도 바로 반영한다. 값이 비면 그 키를 지운다."""
    if name not in NAMES:
        raise ValueError(f"바꿀 수 없는 키: {name}")
    value = (value or "").strip()
    if any(c in value for c in "\r\n\0") or value.startswith("#"):
        raise ValueError("값에 줄바꿈이나 # 로 시작하는 글자는 쓸 수 없다")
    lines = FILE.read_text("utf-8-sig").splitlines() if FILE.exists() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0].strip() != name or ln.lstrip().startswith("#")]
    if value:
        keep.append(f"{name}={value}")
    # 제자리 쓰기 — 도커가 파일 하나만 붙여 둔 경우 새 파일로 바꿔치기(rename)하면 붙은 것이 끊긴다
    FILE.write_text("\n".join(keep).rstrip("\n") + "\n", encoding="utf-8")
    if value:
        config.KEYS[name] = value
    else:
        config.KEYS.pop(name, None)
    if name == "ORG_API_KEY":
        config.ORG_API_KEY = value
