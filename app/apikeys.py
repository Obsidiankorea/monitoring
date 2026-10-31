"""화면(설정 › 시스템 › API 키)에서 API 키를 보고 바꾼다 — config/api_keys.txt 에 쓴다(저장소에는 올라가지 않는 파일).

⚠️ 값은 화면으로 돌려주지 않는다(설정됨 · 끝 네 글자만). 쓸 수 있는 이름은 아래 목록뿐이다.
   환경변수로 준 키는 그 값이 우선이라 이 화면에서 바꿔도 다시 켤 때 환경변수가 이긴다.
"""
from __future__ import annotations

import os

from . import config

# (이름, 화면에 보일 말, 어디에 쓰나)
EDITABLE = [
    ("ORG_API_KEY", "기상청 API허브(기관용)", "특보 · 격자 · 관측 수집 전부"),
    ("LAW_OC", "법제처 국가법령정보(OC)", "법령 · 행정규칙 · 자치법규 변경 감시 — 서버 공인 IP 등록 필요"),
    ("HRFCO_KEY", "홍수통제소(HRFCO)", "하천 수위 · 댐 · 보 · 홍수예보 — 지도 레이어 '하천·댐'"),
    ("DATA_GO_KR_KEY", "공공데이터포털", "산림청 산사태 예보(승인 뒤)"),
    ("TELEGRAM_BOT_TOKEN", "텔레그램 봇 토큰", "AI 알림 · 법령 알림"),
    ("TELEGRAM_CHAT_ID", "텔레그램 채팅 번호", "알림 받을 곳"),
]
NAMES = {n for n, _, _ in EDITABLE}
FILE = config.ROOT / "config" / "api_keys.txt"


def status() -> list[dict]:
    out = []
    for name, label, use in EDITABLE:
        v = config.KEYS.get(name, "")
        out.append({"name": name, "label": label, "use": use, "set": bool(v), "tail": v[-4:] if len(v) > 8 else "",
                    "env": bool(os.environ.get(name))})
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
