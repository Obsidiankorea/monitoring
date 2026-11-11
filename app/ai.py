"""AI 상황판단 — 시군 하나의 '지금 수치'와 LLM 위키의 '기준'을 맞대 놓는다(판단은 사람이 · 문장은 LLM 이).

⚠️ 지금 수치는 **gn-monitor HTTP API 로만** 읽는다(이 PC · NAS 어느 쪽이든 같은 코드). NAS 의 Hermes 에이전트가
   같은 API 를 도구로 부르면 된다 — 화면 안의 함수에 기대지 않는다(deploy/hermes/gn-situation/SKILL.md).
⚠️ 기준은 LLM 위키(옵시디언 볼트, GN_WIKI)에 적힌 값만 — tools/lookup.py(우려지역 · 지구별 대피기준 원문)와
   [[통제·대피 기준]](3대 유형 통제 → 사전대피 → 긴급대피) · [[시군 상황관리반 행동매뉴얼]](상황전파) ·
   [[위기경보와 비상단계]] · [[재난문자 송출기준]].

여기서 하는 일은 **계산과 대조뿐**이다 — 조건마다 met(충족) · near(70% 이상) · no · unknown(자료가 없어 못 봄).
'예보' 조건은 초단기 RN1(앞으로 6시간), '실황' 조건은 격자 실측(500m, 읍면동 안 가장 많이 온 칸)으로 본다.
  ⚠️ 초단기 RN1 격자는 시우량 30㎜ 에서 막혀 온다(그림 분포도와 대조, 2026-10-20) — 50 · 55㎜/h '예보' 조건은 판정 불가
  ⚠️ 지구 좌표가 없다 → 읍면동 최대 칸은 지구 강우의 **상한**. 선행 5일 강우 · 토양함수 · 하천수위 · 침수심은 여기 없다
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import httpx

from . import tide

def _default_wiki() -> Path:
    """GN_WIKI 가 없으면 이 사용자 홈의 obsidian/재난(행정 PC — 환경변수 없이 압축만 풀어 둔다), 그다음 개발 PC 경로."""
    here = Path(__file__).resolve()   # 제출 묶음 — monitoring 옆(소스), 실행파일/경남강수지도 의 두 칸 위(exe)의 위키 폴더
    up = here.parents[1].parent       # ⚠️ parents[3] 은 도커(/app/app/ai.py)에 없다(IndexError 로 서버가 못 떴다) — .parent 는 뿌리에서 멈춘다
    for c in (up / "위키", up.parent / "위키", Path.home() / "obsidian" / "재난", Path(r"C:\Users\ms\obsidian\재난")):
        if (c / "tools" / "lookup.py").is_file():
            return c
    return Path.home() / "obsidian" / "재난"


DEFAULT_WIKI = str(_default_wiki())


_WS: list = [0.0, None]                                 # (언제, 값) — 판정 한 번에 수만 번 불려 DB 를 매번 읽으면 느렸다(2026-11)


def wiki_source() -> tuple[Path, str]:
    """위키 폴더와 그 출처 — 화면 설정(DB ai_wiki) > 환경변수 GN_WIKI > 기본. 5초 동안은 앞에 읽은 것(set_wiki 가 비운다)."""
    import time as _t
    if _WS[1] and _t.time() - _WS[0] < 5:
        return _WS[1]
    _WS[1] = _wiki_source()
    _WS[0] = _t.time()
    return _WS[1]


def _wiki_source() -> tuple[Path, str]:
    from . import db
    try:
        v = str(db.get_setting("ai_wiki", "") or "").strip()
    except Exception:                                   # noqa: BLE001 — DB 가 아직 없을 때
        v = ""
    if v:
        return Path(v), "설정"
    if os.environ.get("GN_WIKI"):
        return Path(os.environ["GN_WIKI"]), "환경변수"
    return Path(DEFAULT_WIKI), "기본"


def wiki() -> Path:
    return wiki_source()[0]


def wiki_check(path: Path) -> dict:
    """그 폴더가 쓸 수 있는 위키인가 — 폴더 · tools/lookup.py · 우려지역 CSV · 문서 수."""
    md = sum(1 for x in path.rglob("*.md") if ".obsidian" not in x.parts) if path.is_dir() else 0
    has = (path / "tools" / "lookup.py").exists()
    return {"path": str(path), "dir": path.is_dir(), "lookup": has,
            "csv": (path / "data" / "인명피해 우려지역.csv").exists(), "rules": (path / RULES_CSV).exists(),
            "md": md, "ok": path.is_dir() and has and md > 0}


# ── 판정값 — 위키 data/판정값.csv([[판정값]]). 숫자 기준은 여기서만 읽는다. 못 읽으면 2026-05 값 + 경고 ──
RULES_CSV = Path("data") / "판정값.csv"
RULE_DEFAULT = {"비상1단계_호우주의보_시군": 4, "비상2단계_호우경보_시군": 3, "긴급재난문자_1시간": 50, "긴급재난문자_3시간": 90,
                "긴급재난문자_1시간_단독": 72, "상황전파_1시간": 20, "상황전파_일": 100,
                # [[통제·대피 기준]] 3대 유형 — 조건의 짝(그리고 · 예보/실황)은 ladders() 코드에
                "산사태_통제_누적": 100, "산사태_통제_예보시우량": 20, "산사태_사전대피_누적": 200, "산사태_사전대피_예보시우량": 50,
                "산사태_사전대피_선행5일": 120, "산사태_사전대피_야간예보시우량": 30, "산사태_긴급대피_시우량": 50,
                "산사태_긴급대피_일": 170, "산사태_긴급대피_누적": 270, "하천_통제_시우량": 30, "하천_통제_지속시간": 3,
                "하천_사전대피_누적": 200, "하천_사전대피_예보시우량": 30, "하천_긴급대피_누적": 200, "하천_긴급대피_시우량": 30,
                "지하공간_사전대피_15분": 20, "지하공간_사전대피_예보시우량": 55, "지하공간_긴급대피_15분": 30,
                "지하공간_긴급대피_시우량": 55}
_RULES: dict = {}


def rules() -> dict:
    """{v: {항목: 값}, err: [...], src: 위키|기본값} — CSV 가 바뀌면(mtime) 다시 읽는다. mtime 은 5초에 한 번만 본다(판정 한 번에 수천 번 불린다)."""
    import csv
    import time as _t
    if _RULES.get("out") and _t.time() - _RULES.get("seen", 0) < 5:
        return _RULES["out"]
    _RULES["seen"] = _t.time()
    try:
        p = wiki() / RULES_CSV
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return {"v": dict(RULE_DEFAULT), "err": ["위키에 data/판정값.csv 가 없다"], "src": "기본값"}
    if _RULES.get("key") != key:
        v, err = dict(RULE_DEFAULT), []
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                got = {r.get("항목", "").strip(): (r.get("값") or "").strip() for r in csv.DictReader(f)}
        except (OSError, csv.Error, UnicodeDecodeError) as e:
            got, err = {}, [f"data/판정값.csv 를 못 읽었다 ({type(e).__name__})"]
        for k in RULE_DEFAULT:
            if k not in got:
                err.append(f"{k} 줄이 없다")
            elif got[k].isdigit() and int(got[k]) > 0:
                v[k] = int(got[k])
            else:
                err.append(f"{k} = {got[k]!r} — 양의 정수가 아니다")
        if (v["비상1단계_호우주의보_시군"] < 2 or v["긴급재난문자_1시간_단독"] <= v["긴급재난문자_1시간"]
                or v["산사태_사전대피_누적"] <= v["산사태_통제_누적"] or v["지하공간_긴급대피_15분"] <= v["지하공간_사전대피_15분"]):
            err.append("단계가 겹친다 — 전부 기본값으로")
            v = dict(RULE_DEFAULT)
        _RULES.update(key=key, val={"v": v, "err": err, "src": "위키" if not err else "위키(일부 기본값)"})
    _RULES["out"] = _RULES["val"]
    return _RULES["out"]


def R(k: str) -> int:
    return rules()["v"][k]


def cbs_rule() -> str:
    return f"1시간 {R('긴급재난문자_1시간')}㎜ + 3시간 {R('긴급재난문자_3시간')}㎜ 동시, 또는 1시간 {R('긴급재난문자_1시간_단독')}㎜"


def relay_rule() -> str:
    return f"시간당 {R('상황전파_1시간')}㎜ · 일 {R('상황전파_일')}㎜"


def is_cbs(r1: float, r3: float) -> bool:
    """[[재난문자 송출기준]] 기상청 호우 긴급재난문자."""
    return (r1 >= R("긴급재난문자_1시간") and r3 >= R("긴급재난문자_3시간")) or r1 >= R("긴급재난문자_1시간_단독")


def is_relay(r1: float, r24: float) -> bool:
    """[[시군 상황관리반 행동매뉴얼]] 상황전파."""
    return r1 >= R("상황전파_1시간") or r24 >= R("상황전파_일")


WINDOWS = (1, 3, 12, 24, 48)
RN1_CAP = 30.0
SIGUN_FULL = {"창원": "창원시", "진주": "진주시", "통영": "통영시", "사천": "사천시", "김해": "김해시", "밀양": "밀양시",
              "거제": "거제시", "양산": "양산시", "의령": "의령군", "함안": "함안군", "창녕": "창녕군", "고성": "고성군",
              "남해": "남해군", "하동": "하동군", "산청": "산청군", "함양": "함양군", "거창": "거창군", "합천": "합천군"}

# 우려지역 유형 → 기준 가족([[통제·대피 기준]] 은 산사태 · 하천 · 지하공간 셋, 나머지는 위키의 다른 기준)
FAMILY = {
    "산사태": ["산사태", "산사태취약지구", "급경사지(붕괴위험)", "급경사지(위험사면)", "태양광(경사지)", "태양광(산지)",
             "산지부 복개시설", "시특법시설(붕괴우려)", "자연재해위험개선지구(붕괴)", "소규모시설(농로)"],
    "하천": ["하천변산책로", "둔치주차장", "세천", "소교량", "위험저수지, 댐"],
    "지하공간": ["지하차도", "지하시설,지하주차장,지하상가", "반지하주택가"],
    "침수·해안": ["침수우려도로", "침수위험", "해안가 저지대", "해안가 산책로", "해일위험"],
    "야외·기타": ["야영장", "낚시터", "수상레져", "기타", "1종", "2종", "3종"],
}
FAMILY_OF = {t: f for f, ts in FAMILY.items() for t in ts}
FAMILY_WIKI = {"산사태": "[[통제·대피 기준]] · [[산사태 위험지역]]", "하천": "[[통제·대피 기준]]",
               "지하공간": "[[통제·대피 기준]]", "침수·해안": "[[재난경보와 폭풍해일 기준]] · [[인명피해 우려지역]]",
               "야외·기타": "[[인명피해 우려지역]]"}

_COND = re.compile(r"(?:(\d+)\s*시간|(일)\s*강우|(누적)\s*강우|(시간당))\s*(?:강우\s*)?(\d+(?:\.\d+)?)\s*mm")


def conditions(text: str) -> list[dict]:
    """지구별 원문 대피기준 → [{win(시간), mm, label}]. 못 읽으면 빈 목록(원문을 그대로 보인다)."""
    out = []
    for h, day, acc, per, mm in _COND.findall(text or ""):
        if h:
            win, lab = int(h), f"{h}시간"
        elif day:
            win, lab = 24, "일강우(24시간으로)"
        elif acc:
            win, lab = 48, "누적(48시간으로)"
        else:
            win, lab = 1, "시간당"
        if win in WINDOWS:
            out.append({"win": win, "mm": float(mm), "label": lab})
    return out


def _st(v, need) -> str:
    if v is None:
        return "unknown"
    return "met" if v >= need else "near" if v >= 0.7 * need else "no"


def _all(*parts) -> str:
    """조건 여럿이 '그리고'로 묶였을 때 — 하나라도 unknown 이면 unknown(못 본 것을 충족으로 치지 않는다)."""
    if "unknown" in parts:
        return "unknown" if "no" not in parts else "no"
    if all(p == "met" for p in parts):
        return "met"
    return "near" if all(p in ("met", "near") for p in parts) else "no"


def _part(label: str, v, need, unit: str = "㎜", eta: dict | None = None) -> dict:
    """기준 한 토막 — 지금 값 · 기준 · 비율(%) · 남은 양. 값을 모르면 pct · left 가 None."""
    return {"label": label, "now": v, "need": need, "unit": unit,
            "pct": None if v is None else round(v / need * 100),
            "left": None if v is None else round(max(need - v, 0), 1), "eta": eta}


def _eta(v, need, hours: list, labels: list) -> dict | None:
    """쌓이는 값(누적)이 시간별 예보를 더해 기준에 처음 닿는 시각 — {'at': '14', 'i': 2}.
    예보 시간 안에 안 닿으면 {'at': None}. 이미 닿았거나 값 · 예보가 없으면 None.
    ⚠️ 창에서 빠져나가는 옛 비는 빼지 않는다 → 실제보다 이르게 나올 수 있다."""
    if v is None or v >= need or not hours:
        return None
    s = v
    for i, x in enumerate(hours):
        s += x or 0
        if s >= need:
            return {"at": labels[i] if i < len(labels) else None, "i": i}
    return {"at": None, "i": None}


def _gap(*parts: dict) -> dict | None:
    """규칙 하나(조건이 '그리고'로 묶임)가 기준에서 얼마나 먼가 — 가장 먼 조건이 병목이다.
    아는 조건이 하나도 없으면 None. 모르는 조건이 섞였으면 partial(비율은 아는 조건만)."""
    known = [p for p in parts if p["pct"] is not None]
    if not known:
        return None
    w = min(known, key=lambda p: p["pct"])
    unmet = [p for p in known if p["left"] > 0]
    partial = len(known) < len(parts)
    eta = None
    if unmet and not partial and all(p["eta"] for p in unmet):      # 안 쌓이는 조건(시우량 등)이 남았으면 시각을 말하지 않는다
        got = [p["eta"] for p in unmet]
        eta = {"at": None} if any(e["at"] is None for e in got) else max(got, key=lambda e: e["i"])
    return {"pct": w["pct"], "left": w["left"], "unit": w["unit"], "by": w["label"], "partial": partial,
            "eta": eta, "parts": list(parts)}


def gap_text(c: dict) -> str:
    """판정 한 줄(c)에 붙일 글 — '기준 78% · 남은 22㎜(일/누적) · 예보대로면 14시경 닿음'. 모르면 빈 글."""
    g = c.get("gap")
    if not g:
        return ""
    s = f"기준 {g['pct']}%"
    if g["left"]:
        s += f" · 남은 {g['left']:g}{g['unit']}({g['by']})"
    e = g["eta"]
    if e:
        s += f" · 예보대로면 {e['at']}시경 닿음" if e["at"] else " · 예보 시간 안엔 안 닿음"
    if g["partial"]:
        s += " · 일부 조건은 모름"
    return s


def rain_state(cs: list[dict]) -> tuple[int, str]:
    """우려지역 강우 기준 상태 — 위키 [[통제·대피 기준]]의 단계 이름 그대로 '사전대피 충족 · 통제 근접'(센 것부터).
    cs 는 읍면동 판정들([{stage, st}]). 톤: 0 없음 · 1 근접만 · 2 통제 충족 · 3 사전대피/긴급대피 충족."""
    rank = {"긴급대피": 3, "사전대피": 2, "통제": 1}
    seen = {(c["stage"], c["st"]) for c in cs if c["st"] in ("met", "near")}
    seen -= {(g, "near") for g, st in seen if st == "met"}        # 충족한 단계는 근접을 따로 적지 않는다
    items = sorted(seen, key=lambda x: (x[1] != "met", -rank[x[0]]))
    tone = 3 if any(st == "met" and rank[g] >= 2 for g, st in seen) else 2 if ("통제", "met") in seen else 1 if seen else 0
    return tone, " · ".join(f"{g} {'충족' if st == 'met' else '근접'}" for g, st in items)


def river_of(sigun: str) -> dict | None:
    """그 시군의 하천 수위(홍수통제소, app/river.py) — 기준 수위가 있는 관측소 가운데 가장 높은 단계(같으면 다음 단계까지 가장 가까운 곳).
    저수지 수위계(해발 값)는 하천 기준과 견줄 수 없어 뺀다. 자료가 없으면 None."""
    from . import river
    rows = [s for s in river.status()["rows"] if s["kind"] == "wl" and s.get("sigun") == sigun and s.get("stage", -1) >= 0
            and "저수지" not in s["name"] and (s["thr"][0] or 0) < 30]
    if not rows:
        return None
    b = max(rows, key=lambda s: (s["stage"], -(s.get("gap") if s.get("gap") is not None else 99)))
    dams = [s for s in river.status()["rows"] if s["kind"] != "wl" and (s.get("sigun") == sigun or (s.get("up") and s.get("rise")))]
    return {"stage": b["stage"], "name": b["name"], "wl": b["v"], "thr": b["thr"], "gap": b.get("gap"), "d1h": b.get("d1h"),
            "t": b.get("t"), "n": len(rows), "dams": [{k: d.get(k) for k in ("name", "out", "inf", "rise", "up")} for d in dams if d.get("out") is not None]}


def flood_of(sigun: str) -> list[dict]:
    """그 시군에 걸린 홍수예보 — 그 시군 지점이거나 주의 지역에 그 시군이 적힌 것."""
    from . import river
    full = SIGUN_FULL.get(sigun, sigun)
    return [s for s in river.flood() if s.get("sigun") == sigun or full in (s["fc"].get("area") or "")]


def _fld(rv: dict | None, fld: list[dict] | None, need: int) -> str:
    """홍수예보 발령이 need 단계(2 주의보 · 3 경보)에 닿았나. 발령이 없어도 하천 자료가 없으면 '모름'이다."""
    if any(s["fc"]["lv"] >= need for s in fld or []):
        return "met"
    return "no" if rv else "unknown"


def _riv(rv: dict | None, need: int) -> tuple[str, dict | None]:
    """하천 수위 단계(0 정상 · 1 관심 · 2 주의보 · 3 경보 · 4 심각)가 need 에 닿았나 → (st, gap). 한 단계 모자라면 근접."""
    if not rv:
        return "unknown", None
    st = "met" if rv["stage"] >= need else "near" if rv["stage"] == need - 1 else "no"
    t = rv["thr"][need - 1] if len(rv["thr"]) >= need else None
    gap = _gap(_part(f"{rv['name']} 수위", rv["wl"], t, "m")) if (t and rv["wl"] is not None) else None
    return st, gap


def ladders(r: dict, night: bool, alerts: list[str], rv: dict | None = None, fld: list[dict] | None = None) -> dict:
    """읍면동 하나 — [[통제·대피 기준]] 3대 유형 단계별 조건 대조(숫자는 위키 [[판정값]], 조건의 짝은 여기).
    st 는 '그 조건에 닿았나', gap 은 '기준에서 얼마나 먼가'(비율 · 남은 양 · 닿는 시각)."""
    rain, fpk, f3 = r["rain"], r["fc_peak"], r["fc_run30"]
    o1, o24, o48, q15 = rain["1h"], rain["24h"], rain["48h"], r["m15"]
    accum = max(x for x in (o24, o48) if x is not None) if (o24 is not None or o48 is not None) else None
    fcap = fpk == RN1_CAP                              # 예보가 30 에 막혔으면 그 위는 모른다(그 위 값은 가상 시연에서만 온다)
    v = rules()["v"]
    L, H, U = ({k.split("_", 1)[1]: x for k, x in v.items() if k.startswith(f"{t}_")} for t in ("산사태", "하천", "지하공간"))
    f50 = "unknown" if fpk is None or fcap else _st(fpk, L["사전대피_예보시우량"])
    f55 = "unknown" if fpk is None or fcap else _st(fpk, U["사전대피_예보시우량"])
    hoou = [a for a in alerts if a.startswith("호우")]
    fh, fl = r.get("eta_hours") or r.get("fc_hours") or [], r.get("eta_labels") or r.get("fc_labels") or []   # 도달 시각은 초단기 + 단기예보로
    fpk_ok = None if fpk is None or fcap else fpk          # 30 에 막힌 예보는 50·55 와 견줄 수 없다

    def cum(label, v, need):                               # 쌓이는 값 — 예보 시우량을 더해 닿는 시각도 본다
        return _part(label, v, need, eta=_eta(v, need, fh, fl))

    def one(label, v, need, unit="㎜"):
        return _part(label, v, need, unit)

    out = {
        "산사태": [
            {"stage": "통제", "rule": f"일/누적 {L['통제_누적']}㎜↑ + {L['통제_예보시우량']}㎜/h↑ 예보",
             "st": _all(_st(accum, L["통제_누적"]), _st(fpk, L["통제_예보시우량"])),
             "gap": _gap(cum("일/누적", accum, L["통제_누적"]), one("예보 시우량", fpk, L["통제_예보시우량"], "㎜/h"))},
            {"stage": "사전대피", "rule": f"일/누적 {L['사전대피_누적']}㎜↑ + {L['사전대피_예보시우량']}㎜/h↑ 예보",
             "st": _all(_st(accum, L["사전대피_누적"]), f50),
             "gap": _gap(cum("일/누적", accum, L["사전대피_누적"]), one("예보 시우량", fpk_ok, L["사전대피_예보시우량"], "㎜/h"))},
            # 선행 5일 120㎜ 는 대시보드가 격자로 계산한다. 뒤의 '산사태 위험 증가 예보'(산림청)는 없어서 → 충족으로는 못 친다(모름)
            {"stage": "사전대피", "rule": f"선행 5일 {L['사전대피_선행5일']}㎜↑ + 산사태 위험 증가 예보(산림청)",
             "st": _all(_st(r.get("ante"), L["사전대피_선행5일"]), "unknown"),
             "gap": _gap(one("선행 5일", r.get("ante"), L["사전대피_선행5일"]), one("산림청 예보", None, 1))},
            # 통제 누적과 '그리고'(2026-11 결정) — 누적 없이 밤 예보만으로 사전대피가 되면 통제보다 먼저 대피가 된다
            {"stage": "사전대피", "rule": f"취약시간대(21~06시) 일/누적 {L['통제_누적']}㎜↑ + {L['사전대피_야간예보시우량']}㎜/h↑ 예보",
             "st": ("no" if not night else _all(_st(accum, L["통제_누적"]), _st(fpk, L["사전대피_야간예보시우량"]))),
             "gap": _gap(cum("일/누적", accum, L["통제_누적"]), one("예보 시우량", fpk, L["사전대피_야간예보시우량"], "㎜/h")) if night else None},
            # 위키 표는 두 줄('또는')이지만 하나로 묶는다(2026-11 결정) — '또는'이면 누적 270 만으로, 시간당 비 없이도 긴급대피가 됐다
            {"stage": "긴급대피", "rule": f"누적 {L['긴급대피_누적']}㎜↑ + {L['긴급대피_시우량']}㎜/h↑ + 일 {L['긴급대피_일']}㎜↑(실황)",
             "st": _all(_st(o48, L["긴급대피_누적"]), _st(o1, L["긴급대피_시우량"]), _st(o24, L["긴급대피_일"])),
             "gap": _gap(cum("48시간", o48, L["긴급대피_누적"]), one("1시간", o1, L["긴급대피_시우량"], "㎜/h"), cum("24시간", o24, L["긴급대피_일"]))},
        ],
        "하천": [
            {"stage": "통제", "rule": f"{H['통제_시우량']}㎜/h↑ {H['통제_지속시간']}시간 이상 지속 예보", "st": _st(f3, H["통제_지속시간"]),
             "gap": _gap(one(f"{H['통제_시우량']}㎜/h↑ 이어진 시간", f3, H["통제_지속시간"], "시간"))},
            {"stage": "사전대피", "rule": f"누적 {H['사전대피_누적']}㎜↑ + {H['사전대피_예보시우량']}㎜/h↑ 예보",
             "st": _all(_st(accum, H["사전대피_누적"]), _st(fpk, H["사전대피_예보시우량"])),
             "gap": _gap(cum("일/누적", accum, H["사전대피_누적"]), one("예보 시우량", fpk, H["사전대피_예보시우량"], "㎜/h"))},
            {"stage": "긴급대피", "rule": f"누적 {H['긴급대피_누적']}㎜↑ + {H['긴급대피_시우량']}㎜/h↑ 실제",
             "st": _all(_st(accum, H["긴급대피_누적"]), _st(o1, H["긴급대피_시우량"])),
             "gap": _gap(cum("일/누적", accum, H["긴급대피_누적"]), one("1시간", o1, H["긴급대피_시우량"], "㎜/h"))},
            {"stage": "긴급대피", "rule": "호우경보 발령", "st": "met" if "호우경보" in hoou else "no"},
            # 홍수통제소 수위(app/river.py) — 시군 안 관측소 가운데 가장 높은 단계. 제방 만수위 90% · 교량 수위 90% · 댐 방류 예보는 자료가 없다
            {"stage": "통제", "rule": "홍수주의보 수준 하천수위(주의보 수위↑, 홍수통제소)", "st": _riv(rv, 2)[0], "gap": _riv(rv, 2)[1]},
            {"stage": "긴급대피", "rule": "홍수경보 수준 하천수위(경보 수위↑, 홍수통제소)", "st": _riv(rv, 3)[0], "gap": _riv(rv, 3)[1]},
            # 위키 표는 긴급대피 칸에도 '홍수주의보' 를 적었다 — 주의보 발령은 통제로 치고 나머지는 '별도 확인 필요' 로 넘긴다(aireport._gaps)
            {"stage": "통제", "rule": "홍수주의보 발령(홍수통제소)", "st": _fld(rv, fld, 2)},
            {"stage": "긴급대피", "rule": "홍수경보 발령(홍수통제소)", "st": _fld(rv, fld, 3)},
        ],
        "지하공간": [
            {"stage": "통제", "rule": "(지하차도) 호우특보 발령", "st": "met" if hoou else "no"},
            {"stage": "사전대피", "rule": f"15분 {U['사전대피_15분']}㎜↑ + 시간당 {U['사전대피_예보시우량']}㎜↑ 예보",
             "st": _all(_st(q15, U["사전대피_15분"]), f55),
             "gap": _gap(one("15분", q15, U["사전대피_15분"]), one("예보 시우량", fpk_ok, U["사전대피_예보시우량"], "㎜/h"))},
            {"stage": "긴급대피", "rule": f"15분 {U['긴급대피_15분']}㎜↑ + 시간당 {U['긴급대피_시우량']}㎜↑ 실제",
             "st": _all(_st(q15, U["긴급대피_15분"]), _st(o1, U["긴급대피_시우량"])),
             "gap": _gap(one("15분", q15, U["긴급대피_15분"]), one("1시간", o1, U["긴급대피_시우량"], "㎜/h"))},
        ],
    }
    return out


NO_WIKI = {"sites": [], "source_basis": "위키 없음(GN_WIKI) — 우려지역 · 지구별 기준이 빠진 채 수치만 본다"}


def _no_wiki(vault, sigun, emd=None, kind="all"):
    return NO_WIKI


_LK_LOCK = threading.Lock()


def _lookup_fn():
    """위키 tools/lookup.py. 위키가 없는 PC(행정 PC 등)면 빈 결과 — 보고는 수치만으로 돌아간다(deploy.sh 의 경고와 같다).
    잠금 — 판정은 시군 18곳을 스레드로 돈다. 처음에 여럿이 동시에 import 하면 한쪽이 sys.modules 를 지워 KeyError('lookup') 가 났다."""
    with _LK_LOCK:
        return _lookup_load()


@lru_cache(maxsize=1)
def _lookup_load():
    sys.modules.pop("lookup", None)                     # 위키를 바꿨으면 그 쪽 도구로
    if not (wiki() / "tools" / "lookup.py").is_file():
        return _no_wiki
    sys.path.insert(0, str(wiki() / "tools"))
    from lookup import lookup_sites  # noqa: E402 — 위키 쪽 읽기 전용 도구
    return lookup_sites


_LK: dict = {}


def _lookup():
    """위키 우려지역 조회 — CSV 가 바뀌지 않았으면 시군마다 한 번만 읽는다(보고 한 번에 18 시군을 본다)."""
    def fn(vault, sigun, emd=None, kind="all"):
        csv = Path(vault) / "data" / "인명피해 우려지역.csv"
        key = (str(vault), sigun, emd, kind, csv.stat().st_mtime if csv.exists() else 0)
        if key not in _LK:
            if len(_LK) > 256:
                _LK.clear()
            _LK[key] = _lookup_fn()(vault, sigun, emd, kind)
        return _LK[key]
    return fn


_GET: dict = {}
_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    """한 번 만든 연결을 다시 쓴다 — httpx.get 은 부를 때마다 인증서 묶음을 새로 읽어 0.4초씩 들었다."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(timeout=20)
    return _CLIENT


def _get(base: str, path: str, **params) -> dict:
    """대시보드 API — 같은 요청은 30초 안에 다시 부르지 않는다(보고 하나가 시군 여럿을 돈다)."""
    import time as _t
    key = (base, path, tuple(sorted(params.items())))
    hit = _GET.get(key)
    if hit and _t.time() - hit[0] < 30:
        return hit[1]
    r = _client().get(f"{base}{path}", params=params)
    r.raise_for_status()
    j = r.json()
    if len(_GET) > 64:
        _GET.clear()
    _GET[key] = (_t.time(), j)
    return j


def _stage(groups: list[dict]) -> dict | None:
    """[[위기경보와 비상단계]] 호우 — 주의보 A개↑ 또는 경보 W개 미만 비상1 · 경보 W개↑ 비상2 · 그 밖의 주의보 초기대응(A · W 는 [[판정값]])."""
    land = [g for g in groups if not g.get("sea")]
    n_w = sum(len(g["siguns"]) for g in land if g["name"] == "호우경보")
    n_a = sum(len(g["siguns"]) for g in land if g["name"] == "호우주의보")
    a, w = R("비상1단계_호우주의보_시군"), R("비상2단계_호우경보_시군")
    if n_w >= w:
        return {"stage": "비상 2단계", "why": f"호우경보 {n_w}개 시군({w}개 이상)"}
    if n_a >= a or n_w >= 1:
        return {"stage": "비상 1단계", "why": f"호우주의보 {n_a}개 · 경보 {n_w}개 시군"}
    if n_a >= 1:
        return {"stage": "초기대응", "why": f"호우주의보 {n_a}개 시군({a - 1}개 이하)"}
    return None


# 도 단계 — 특보 기준에 닿으면 그 단계가 된 것으로 본다. 실제와 다르면 사람이 바꾼다(시군과 같은 저장소, 열쇠 '도').
DO_ORDER = ["상시대비", "초기대응", "비상 1단계", "비상 2단계", "비상 3단계"]


def do_stage(groups: list[dict], over: dict | None = None) -> dict | None:
    """지금 도 단계 — stage = 지금(바꾼 값이 있으면 그것), auto = 특보 기준. 특보도 바꾼 값도 없으면 None."""
    a = _stage(groups)
    v = (overrides() if over is None else over).get("도")
    ok = bool(v) and v.get("stage") in DO_ORDER
    if not a and not ok:
        return None
    auto = a["stage"] if a else DO_ORDER[0]
    return {"stage": v["stage"] if ok else auto, "why": a["why"] if a else "호우특보 없음", "auto": auto, "set": ok,
            "set_at": v.get("at") if ok else None, "order": DO_ORDER}


def do_text(d: dict) -> str:
    """'도 비상단계: 비상 1단계 (호우주의보 4개 · 경보 2개 시군)'. 사람이 바꿨으면 특보 기준을 옆에 남긴다."""
    return f"도 비상단계: {d['stage']} " + (f"(수동 입력 · 특보 기준 {d['auto']}: {d['why']})" if d["set"] else f"({d['why']})")


# 시군 자체 비상단계 — 위키 [[거제시 단계별 업무]] · [[통영시 단계별 업무]](시군 현장조치 행동매뉴얼 2026.10.)의 진입 기준 · 근무 · 대응.
# 도(_stage)는 '특보가 난 시군 수'지만 시군은 '그 시에 발효된 특보 종류'로 정한다 — 두 기준은 별개로 돈다.
# 이름은 매뉴얼 그대로(order). 매뉴얼이 위키에 있는 시군만 — 없는 시군은 None(만들어 내지 않는다).
# 규칙은 센 단계부터 (단계, 육상 특보 이름, 예비특보 종류). 이 계산은 특보로 정해지는 부분(기준)일 뿐이다 —
# 실제 발령은 상황판단회의 · 본부장 판단이라, 사람이 바꾼 값(over)이 있으면 그것이 지금 단계이고 기준은 옆에 남긴다.
# 풍랑 · 앞바다 특보는 시군에 붙지 않아 판단하지 않는다. '광역적 재난' · '본부장 판단'도 계산하지 않는다.
OVER_TTL_H = 24          # 사람이 바꾼 값은 이만큼 뒤 저절로 풀린다(지난 호우의 단계가 화면에 남는 것을 막는다)
SIGUN_STAGE = {
    "거제": {"src": "거제시 단계별 업무 p.28", "draft": False, "base": "평시",
             "order": ["평시", "준비(관심)", "비상 1단계", "비상 2단계", "비상 3단계"],
             "do": {"평시": "주간 재난대응과 풍수해재난팀 상시 대기, 야간 상황관리팀 1명",
                    "준비(관심)": "상황관리팀 1명 + 풍수해재난팀 2명(관내 비상대기)",
                    "비상 1단계": "재대본 운영 — 풍수해재난팀 3명 · 상황관리팀 1명 · 실무반 18명, 면·동 근무 1~2명",
                    "비상 2단계": "풍수해재난팀 6명 · 상황관리팀 2명 · 실무반 23명, 전 직원 1/4 근무",
                    "비상 3단계": "비상 2단계와 같은 편성, 전 직원 1/2 근무"},
             "rules": [("비상 3단계", {"태풍경보"}, set()),
                       ("비상 2단계", {"호우경보", "태풍주의보"}, set()),
                       ("비상 1단계", {"호우주의보"}, {"태풍"}),
                       ("준비(관심)", {"강풍주의보"}, {"호우"})]},
    "통영": {"src": "통영시 단계별 업무 p.30", "draft": True, "base": "평시",
             "order": ["평시", "비상 1단계", "비상 2·3단계"],
             "do": {"평시": "기상 모니터링, (필요시) 상황판단회의(매뉴얼 '평시 및 초기대응')",
                    "비상 1단계": "상황판단회의, 지대본 비상근무, 현장 안전관리, (필요시) 위험지역 통제·대피",
                    "비상 2·3단계": "지대본 비상근무 격상, 현장 안전관리 지속, 위험지역 통제·대피, 피해 수습·이재민 지원, 응급복구"},
             "rules": [("비상 2·3단계", {"호우경보", "대설경보", "태풍주의보", "태풍경보"}, set()),
                       ("비상 1단계", {"호우주의보", "대설주의보"}, {"태풍"})]},
}


# 시군 매뉴얼이 위키에 아직 없는 시군 — 거제시 매뉴얼의 5단계(평시 · 준비(관심) · 비상 1~3단계)와 특보 기준을 준용한다. 근무 편성 같은 시군 고유 숫자는 쓰지 않는다.
# 이 시군 자신의 매뉴얼이 위키에 들어오면 SIGUN_STAGE 에 한 줄을 더해 바꾼다.
_STD = {"src": "거제시 매뉴얼 준용(이 시군 매뉴얼은 위키에 아직 없다)", "draft": True, "std": True, "base": SIGUN_STAGE["거제"]["base"],
        "order": SIGUN_STAGE["거제"]["order"], "rules": SIGUN_STAGE["거제"]["rules"],
        "do": {s: "이 시군 매뉴얼의 해당 단계 업무에 따른다(위키에 아직 없음)" for s in SIGUN_STAGE["거제"]["order"]}}


def _manual(sigun: str) -> dict | None:
    """그 시군의 단계 표 — 자기 매뉴얼이 위키에 있으면 그것, 경남 시군이면 거제 기준 준용, 아니면 None."""
    return SIGUN_STAGE.get(sigun) or (_STD if sigun in SIGUN_FULL else None)


def sigun_stage(sigun: str, alerts: list[str], pending: list[str], over: dict | None = None) -> dict | None:
    """시군 하나의 비상단계 — alerts 는 그 시에 발효된 육상 특보 이름, pending 은 예비특보 종류(호우 · 태풍 …),
    over 는 사람이 바꾼 값 {stage, at}. stage = 지금 단계(바꾼 값이 있으면 그것), auto = 특보 기준."""
    m = _manual(sigun)
    if not m:
        return None
    a, p = set(alerts), set(pending)
    auto, why = m["base"], "해당 특보 없음"
    for stage, wa, wp in m["rules"]:
        hit = sorted(a & wa) + [f"{x} 예비특보" for x in sorted(p & wp)]
        if hit:
            auto, why = stage, " · ".join(hit)
            break
    ok = bool(over) and over.get("stage") in m["order"]
    now = over["stage"] if ok else auto
    return {"stage": now, "auto": auto, "why": why, "set": ok, "set_at": over.get("at") if ok else None,
            "do": m["do"].get(now, ""), "order": m["order"], "src": m["src"], "draft": m["draft"], "std": bool(m.get("std"))}


def stage_text(sigun: str, d: dict) -> str:
    """'거제시 매뉴얼 기준 비상 1단계 (호우주의보) — 도 단계와 별개'. 사람이 바꿨으면 특보 기준을 옆에 남긴다."""
    full = SIGUN_FULL.get(sigun, sigun)
    who = f"{full} 기준(거제시 매뉴얼 준용)" if d.get("std") else f"{full} 매뉴얼 기준"
    head = (f"{full} {d['stage']} (수동 입력 · 특보 기준 {d['auto']}: {d['why']})" if d["set"]
            else f"{who} {d['stage']} ({d['why']})")
    return head + " — 도 단계와 별개" + (" · 이 시군 매뉴얼은 위키에 아직 없다" if d.get("std") else " · 매뉴얼 확정본 확인 전(참고본)" if d["draft"] else "")


def overrides() -> dict:
    """사람이 바꾼 시군 단계 {시군: {stage, at}} — 24시간 지난 것은 뺀다. DB 가 없으면 빈 값(특보 기준만)."""
    try:
        from . import db
        raw = db.get_setting("sigun_stage_over", {}) or {}
    except Exception:                                      # noqa: BLE001
        return {}
    cut = (datetime.now() - timedelta(hours=OVER_TTL_H)).strftime("%Y%m%d%H%M")
    return {k: v for k, v in raw.items() if (k in SIGUN_FULL or k == "도") and isinstance(v, dict) and (v.get("at") or "") >= cut}


def set_override(sigun: str, stage: str | None) -> dict:
    """사람이 도 · 시군 단계를 바꾼다(sigun='도' 면 도, stage=None 이면 특보 기준으로 되돌림). 매뉴얼의 단계 이름만 받는다."""
    m = {"order": DO_ORDER} if sigun == "도" else _manual(sigun)
    if not m:
        raise ValueError(f"{sigun}: 경남 시군이 아니다")
    if stage is not None and stage not in m["order"]:
        raise ValueError(f"{stage}: {sigun} 매뉴얼에 없는 단계 — {', '.join(m['order'])}")
    from . import db
    cur = overrides()
    if stage is None:
        cur.pop(sigun, None)
    else:
        cur[sigun] = {"stage": stage, "at": datetime.now().strftime("%Y%m%d%H%M")}
    db.put_setting("sigun_stage_over", cur)
    return cur


def sigun_stages(data: dict, over: dict | None = None) -> dict:
    """특보 스냅숏(data: groups · pending) → 도 비상단계 + 시군별 비상단계(매뉴얼이 없는 시군은 거제 기준 준용, 사람이 바꾼 값 포함)."""
    groups, pend = data.get("groups", []), data.get("pending", [])
    over = over or {}
    out = {}
    for sg in SIGUN_FULL:
        al = [g["name"] for g in groups if sg in g.get("siguns", []) and not g.get("sea")]
        out[sg] = sigun_stage(sg, al, [x["name"] for x in pend if x.get("sigun") == sg], over.get(sg))
    return {"do": do_stage(groups, over), "do_order": DO_ORDER, "sigun": out}


# 할 일 체크 — 사람이 한 일을 표시하면 보고의 '조치 완료'에 남는다. 단계 값처럼 24시간 뒤 저절로 풀린다.
def task_key(text: str) -> str:
    # shortcut: 문장 전체가 열쇠라 수치가 바뀐 할 일은 새 일로 본다, 할 일에 번호를 매기게 되면 그때 바꾼다
    return hashlib.sha1(re.sub(r"\[\[|\]\]", "", text).encode("utf-8")).hexdigest()[:12]


def tasks_done() -> dict:
    """{열쇠: {text, at}} — 24시간 지난 것은 뺀다. DB 가 없으면 빈 값."""
    try:
        from . import db
        raw = db.get_setting("task_done", {}) or {}
    except Exception:                                      # noqa: BLE001
        return {}
    cut = (datetime.now() - timedelta(hours=OVER_TTL_H)).strftime("%Y%m%d%H%M")
    return {k: v for k, v in raw.items() if isinstance(v, dict) and (v.get("at") or "") >= cut}


def set_tasks(tasks: list[dict]) -> None:
    """적용 단추 — [{text, done}] 를 한 번에 남긴다."""
    from . import db
    cur = tasks_done()
    at = datetime.now().strftime("%Y%m%d%H%M")
    for t in tasks:
        if t["done"]:
            cur[task_key(t["text"])] = {"text": t["text"], "at": at}
        else:
            cur.pop(task_key(t["text"]), None)
    db.put_setting("task_done", cur)


# 한 일 → 이어서 볼 일. 새 기준은 없다 — 위키 절차의 다음 칸(회신 · 현황 파악)만 잇는다. 뒤 글은 앞 열쇠말을 품지 않아야 한다(끝없이 이어지지 않게).
FOLLOW = [("재난상황실에 유선 전파", "전파 회신 확인 — {w}: 시군의 통제 · 사전대피 판단 결과를 받아 기록 ([[시군 상황관리반 행동매뉴얼]])"),
          ("긴급대피 실황 기준 해당", "대피 현황 확인 — {w}: 세대 · 인원, 미대피자 파악 ([[대피명령 길라잡이]])"),
          ("사전대피 기준 해당", "권고 결과 확인 — {w}: 대피 세대 · 인원 파악 ([[대피명령 길라잡이]])"),
          ("통제 기준 해당", "통제 유지 확인 — {w}: 통제 지점 · 담당 인력이 그대로인지 ([[통제·대피 기준]])"),
          ("긴급재난문자 기준", "문자 결과 확인 — {w}: 송출 여부 · 문안 기록 ([[재난문자 송출기준]])"),
          ("홍수특보 발령", "특보 변경 확인 — {w}: 변경 발령 · 해제 여부, 하천변 통제 유지 ([[하천 홍수예보와 홍수특보]])"),
          ("댐 방류 증가", "방류 변경 확인 — {w}: 방류량 변경 · 하류 예찰 결과 기록 ([[행동요령 카드 목록]])")]
CHECK_SECS = ("할 일", "별도 확인 필요")


def follow_ups(done: list[str]) -> list[str]:
    out = []
    for text in done:
        for key, tpl in FOLLOW:
            if key in text and (m := re.search(r"— ([^:]+):", text)):
                out.append(tpl.format(w=m[1]))
    return out


def apply_tasks(rep: dict, sigun: str | None = None, done: dict | None = None) -> dict:
    """적용한 일을 보고에 반영한다 — 할 일 · 별도 확인 칸에서 빼고 이어서 볼 일을 더하고, '조치 완료' 칸에 남긴다.
    칸에는 체크용 keys(원문)를 붙인다. 시군 보고의 조치 완료는 그 시군 · 이 보고에 있던 일만."""
    done = tasks_done() if done is None else done
    secs = rep.get("sections") or []
    chk = [s for s in secs if s["h"] in CHECK_SECS]
    mine = {task_key(i) for s in chk for i in s["items"]}
    got = sorted((v for k, v in done.items() if k in mine or not sigun or sigun in v["text"]), key=lambda v: v["at"])
    for s in chk:
        s["items"] = [i for i in s["items"] if task_key(i) not in done]
        if s["h"] == "할 일":
            s["items"] += [i for i in dict.fromkeys(follow_ups([v["text"] for v in got])) if task_key(i) not in done and i not in s["items"]]
            s["items"] = s["items"] or ["남은 할 일 없음 — 정시마다 실황 · 예측 확인 유지"]
        s["texts"] = list(s["items"])
    if got:
        i = secs.index(chk[-1]) + 1 if chk else next((n for n, s in enumerate(secs) if s["h"].startswith("참고")), len(secs))
        secs.insert(i, {"h": "조치 완료", "items": [f"{v['at'][8:10]}:{v['at'][10:12]} {v['text']}" for v in got],
                        "texts": [v["text"] for v in got], "on": True})
    return rep


# ── 전망 — 특보 · 단기예보 · 초단기를 묶어 '비가 올 우려'를 본다. 사람(예보관)이 낸 특보는 무겁게, 새 발표일수록 무겁게.
# ⚠️ 위키 기준 대조(ladders) · 비상단계에는 끼어들지 않는다 — 전망 문구 · 보고 펼침에만 쓴다. 기준이 가중치로 흔들리면 안 된다.
AL_SEV = {"호우경보": 1.0, "태풍경보": 1.0, "호우주의보": .7, "태풍주의보": .7}
AL_3H = {"호우주의보": 60, "호우경보": 90}                  # 기상특보 발표기준 3시간 값
HALF_H, W_FLOOR = 3.0, 0.5                                 # 3시간마다 절반. 발효 중인 특보는 절반 아래로 내리지 않는다
LV_HIGH, LV_WARN = .7, .3


def _fc_dt(t, now: datetime) -> datetime | None:
    """발표 시각 — YYYYMMDDHHMM · YYYYMMDDHH · 옛 스냅숏의 HH:MM."""
    t = str(t or "")
    try:
        if ":" in t:
            d = now.replace(hour=int(t[:2]), minute=int(t[3:5]), second=0, microsecond=0)
            return d - timedelta(days=1) if d > now else d
        return datetime.strptime(t[:12].ljust(12, "0"), "%Y%m%d%H%M") if t else None
    except ValueError:
        return None


def weight(age_h: float | None, backed: bool) -> float:
    """새 발표일수록 무겁다. 지금 실황 · 초단기가 같은 말을 하면(backed) 시간이 지나도 깎지 않는다. 시각을 모르면 깎지 않는다."""
    if backed or age_h is None:
        return 1.0
    return max(W_FLOOR, round(.5 ** (max(age_h, 0) / HALF_H), 2))


def outlook(alerts: list[dict], pending: list[dict], short: dict, r3, fc_sum, fc_peak, now: datetime) -> dict:
    """alerts [{name, at}] · pending(예비특보) · short {today: {max, tmfc}, tomorrow: …} · 실황 3시간 · 초단기 6시간 합 · 최대 시우량."""
    seen = (r3 or 0) + (fc_sum or 0)                       # shortcut: 지난 3시간 + 앞 6시간을 특보 3시간 값과 견준다(느슨한 쪽), 시간별로 보려면 fc_hours 로
    parts = []

    def add(src, name, at, sev, backed):
        d = _fc_dt(at, now)
        age = round((now - d).total_seconds() / 3600, 1) if d else None
        parts.append({"src": src, "name": name, "at": d.strftime("%H:%M") if d else None, "age_h": age,
                      "sev": sev, "backed": backed, "w": weight(age, backed)})

    for a in alerts:
        if a["name"] in AL_SEV:
            need = AL_3H.get(a["name"])                     # 태풍은 3시간 값이 없어 깎지 않는다
            add("특보", a["name"], a.get("at"), AL_SEV[a["name"]], need is None or seen >= .7 * need)
    for p in pending:
        if p.get("name") in ("호우", "태풍"):
            add("예비특보", f"{p['name']} 예비특보", p.get("tmfc"), .5, seen >= 42)
    for key, lab in (("today", "오늘"), ("tomorrow", "내일")):
        v = (short.get(key) or {}).get("max")
        if v is not None and v >= 30:
            add("단기예보", f"{lab} 최대 {v:g}㎜", short[key].get("tmfc"), .8 if v >= 100 else .6 if v >= 60 else .4,
                key == "today" and seen >= .5 * v)
    if (fc_sum or 0) >= 30 or (fc_peak or 0) >= 20:
        big = (fc_sum or 0) >= 60 or (fc_peak or 0) >= 30
        parts.append({"src": "초단기", "name": f"앞으로 6시간 {fc_sum or 0:g}㎜", "at": None, "age_h": None,
                      "sev": .8 if big else .5, "backed": True, "w": 1.0})
    parts.sort(key=lambda x: -x["w"] * x["sev"])
    score = round(parts[0]["w"] * parts[0]["sev"], 2) if parts else 0
    return {"level": "높음" if score >= LV_HIGH else "주의" if score >= LV_WARN else "낮음", "score": score, "parts": parts}


def outlook_text(o: dict) -> str:
    def one(x):
        if x["at"] is None:
            return x["name"]
        how = ("실황 · 초단기가 뒷받침" if x["backed"] else f"{x['age_h']:g}시간 전, 가중 {x['w']:g}" if x["name"].startswith("내일")   # 내일 비는 지금 비로 맞춰 볼 수 없다
               else f"{x['age_h']:g}시간 전 · 실황 · 초단기가 아직 못 따라옴, 가중 {x['w']:g}")
        return f"{x['name']} {x['at']} 발표({how})"
    return f"전망 {o['level']}" + (" — " + " · ".join(one(x) for x in o["parts"][:3]) if o["parts"] else " — 특보 · 단기예보 · 초단기 모두 큰 비 없음")


def alert_times(groups: list[dict], sigun: str) -> list[dict]:
    return [{"name": g["name"], "at": (g.get("at") or {}).get(sigun) or g.get("tmfc")}
            for g in groups if sigun in g.get("siguns", []) and not g.get("sea")]


def short_of(base: str) -> dict:
    """시군별 단기예보 — {시군: {today: {max, tmfc}, tomorrow: …}}. 격자가 없으면 빈 것."""
    out: dict[str, dict] = {}
    for key in ("today", "tomorrow"):
        try:
            j = _get(base, "/api/grid/sigun", layer=f"shrt_{key}")
        except Exception:                                  # noqa: BLE001 — 단기예보가 없어도 상황판단은 돈다
            continue
        for r in j.get("rows", []):
            if r.get("kind") == "gn" and r.get("max") is not None:
                out.setdefault(r["sigun"], {})[key] = {"max": r["max"], "tmfc": j.get("tmfc")}
    return out


def situation(sigun: str, base: str = "http://127.0.0.1:8000", k: float = 1.0, basis: str = "grid",
              add_h: float = 0.0, add_24: float = 0.0) -> dict:
    """시군 하나 — 읍면동별 지금 수치 · 우려지역(유형별) · 3대 유형 단계 대조 · 지구 대피기준까지 % ·
    상황전파 기준 · 특보 · 비상단계 · 재난문자 기준. 판정하지 않는다(st 는 '그 조건에 닿았나'일 뿐).
    k = 상황판단 모드의 '만약에' — 예보 시우량(초단기 · 단기)에 곱한다. add_h = 앞으로 24시간 매시간 더하는 ㎜,
    add_24 = 앞으로 24시간에 고루 나눠 더하는 총 ㎜(곱한 뒤 더한다)."""
    base = base.rstrip("/")
    w = _get(base, "/api/ai/emdwin", basis=basis)          # 읍면동 × 1·3·12·24·48시간 · 15분 — 한 번에(basis=aws 면 AWS 면)
    mine_rows = [r for r in w["rows"] if r["sig"] == sigun]
    acc = {h: {r["emd"]: r.get(f"{h}h") for r in mine_rows} for h in WINDOWS}
    m15 = {r["emd"]: r.get("15m") for r in mine_rows}
    tm, src = w.get("tm"), "기상청 고해상도 격자(500m) · 매시 60분 합 + 지금 칸(일강수 증분)"
    try:
        an = _get(base, "/api/ai/ante")                    # 직전 5일 — 5일치 격자가 없으면 ok=False
    except Exception:                                      # noqa: BLE001
        an = {"ok": False, "have": 0, "want": 120, "missing": 120}
    ante = {r["emd"]: r["mm"] for r in an.get("rows", []) if r["sig"] == sigun} if an.get("ok") else {}
    fc = _get(base, "/api/forecast", hours=6, sigun=sigun)
    fce = {e["emd"]: e for e in fc.get("emd_sigun", []) if e.get("sigun") == sigun}
    al = (_get(base, "/api/alerts").get("data") or {})
    groups = al.get("groups", [])
    mine = [g["name"] for g in groups if sigun in g.get("siguns", [])]
    pend = [p for p in al.get("pending", []) if p.get("sigun") == sigun]
    now = datetime.strptime(tm, "%Y%m%d%H%M") if tm else datetime.now()
    night = now.hour >= 21 or now.hour < 6

    rv, fld = river_of(sigun), flood_of(sigun)
    sites = _lookup()(wiki(), SIGUN_FULL.get(sigun, sigun), kind="all")
    by_emd: dict[str, list] = defaultdict(list)
    for s in sites["sites"]:
        by_emd[s["읍면동"]].append(s)

    emds = []
    labels = fc.get("labels") or []
    try:                                                   # 초단기 6시간 뒤는 단기예보로 이어 내일 24시까지(도달 시각 · 오늘/내일 누적)
        h0 = datetime.strptime((tm or "")[:10], "%Y%m%d%H") + timedelta(hours=len(labels))
        sh = _get(base, "/api/ai/shrt_emd", sigun=sigun, start=h0.strftime("%Y%m%d%H"))
    except Exception:                                      # noqa: BLE001 — 단기예보가 없어도 돈다
        sh = {"labels": [], "emd": {}, "tmefs": []}
    for name in acc[3]:
        f = fce.get(name) or {}
        d = [round(v * k, 1) for v in f.get("d") or []]
        sd = [round(v * k, 1) for v in sh["emd"].get(name) or []]
        if (add_h or add_24) and d:                          # 만약에 — 앞으로 24시간(있는 만큼) 매시간 더하기
            al = d + sd
            n = min(24, len(al))
            al = [round(v + (add_h + add_24 / n if i < n else 0), 1) for i, v in enumerate(al)]
            d, sd = al[:len(d)], al[len(d):]
        run, best = 0, 0
        for v in d:
            run = run + 1 if v >= R("하천_통제_시우량") else 0
            best = max(best, run)
        row = {"emd": name, "rain": {f"{h}h": acc[h].get(name) for h in WINDOWS}, "m15": m15.get(name),
               "fc6h": round(sum(d), 1) if d else f.get("sum"), "fc_peak": max(d) if d else f.get("peak"), "fc_hours": d, "fc_labels": labels,
               "fc_run30": best if d else None,
               "ante": ante.get(name)}
        if d and sd:
            row["eta_hours"], row["eta_labels"] = d + sd, labels + sh["labels"]
            row["later"] = {"today": round(sum(v for v, l in zip(sd, sh["labels"]) if " " not in l), 1),
                            "tomorrow": round(sum(v for v, l in zip(sd, sh["labels"]) if l.startswith("내일")), 1)}
        r1, r3, r24 = row["rain"]["1h"] or 0, row["rain"]["3h"] or 0, row["rain"]["24h"] or 0
        row["cbs"] = is_cbs(r1, r3)
        row["relay"] = is_relay(r1, r24)
        fam = Counter(FAMILY_OF.get(s["유형"], "야외·기타") for s in by_emd.get(name, []))
        row["risk"] = dict(fam)
        lad = ladders(row, night, mine, rv, fld)
        row["ladders"] = {k: v for k, v in lad.items() if fam.get(k)}       # 그 유형 우려지역이 있을 때만
        row["sites"] = []
        for rule, n in Counter(s["대피기준"] for s in by_emd.get(name, []) if FAMILY_OF.get(s["유형"]) == "산사태").most_common():
            prog = [{**c, "now": acc[c["win"]].get(name),
                     "pct": None if acc[c["win"]].get(name) is None else round(acc[c["win"]][name] / c["mm"] * 100)}
                    for c in conditions(rule)]
            row["sites"].append({"rule": rule, "n": n, "conds": prog, "max_pct": max((p["pct"] or 0 for p in prog), default=None),
                                 "check": [x for x in ("토양함수", "예보", "선행") if x in (rule or "")]})
        row["max_pct"] = max((s["max_pct"] or 0 for s in row["sites"]), default=None)
        order = {"met": 3, "near": 2, "unknown": 0, "no": 0}       # 모름은 순위를 올리지 않는다
        row["hot"] = max((order[c["st"]] for v in row["ladders"].values() for c in v), default=0)
        emds.append(row)
    emds.sort(key=lambda r: (-r["hot"], -(r["max_pct"] or -1), -(r["rain"]["3h"] or 0)))
    ol = outlook(alert_times(groups, sigun), pend, short_of(base).get(sigun, {}),
                 max((r["rain"]["3h"] or 0 for r in emds), default=0), max((r["fc6h"] or 0 for r in emds), default=0),
                 max((r["fc_peak"] or 0 for r in emds), default=0), now)
    return {
        "sigun": sigun, "tm": tm, "night": night, "rain_src": src, "basis": basis, "fc_tmfc": fc.get("tmfc"), "k": k, "shrt_tmfc": sh.get("tmfc"),
        "ante": {k: an.get(k) for k in ("ok", "have", "want", "missing", "from", "to")},
        "alerts": mine, "pending": pend, "stage": do_stage(groups), "river": rv, "flood": fld, "outlook": ol,
        "tide": tide.text(tide.of_sigun(sigun), max((r["fc6h"] or 0 for r in emds), default=0)),
        "risk_total": dict(Counter(FAMILY_OF.get(s["유형"], "야외·기타") for s in sites["sites"])),
        "emd": emds,
        "rules": {"cbs": cbs_rule() + "(기상청 긴급재난문자)",
                  "relay": f"시간당 {R('상황전파_1시간')}㎜ 이상 또는 일강우 {R('상황전파_일')}㎜ 이상 → 시군 재난상황실 유선 전파, 우려지역 통제·사전대피 여부 판단",
                  "principle": "사전대피는 예보, 긴급대피는 실황 · 일몰 전 사전대피 · 그 유형 우려지역에만 적용"},
        "limits": ["지구 좌표가 없어 읍면동 안 가장 많이 온 격자(500m)로 견준다 — 지구 강우의 상한",
                   f"초단기 예보 시우량은 {RN1_CAP:g}㎜ 에서 막혀 온다 — 50·55㎜/h 예보 조건은 '모름'",
                   "선행 5일 강우 · 토양함수 · 침수심 · 제방 만수위 · 교량 수위 · 댐 방류 예보 · 예측정보(산림청 산사태 예보)는 여기 없다 — 따로 확인(하천 수위는 홍수통제소 원시값을 연결했다)",
                   "기준 N% · 남은 ㎜ · 닿는 시각은 가장 먼 조건 기준이다 — 닿는 시각은 예보 시우량을 지금 누적에 더한 것이라 창에서 빠지는 옛 비는 빼지 않아 실제보다 이를 수 있다",
                   "조위 단계는 해양조사원 고조정보다 — 폭풍해일 특보와 다른 체계이고, 호우와 만조의 겹침은 나란히 보일 뿐 판정하지 않는다(위키에 기준이 없다)",
                   "전망(높음 · 주의 · 낮음)은 특보 · 단기예보 · 초단기를 묶은 참고다 — 새 발표일수록 무겁고, 지금 비가 같은 말을 하면 시간이 지나도 깎지 않는다. 위키 기준 대조 · 비상단계는 바꾸지 않는다",
                   "목록에 없다고 위험이 없는 것이 아니다", "대피명령은 시장·군수·구청장 권한(재난안전법 제40조)",
                   sites["source_basis"]],
        "wiki": [f"[[{SIGUN_FULL.get(sigun, sigun)}]] (산사태 위험지역)", "[[통제·대피 기준]]", "[[시군 상황관리반 행동매뉴얼]]",
                 "[[대피명령 길라잡이]]", "[[위기경보와 비상단계]]", "[[재난문자 송출기준]]", "[[재난문자 표준문안]]"]
                + (["[[고조정보 4단계와 대조기 해안침수]]"] if tide.of_sigun(sigun) else []),
    }


STL = {"met": "충족", "near": "근접(70%↑)", "unknown": "모름", "no": "아님"}
RV_NAME = ["정상", "관심", "주의보", "경보", "심각"]


def river_text(rv: dict | None, fld: list[dict] | None = None) -> str:
    """하천 · 댐 한 줄(홍수통제소 원시값). 자료가 없으면 그렇게 적는다 — 없는 것을 정상으로 치지 않는다."""
    from . import river
    tail = " · 홍수예보 발령: " + ", ".join(river.fld_text(s) for s in fld) if fld else ""
    if not rv:
        return "하천 수위(홍수통제소): 이 시군은 기준 수위가 있는 관측소 자료가 없다 — 따로 확인" + tail
    s = f"하천 수위(홍수통제소 원시값): {rv['name']} {rv['wl']:.2f}m {RV_NAME[rv['stage']]}"
    if rv.get("gap") is not None and rv["stage"] < 4:
        s += f" · {RV_NAME[rv['stage'] + 1]} 수위까지 {rv['gap']}m"
    if rv.get("d1h"):
        s += f" · 1시간 {'+' if rv['d1h'] > 0 else ''}{rv['d1h']}m"
    s += f" (기준 수위 있는 {rv['n']}곳 중 기준에 가장 가까운 곳)"
    dm = [d for d in rv.get("dams") or [] if (d["out"] or 0) >= 1 or d["rise"]]
    if dm:
        s += " · 댐·보 방류: " + ", ".join(f"{d['name']} {round(d['out'], 1):g}㎥/s{'▲' if d['rise'] else ''}{'(위쪽)' if d['up'] else ''}" for d in dm[:4])
    return s + tail


def _na(v):
    return "자료 없음" if v is None else v


def brief(s: dict, top: int = 4) -> str:
    """LLM 맥락 · 사람이 읽는 짧은 글 — 닿았거나 가까운 것만 적는다."""
    t = s.get("tm") or ""
    out = [f"■ {s['sigun']} — {t[4:6]}.{t[6:8]}. {t[8:10]}:{t[10:12]} 실황 기준{' · 취약시간대(21~06시)' if s['night'] else ''}"]
    out.append("특보: " + (", ".join(s["alerts"]) or "없음") + (f" · 예비 {', '.join(p['name'] for p in s['pending'])}" if s["pending"] else ""))
    if s.get("outlook"):
        out.append(outlook_text(s["outlook"]))
    if s.get("tide"):
        out.append(s["tide"])
    if s["stage"]:
        out.append(do_text(s["stage"]))
    out.append("우려지역(위키): " + " · ".join(f"{k} {v}" for k, v in sorted(s["risk_total"].items(), key=lambda x: -x[1])))
    relay = [r["emd"] for r in s["emd"] if r["relay"]]
    out.append(f"상황전파 기준({relay_rule()}): " +(", ".join(relay) if relay else "없음"))
    cbs = [r["emd"] for r in s["emd"] if r["cbs"]]
    out.append("재난문자 기준(실황): " + (", ".join(cbs) if cbs else "없음"))
    out.append(river_text(s.get("river"), s.get("flood")))
    for r in s["emd"][:top]:
        rn = r["rain"]
        hit = [f"{fam} {c['stage']} '{c['rule']}' {STL[c['st']]}" + (f" ({gap_text(c)})" if gap_text(c) else "")
               for fam, cs in r["ladders"].items() for c in cs if c["st"] in ("met", "near")]
        an_ = f" · 선행 5일 {r['ante']:g}" if r.get("ante") is not None else ""
        fc = f"앞으로 6h {r['fc6h']}(최대 {r['fc_peak']}/h)" if r["fc6h"] is not None else "앞으로 6h 예측 자료 없음"
        out.append(f"· {r['emd']} — 1h {rn['1h']} · 3h {rn['3h']} · 24h {rn['24h']} · 15분 {_na(r['m15'])}{an_} · {fc}"
                   f" · 우려지역 {', '.join(f'{k} {v}' for k, v in r['risk'].items()) or '없음'}")
        if hit:
            out.append("   닿음/근접: " + "; ".join(hit))
        if r["sites"]:
            b = max(r["sites"], key=lambda x: x["max_pct"] or 0)
            out.append("   산사태 지구 대피기준(원문 '" + b["rule"] + "'): "
                       + " · ".join(f"{p['label']} {p['now']}/{p['mm']:g}㎜ {p['pct']}%" for p in b["conds"]))
    return "\n".join(out)


if __name__ == "__main__":
    sg = sys.argv[1] if len(sys.argv) > 1 else "함양"
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"
    s = situation(sg, base)
    print(brief(s))
    if "--json" in sys.argv:
        print(json.dumps(s, ensure_ascii=False, indent=1)[:4000])


def set_wiki(path: str) -> dict:
    """위키 폴더를 바꾼다(빈 값 = 설정 지움). 쓸 수 없는 폴더면 바꾸지 않고 이유를 돌려준다. 바꾸면 위키에서 읽은 캐시를 다 비운다."""
    from . import db
    path = (path or "").strip().strip('"')
    if path:
        chk = wiki_check(Path(path))
        if not chk["ok"]:
            return {**chk, "saved": False}
    db.put_setting("ai_wiki", path)
    reset_wiki_cache()
    return {**wiki_check(wiki()), "saved": True}


def reset_wiki_cache() -> None:
    _WS[1] = None
    _RULES.pop("out", None)
    _lookup_load.cache_clear()
    _LK.clear()
    _GET.clear()
    _RULES.clear()
    from . import aireport
    aireport.reset_cache()


def ladder_list() -> list[dict]:
    """도움말 표 — 유형 · 단계 · 조건(ladders 의 규칙 글) · 쓰는 자료. 빈 줄 하나를 대조해 규칙 글만 꺼낸다(값은 안 본다)."""
    row = {"rain": {"1h": 0, "3h": 0, "12h": 0, "24h": 0, "48h": 0}, "m15": 0, "fc_peak": 0, "fc_run30": 0, "ante": 0,
           "fc_hours": [0] * 6, "fc_labels": [str(i) for i in range(6)]}

    def src(rule: str) -> str:
        if "홍수통제소" in rule:
            return "하천 수위 · 홍수예보(홍수통제소)"
        if "산림청" in rule:
            return "산림청 산사태 예보 — 대시보드에 없음(모름)"
        if "발령" in rule:
            return "기상특보"
        if "예보" in rule:
            return "초단기 · 단기예보"
        return "실황(AWS · 격자)"
    out = []
    for fam, cs in ladders(row, False, []).items():
        for c in cs:
            out.append({"fam": fam, "stage": c["stage"], "rule": c["rule"], "src": src(c["rule"])})
    order = {"통제": 0, "사전대피": 1, "긴급대피": 2}
    return sorted(out, key=lambda r: (list(FAMILY).index(r["fam"]) if r["fam"] in FAMILY else 9, order.get(r["stage"], 9)))


def regions() -> dict:
    """단계 영역 평면 — 유형마다 가로(누적 ㎜ 또는 15분 ㎜) × 세로(시우량 ㎜/h) 위의 통제 · 사전대피 · 긴급대피 영역(위키 판정값).
    rect = 그 점에서 오른쪽 위(그리고), band = 세로 그 값 위 전부(가로 상관없음), vband = 가로 그 값 오른쪽 전부.
    같은 단계에 영역이 여럿이면 '또는' — 합치면 의자(ㄱ) 모양. 비가 아닌 조건(특보 · 수위 · 산림청)은 texts 로(평면에 못 그린다)."""
    v = rules()["v"]
    L, H, U = ({k.split("_", 1)[1]: x for k, x in v.items() if k.startswith(f"{t}_")} for t in ("산사태", "하천", "지하공간"))
    nonrain = lambda fam: [{"stage": r["stage"], "text": r["rule"]} for r in ladder_list()  # noqa: E731
                           if r["fam"] == fam and not r["src"].startswith(("실황", "초단기"))]
    return {
        "산사태": {"x": "누적", "xu": "㎜", "areas": [
            {"stage": "통제", "kind": "rect", "x": L["통제_누적"], "y": L["통제_예보시우량"], "note": "예보"},
            {"stage": "사전대피", "kind": "rect", "x": L["사전대피_누적"], "y": L["사전대피_예보시우량"], "note": "예보"},
            {"stage": "사전대피", "kind": "rect", "x": L["통제_누적"], "y": L["사전대피_야간예보시우량"], "night": True, "note": "취약시간(21~06시) 예보 · 통제 누적과 함께"},
            {"stage": "긴급대피", "kind": "rect", "x": L["긴급대피_누적"], "y": L["긴급대피_시우량"], "note": f"실황 · 일 {L['긴급대피_일']}㎜ 도 함께"}],
            "texts": nonrain("산사태")},
        "하천": {"x": "누적", "xu": "㎜", "areas": [
            {"stage": "통제", "kind": "band", "y": H["통제_시우량"], "note": f"{H['통제_지속시간']}시간 이상 지속 예보"},
            {"stage": "사전대피", "kind": "rect", "x": H["사전대피_누적"], "y": H["사전대피_예보시우량"], "note": "예보"},
            {"stage": "긴급대피", "kind": "rect", "x": H["긴급대피_누적"], "y": H["긴급대피_시우량"], "note": "실황"}], "texts": nonrain("하천")},
        "지하공간": {"x": "15분", "xu": "㎜", "areas": [
            {"stage": "사전대피", "kind": "rect", "x": U["사전대피_15분"], "y": U["사전대피_예보시우량"], "note": "예보"},
            {"stage": "긴급대피", "kind": "rect", "x": U["긴급대피_15분"], "y": U["긴급대피_시우량"], "note": "실황"}], "texts": nonrain("지하공간")},
    }


def site_area(rule: str) -> list[dict]:
    """지구 원문 대피기준 → 평면의 영역. 쉼표 · 띄어쓰기는 '그리고'(2026-11 결정) → 네모 하나, 원문에 '또는'이 있으면 두 영역(의자 모양).
    1시간 조건은 세로, 나머지(누적 · 일 · 3 · 12시간)는 가로 — 가로 조건이 여럿이면 큰 값(한 축에 둘을 못 그린다)."""
    cs = conditions(rule)
    if not cs:
        return []
    y = max((c["mm"] for c in cs if c["win"] == 1), default=None)
    x = max((c["mm"] for c in cs if c["win"] != 1), default=None)
    base = {"stage": "지구 기준", "note": rule}
    if "또는" in rule and x and y:
        return [{**base, "kind": "vband", "x": x}, {**base, "kind": "band", "y": y}]
    return [{**base, "kind": "rect" if x and y else "vband" if x else "band", "x": x, "y": y}]
