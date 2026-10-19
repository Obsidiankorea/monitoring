"""서버(언레이드 도커) 갱신 — 화면의 '서버 갱신' 단추.

컨테이너는 도커를 만질 수 없다(권한을 주지 않는다). 그래서 **파일로 부탁만 한다** — state/update/ 에
`request`(갱신) · `check`(GitHub 다시 확인)를 두면, 언레이드 예약 작업(deploy/unraid/updater.sh, 1분마다)이
deploy.sh 를 돌리고 `status.json`(지금 판 · GitHub 최신 · 밀린 커밋 · 마지막 갱신 결과)을 적는다.

⚠️ 자동 갱신은 하지 않는다 — 새 판이 있으면 '새 판 있음'만 보이고, 누를 때만 갱신한다(관제 · 발표 중 재시작 막기).
⚠️ status.json 이 몇 분째 안 바뀌면 예약 작업이 안 도는 것이다(재부팅 뒤 등) — 화면이 그렇게 적는다.
PC(이 폴더가 git 저장소)는 app/update.py 의 '지금 받기'를 쓴다 — 이것은 서버용이다.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from . import config

STALE_S = 5 * 60             # 예약 작업은 1분마다 적는다 — 5분 넘게 조용하면 안 도는 것


def _dir() -> Path:
    return config.STATE / "update"


def status() -> dict:
    d = _dir()
    p = d / "status.json"
    if not p.exists():
        return {"available": False, "reason": "서버 갱신 장치(updater.sh 예약 작업)가 없다 — 언레이드 서버에서만"}
    try:
        j = json.loads(p.read_text("utf-8"))
    except ValueError:
        j = {}
    age = time.time() - p.stat().st_mtime
    j.update(available=True, version=os.environ.get("APP_VERSION") or j.get("running"),
             requested=(d / "request").exists(), checking=(d / "check").exists(),
             updater_age_s=round(age), updater_stale=age > STALE_S)
    return j


def ask(action: str, who: str = "") -> dict:
    """action = deploy(갱신) | check(GitHub 다시 확인). 파일 하나를 둔다 — 1분 안에 예약 작업이 집어 간다."""
    if action not in ("deploy", "check"):
        raise ValueError("action 은 deploy | check")
    d = _dir()
    if not (d / "status.json").exists():
        raise FileNotFoundError("서버 갱신 장치가 없다")
    name = "request" if action == "deploy" else "check"
    (d / name).write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S} {who}".strip(), "utf-8")
    return status()
