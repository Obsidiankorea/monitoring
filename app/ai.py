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

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import httpx

WIKI = Path(os.environ.get("GN_WIKI") or r"C:\Users\ms\obsidian\재난")
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


def ladders(r: dict, night: bool, alerts: list[str]) -> dict:
    """읍면동 하나 — [[통제·대피 기준]] 3대 유형 단계별 조건 대조(위키 표의 숫자 그대로)."""
    rain, fpk, f3 = r["rain"], r["fc_peak"], r["fc_run30"]
    o1, o24, o48, q15 = rain["1h"], rain["24h"], rain["48h"], r["m15"]
    accum = max(x for x in (o24, o48) if x is not None) if (o24 is not None or o48 is not None) else None
    fcap = fpk is not None and fpk >= RN1_CAP          # 예보가 30 에 막혔으면 그 위는 모른다
    f50 = "unknown" if fpk is None or fcap else _st(fpk, 50)
    f55 = "unknown" if fpk is None or fcap else _st(fpk, 55)
    hoou = [a for a in alerts if a.startswith("호우")]
    out = {
        "산사태": [
            {"stage": "통제", "rule": "일/누적 100㎜↑ + 20㎜/h↑ 예보", "st": _all(_st(accum, 100), _st(fpk, 20))},
            {"stage": "사전대피", "rule": "일/누적 200㎜↑ + 50㎜/h↑ 예보", "st": _all(_st(accum, 200), f50)},
            {"stage": "사전대피", "rule": "취약시간대(21~06시) 30㎜/h↑ 예보",
             "st": ("no" if not night else _st(fpk, 30))},
            {"stage": "긴급대피", "rule": "50㎜/h↑ + 일 170㎜↑(실황)", "st": _all(_st(o1, 50), _st(o24, 170))},
            {"stage": "긴급대피", "rule": "누적 270㎜↑(실황)", "st": _st(o48, 270)},
        ],
        "하천": [
            {"stage": "통제", "rule": "30㎜/h↑ 3시간 이상 지속 예보", "st": _st(f3, 3)},
            {"stage": "사전대피", "rule": "누적 200㎜↑ + 30㎜/h↑ 예보", "st": _all(_st(accum, 200), _st(fpk, 30))},
            {"stage": "긴급대피", "rule": "누적 200㎜↑ + 30㎜/h↑ 실제", "st": _all(_st(accum, 200), _st(o1, 30))},
            {"stage": "긴급대피", "rule": "호우경보 발령", "st": "met" if "호우경보" in hoou else "no"},
        ],
        "지하공간": [
            {"stage": "통제", "rule": "(지하차도) 호우특보 발령", "st": "met" if hoou else "no"},
            {"stage": "사전대피", "rule": "15분 20㎜↑ + 시간당 55㎜↑ 예보", "st": _all(_st(q15, 20), f55)},
            {"stage": "긴급대피", "rule": "15분 30㎜↑ + 시간당 55㎜↑ 실제", "st": _all(_st(q15, 30), _st(o1, 55))},
        ],
    }
    return out


@lru_cache(maxsize=1)
def _lookup_fn():
    sys.path.insert(0, str(WIKI / "tools"))
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
    """[[위기경보와 비상단계]] 호우 — 주의보 3개 이하 초기대응 · 4개↑ 또는 경보 2개 이하 비상1 · 경보 3개↑ 비상2."""
    land = [g for g in groups if not g.get("sea")]
    n_w = sum(len(g["siguns"]) for g in land if g["name"] == "호우경보")
    n_a = sum(len(g["siguns"]) for g in land if g["name"] == "호우주의보")
    if n_w >= 3:
        return {"stage": "비상 2단계", "why": f"호우경보 {n_w}개 시군(3개 이상)"}
    if n_a >= 4 or n_w >= 1:
        return {"stage": "비상 1단계", "why": f"호우주의보 {n_a}개 · 경보 {n_w}개 시군"}
    if n_a >= 1:
        return {"stage": "초기대응", "why": f"호우주의보 {n_a}개 시군(3개 이하)"}
    return None


def situation(sigun: str, base: str = "http://127.0.0.1:8000") -> dict:
    """시군 하나 — 읍면동별 지금 수치 · 우려지역(유형별) · 3대 유형 단계 대조 · 지구 대피기준까지 % ·
    상황전파 기준 · 특보 · 비상단계 · 재난문자 기준. 판정하지 않는다(st 는 '그 조건에 닿았나'일 뿐)."""
    base = base.rstrip("/")
    w = _get(base, "/api/ai/emdwin")                       # 읍면동 × 1·3·12·24·48시간 · 15분 — 한 번에
    mine_rows = [r for r in w["rows"] if r["sig"] == sigun]
    acc = {h: {r["emd"]: r.get(f"{h}h") for r in mine_rows} for h in WINDOWS}
    m15 = {r["emd"]: r.get("15m") for r in mine_rows}
    tm, src = w.get("tm"), "기상청 고해상도 격자(500m) · 매시 60분 합 + 지금 칸(일강수 증분)"
    fc = _get(base, "/api/forecast", hours=6, sigun=sigun)
    fce = {e["emd"]: e for e in fc.get("emd_sigun", []) if e.get("sigun") == sigun}
    al = (_get(base, "/api/alerts").get("data") or {})
    groups = al.get("groups", [])
    mine = [g["name"] for g in groups if sigun in g.get("siguns", [])]
    pend = [p for p in al.get("pending", []) if p.get("sigun") == sigun]
    now = datetime.strptime(tm, "%Y%m%d%H%M") if tm else datetime.now()
    night = now.hour >= 21 or now.hour < 6

    sites = _lookup()(WIKI, SIGUN_FULL.get(sigun, sigun), kind="all")
    by_emd: dict[str, list] = defaultdict(list)
    for s in sites["sites"]:
        by_emd[s["읍면동"]].append(s)

    emds = []
    for name in acc[3]:
        f = fce.get(name) or {}
        d = f.get("d") or []
        run, best = 0, 0
        for v in d:
            run = run + 1 if v >= 30 else 0
            best = max(best, run)
        row = {"emd": name, "rain": {f"{h}h": acc[h].get(name) for h in WINDOWS}, "m15": m15.get(name),
               "fc6h": f.get("sum"), "fc_peak": f.get("peak"), "fc_hours": d, "fc_run30": best if d else None}
        r1, r3, r24 = row["rain"]["1h"] or 0, row["rain"]["3h"] or 0, row["rain"]["24h"] or 0
        row["cbs"] = (r1 >= 50 and r3 >= 90) or r1 >= 72                   # [[재난문자 송출기준]]
        row["relay"] = r1 >= 20 or r24 >= 100                               # [[시군 상황관리반 행동매뉴얼]] 상황전파
        fam = Counter(FAMILY_OF.get(s["유형"], "야외·기타") for s in by_emd.get(name, []))
        row["risk"] = dict(fam)
        lad = ladders(row, night, mine)
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
    return {
        "sigun": sigun, "tm": tm, "night": night, "rain_src": src, "fc_tmfc": fc.get("tmfc"),
        "alerts": mine, "pending": pend, "stage": _stage(groups),
        "risk_total": dict(Counter(FAMILY_OF.get(s["유형"], "야외·기타") for s in sites["sites"])),
        "emd": emds,
        "rules": {"cbs": "1시간 50㎜ + 3시간 90㎜ 동시, 또는 1시간 72㎜(기상청 긴급재난문자)",
                  "relay": "시간당 20㎜ 이상 또는 일강우 100㎜ 이상 → 시군 재난상황실 유선 전파, 우려지역 통제·사전대피 여부 판단",
                  "principle": "사전대피는 예보, 긴급대피는 실황 · 일몰 전 사전대피 · 그 유형 우려지역에만 적용"},
        "limits": ["지구 좌표가 없어 읍면동 안 가장 많이 온 격자(500m)로 견준다 — 지구 강우의 상한",
                   f"초단기 예보 시우량은 {RN1_CAP:g}㎜ 에서 막혀 온다 — 50·55㎜/h 예보 조건은 '모름'",
                   "선행 5일 강우 · 토양함수 · 하천수위 · 침수심 · 예측정보(산림청 산사태 예보)는 여기 없다 — 따로 확인",
                   "목록에 없다고 위험이 없는 것이 아니다", "대피명령은 시장·군수·구청장 권한(재난안전법 제40조)",
                   sites["source_basis"]],
        "wiki": [f"[[{SIGUN_FULL.get(sigun, sigun)}]] (산사태 위험지역)", "[[통제·대피 기준]]", "[[시군 상황관리반 행동매뉴얼]]",
                 "[[대피명령 길라잡이]]", "[[위기경보와 비상단계]]", "[[재난문자 송출기준]]", "[[재난문자 표준문안]]"],
    }


STL = {"met": "충족", "near": "근접(70%↑)", "unknown": "모름", "no": "아님"}


def _na(v):
    return "자료 없음" if v is None else v


def brief(s: dict, top: int = 4) -> str:
    """LLM 맥락 · 사람이 읽는 짧은 글 — 닿았거나 가까운 것만 적는다."""
    t = s.get("tm") or ""
    out = [f"■ {s['sigun']} — {t[4:6]}.{t[6:8]}. {t[8:10]}:{t[10:12]} 실황 기준{' · 취약시간대(21~06시)' if s['night'] else ''}"]
    out.append("특보: " + (", ".join(s["alerts"]) or "없음") + (f" · 예비 {', '.join(p['name'] for p in s['pending'])}" if s["pending"] else ""))
    if s["stage"]:
        out.append(f"도 비상단계 기준: {s['stage']['stage']} ({s['stage']['why']})")
    out.append("우려지역(위키): " + " · ".join(f"{k} {v}" for k, v in sorted(s["risk_total"].items(), key=lambda x: -x[1])))
    relay = [r["emd"] for r in s["emd"] if r["relay"]]
    out.append("상황전파 기준(20㎜/h · 일 100㎜): " + (", ".join(relay) if relay else "없음"))
    cbs = [r["emd"] for r in s["emd"] if r["cbs"]]
    out.append("재난문자 기준(실황): " + (", ".join(cbs) if cbs else "없음"))
    for r in s["emd"][:top]:
        rn = r["rain"]
        hit = [f"{fam} {c['stage']} '{c['rule']}' {STL[c['st']]}" for fam, cs in r["ladders"].items() for c in cs if c["st"] in ("met", "near")]
        fc = f"앞으로 6h {r['fc6h']}(최대 {r['fc_peak']}/h)" if r["fc6h"] is not None else "앞으로 6h 예측 자료 없음"
        out.append(f"· {r['emd']} — 1h {rn['1h']} · 3h {rn['3h']} · 24h {rn['24h']} · 15분 {_na(r['m15'])} · {fc}"
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
