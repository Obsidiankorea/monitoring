"""법령 변경 감시 — 위키가 인용하는 법령이 바뀌었거나 바뀔 예정이면 알리고, 위키를 고칠 '제안' 파일을 남긴다.

하루 한 번(서버 한 곳) 법제처 국가법령정보 Open API 로 감시 목록(config/law_watch.json)의 법령마다 현행 · 시행예정을 본다.
  · 처음 한 번은 지금 값을 기준으로 기억만 한다(제안 없음).
  · 그 뒤 현행 법령일련번호 · 시행일이 바뀌었거나 새 '시행예정'이 생기면 제안 파일을 쓴다 — STATE/law/proposals/날짜-법령명.md
    (위키에서 그 법령을 인용하는 페이지 목록 · 원문 링크 · 할 일). **위키는 고치지 않는다** — 검토 · 반영은 사람이 위키 쪽에서 한다.
  · 텔레그램 키가 있으면 한 줄로 알린다.
⚠️ 인증키 OC 는 config/api_keys.txt 의 LAW_OC(법제처 가입 아이디). 법제처가 호출하는 서버의 공인 IP 를 미리 등록해 두라고 한다 —
   안 하면 '사용자 정보 검증 실패'가 온다(오류로 기록하고 제안은 만들지 않는다). 응답 필드명은 법제처 공식 안내 기준이며 실제 호출로 확인이 필요하다.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from . import ai, aiwatch, config, db

log = logging.getLogger("lawwatch")

URLS = ("https://www.law.go.kr/DRF/lawSearch.do", "http://www.law.go.kr/DRF/lawSearch.do")
WATCH_FILE = config.ROOT / "config" / "law_watch.json"
OUT = config.STATE / "law" / "proposals"


def watch_list() -> list[dict]:
    return json.loads(WATCH_FILE.read_text("utf-8"))["laws"]


def _rows(obj) -> list[dict]:
    """응답 어디에 있든 '법령명한글'을 가진 항목들(목록 하나면 dict, 여럿이면 list 로 오는 것을 모두 받는다)."""
    if isinstance(obj, dict):
        if "법령명한글" in obj:
            return [obj]
        return [r for v in obj.values() for r in _rows(v)]
    if isinstance(obj, list):
        return [r for v in obj for r in _rows(v)]
    return []


def _fetch(name: str, nw: int) -> list[dict]:
    """법령 목록 조회(target=eflaw) — nw 3 = 현행 · 2 = 시행예정. 법령명이 정확히 같은 것만."""
    oc = config.KEYS.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC 없음 — config/api_keys.txt")
    err = None
    for url in URLS:                                       # https 가 안 되면 http(법제처 안내 예시는 http)
        try:
            r = httpx.get(url, timeout=30, verify=config.VERIFY_SSL,
                          params={"OC": oc, "target": "eflaw", "type": "JSON", "query": name, "nw": nw, "display": 100})
            r.raise_for_status()
            try:
                body = r.json()
            except ValueError:
                raise RuntimeError(r.text[:120].strip() or "JSON 이 아닌 응답")
            return [x for x in _rows(body) if x.get("법령명한글") == name]
        except (httpx.HTTPError, RuntimeError) as e:
            err = e
    raise RuntimeError(f"{name}: {str(err)[:150]}")


def _snap(name: str) -> dict:
    cur = _fetch(name, 3)
    pend = _fetch(name, 2)
    c = cur[0] if cur else {}
    return {"serial": c.get("법령일련번호"), "enforce": c.get("시행일자"), "promul": c.get("공포일자"), "kind": c.get("제개정구분명"),
            "pending": sorted(f"{p.get('법령일련번호')}|{p.get('시행일자')}|{p.get('제개정구분명')}" for p in pend)}


def _changes(name: str, old: dict | None, new: dict) -> list[str]:
    """이전 기억과 지금을 견줘 사람이 읽을 변경 줄을 낸다. 이전 기억이 없으면(첫 실행) 없음."""
    if old is None:
        return []
    out = []
    if (old.get("serial"), old.get("enforce")) != (new["serial"], new["enforce"]):
        out.append(f"현행 변경 — 시행일 {old.get('enforce')} → {new['enforce']} (공포 {new['promul']}, {new['kind']})")
    fresh = sorted(set(new["pending"]) - set(old.get("pending") or []))
    for p in fresh:
        sn, ef, kd = (p.split("|") + ["", ""])[:3]
        out.append(f"시행예정 개정 공포 — 시행일 {ef} ({kd}, 법령일련번호 {sn})")
    return out


def _cites(name: str, aliases: list[str]) -> list[str]:
    """위키에서 이 법령을 인용하는 페이지(상대 경로, .md 뗀 이름) — 위키가 없으면 빈 목록."""
    try:
        root = ai.wiki()
    except Exception:                                      # noqa: BLE001
        return []
    keys = [name, *aliases]
    hit = []
    for f in sorted(root.rglob("*.md")):
        if "raw" in f.relative_to(root).parts[:1]:
            continue
        try:
            t = f.read_text("utf-8")
        except OSError:
            continue
        if any(k in t for k in keys):
            hit.append(f.stem)
    return hit


def _write(name: str, aliases: list[str], lines: list[str], now: datetime) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{now:%Y-%m-%d}-{re.sub(r'[^0-9A-Za-z가-힣]+', '_', name)}.md"
    cites = _cites(name, aliases)
    f.write_text("\n".join([
        "---", "type: 제안", "status: 검토대기", f"법령: {name}", f"감지일: {now:%Y-%m-%d}", "---",
        f"# 법령 변경 감지 — {name}", "",
        *[f"- {x}" for x in lines], "",
        "## 위키에서 이 법령을 인용하는 페이지", *([f"- [[{c}]]" for c in cites] or ["- (찾지 못함)"]), "",
        f"## 원문\n- https://www.law.go.kr/법령/{quote(name)}", "",
        "## 할 일", "1. 원문(신구조문 대비)으로 바뀐 조문을 확인한다.",
        "2. 위 페이지의 해당 조문 · 판본 · 기준일을 고친다(숫자는 원문에서만).", "3. [[log]] 에 한 줄 적고 이 파일의 status 를 `처리됨`으로 바꾼다.", ""]), "utf-8")
    return f


def check(now: datetime | None = None) -> dict:
    """감시 목록 전부를 한 번 본다 → {checked, changed: [(법령, 줄들)], errors: [...] , first: bool}."""
    now = now or datetime.now()
    state = db.get_setting("law_state", {}) or {}
    first = not state
    changed, errors = [], []
    for w in watch_list():
        name = w["name"]
        try:
            new = _snap(name)
        except RuntimeError as e:
            errors.append(str(e))
            continue
        if not new["serial"] and not new["pending"]:
            errors.append(f"{name}: 법제처 목록에 없다(법령명 확인)")
            continue
        lines = _changes(name, state.get(name), new)
        if lines:
            _write(name, w.get("aliases", []), lines, now)
            changed.append((name, lines))
        state[name] = new
    db.put_setting("law_state", state)
    return {"checked": len(watch_list()), "changed": changed, "errors": errors, "first": first}


def status() -> dict:
    return {"on": bool(config.KEYS.get("LAW_OC")), "last": db.get_setting("law_last", {}) or {},
            "proposals": sorted(p.name for p in OUT.glob("*.md")) if OUT.exists() else []}


async def run() -> dict:
    """스케줄러가 하루 한 번 부른다(서버 한 곳). 키가 없거나 시연 서버면 건너뛴다."""
    import asyncio
    if config.DEMO or not config.KEYS.get("LAW_OC"):
        return {"skipped": "키 없음 또는 시연"}
    at = datetime.now().strftime("%m.%d %H:%M")
    try:
        r = await asyncio.to_thread(check)
    except Exception as e:                                 # noqa: BLE001
        db.put_setting("law_last", {"at": at, "err": str(e)[:200]})
        log.warning("법령 감시 실패: %s", e)
        return {"error": str(e)[:200]}
    db.put_setting("law_last", {"at": at, "checked": r["checked"], "changed": [n for n, _ in r["changed"]],
                                "errors": r["errors"][:5], "first": r["first"]})
    if r["changed"] and aiwatch.ready():
        try:
            await aiwatch.send("📜 법령 변경 감지 — " + " · ".join(f"{n}: {l[0]}" for n, l in r["changed"][:5])
                               + "\n위키를 고칠 제안 파일이 생겼다(법령 변경 제안). 검토 후 반영.")
        except Exception as e:                             # noqa: BLE001
            log.warning("법령 알림 실패: %s", aiwatch._mask(e)[:100])
    return {k: r[k] for k in ("checked", "errors", "first")} | {"changed": [n for n, _ in r["changed"]]}
