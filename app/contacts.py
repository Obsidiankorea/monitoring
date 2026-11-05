"""우려지역 담당자 연락처 — 상황판단 모드 화면에서만 보인다. AI(LLM · 헤르메스)에는 넘기지 않는다.

파일: 상태 폴더의 contacts.csv(PC data/contacts.csv · NAS /state/contacts.csv) — git · 위키 · 위키 NAS 사본 어디에도 두지 않는다.
  위키 data/인명피해 우려지역.csv 와 같은 '지역ID' 로 잇는다(풍수해 업무 위키 세션이 hwpx 에서 뽑은 연락처_연결.csv 그대로).
⚠️ AI 쪽 코드(ai.py · aireport.py · llm.py · aiwatch.py)는 이 모듈을 부르지 않는다 — tests/test_contacts.py 가 지킨다.
⚠️ 대시보드에는 로그인이 없다 — 설정 › AI › 연락처 잠금 번호를 두면 그 번호를 아는 화면만 연다(헤더 x-pin, DB 에는 해시만).
"""
from __future__ import annotations

import csv
import hashlib
import hmac

from . import ai, config, db

FILE = config.STATE / "contacts.csv"
_C: dict = {}


def _rows() -> dict[str, dict]:
    """지역ID → 연락처 줄. 파일이 바뀌면(mtime) 다시 읽는다."""
    try:
        key = FILE.stat().st_mtime
    except OSError:
        return {}
    if _C.get("key") != key:
        with open(FILE, encoding="utf-8-sig", newline="") as f:
            _C.update(key=key, rows={r["지역ID"]: r for r in csv.DictReader(f) if r.get("지역ID")})
    return _C["rows"]


def _h(pin: str) -> str:
    return hashlib.sha256(("gn-contacts:" + pin).encode()).hexdigest()


def locked() -> bool:
    return bool(db.get_setting("contacts_pin", ""))


def pin_ok(pin: str | None) -> bool:
    want = db.get_setting("contacts_pin", "")
    return not want or hmac.compare_digest(want, _h(pin or ""))


def set_pin(old: str, new: str) -> None:
    """잠금 번호 바꾸기 — 이미 있으면 옛 번호가 맞아야 한다. new 가 비면 잠금을 푼다."""
    if not pin_ok(old):
        raise PermissionError("지금 잠금 번호가 맞지 않다")
    if new and (len(new) < 4 or not new.isdigit()):
        raise ValueError("숫자 4자리 이상")
    db.put_setting("contacts_pin", _h(new) if new else "")


def of_sigun(sigun: str) -> dict:
    """시군 하나 — 읍면동 → [{지구 · 유형 · 담당1/2 · 번호 · 확인}]. 유형 · 대피장소는 위키 CSV 에서(같은 지역ID)."""
    rows = _rows()
    if not rows:
        return {"on": False, "emd": {}}
    full = ai.SIGUN_FULL.get(sigun, sigun)
    wiki = {}
    try:
        with open(ai.wiki() / "data" / "인명피해 우려지역.csv", encoding="utf-8-sig", newline="") as f:
            wiki = {r["지역ID"]: r for r in csv.DictReader(f) if r.get("시군") == full}
    except (OSError, KeyError):
        pass
    out: dict[str, list] = {}
    for rid, r in rows.items():
        if r.get("시군") != full:
            continue
        w = wiki.get(rid, {})
        people = [{"who": r.get(f"담당{i}") or "", "tel": r.get(f"담당{i}_연락처_정규화") or r.get(f"담당{i}_연락처") or ""}
                  for i in (1, 2) if r.get(f"담당{i}_연락처") or r.get(f"담당{i}")]
        out.setdefault(r.get("읍면동") or "", []).append({
            "id": rid, "name": r.get("지구명") or "", "ri": r.get("리") or "", "jibun": r.get("지번") or "", "kind": w.get("유형", ""),
            "fam": ai.FAMILY_OF.get(w.get("유형", ""), "야외·기타"),         # 상황판단 모드의 유형 줄(산사태 · 하천 · 지하공간)에 붙인다
            "shelter": w.get("대피장소", ""), "people": people, "check": r.get("연락처확인") or ""})
    return {"on": True, "emd": out, "n": sum(len(v) for v in out.values())}
