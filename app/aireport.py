"""AI 상황판단 — 보고서와 예상 질문(규칙으로 답한다 · LLM 없이도 된다). 자유 질문만 LLM(app/llm.py).

보고 형태: 상황 → 중요한 점 → 할 일 → 살펴볼 곳 → 다음 확인 → 참고(위키 페이지 · 책자 쪽수 · 연락처 있는 곳).
숫자는 app/ai.py(대시보드 API + 위키 lookup)에서, 기준 · 절차 · 문안은 위키 페이지에 적힌 것만.
⚠️ 연락처 · 실명은 위키에 없다(위키 AGENTS.md 7절) — 원문 어디에 있는지만 알린다.
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache

from . import ai, river

FAM_SHORT = {"산사태": "산사태", "하천": "하천", "지하공간": "지하공간", "침수·해안": "침수·해안", "야외·기타": "야외"}
CONTACTS = ("연락처 · 담당자는 위키에 두지 않는다(실명 · 전화번호) → 원문에서: "
            "「2026 여름철 자연재난 상황대응계획」 3장(우려지역 지구별 담당자) · p.109~114(시군 재난상황실 · 상황관리반 연락망)")
_TTL: dict = {}


def _cached(key, fn, ttl=120):
    hit = _TTL.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _TTL[key] = (time.time(), v)
    if len(_TTL) > 64:
        _TTL.pop(next(iter(_TTL)))
    return v


# ── 위키 페이지 · 책자 쪽수 ─────────────────────────────────────────────
@lru_cache(maxsize=1)
def _index() -> dict:
    out = {}
    for p in ai.wiki().rglob("*.md"):
        if any(x in p.parts for x in (".obsidian", "_install", "raw")):
            continue
        out.setdefault(p.stem, p)
    return out


@lru_cache(maxsize=256)
def page(name: str) -> dict:
    p = _index().get(name)
    if not p:
        return {"name": name}
    t = p.read_text("utf-8")
    fm = t.split("---", 2)[1] if t.startswith("---") else ""
    g = lambda k: (m.group(1).strip() if (m := re.search(rf"^{k}:\s*(.+)$", fm, re.M)) else "")  # noqa: E731
    return {"name": name, "summary": g("summary"), "src": g("출처"), "date": g("기준일"), "path": str(p.relative_to(ai.wiki()))}


def ref(name: str) -> str:
    m = page(name)
    return f"[[{name}]]" + (f" — {m['src']}" if m.get("src") else "") + (f" (기준일 {m['date']})" if m.get("date") else "")


def _rows(name: str) -> list[tuple[str, str]]:
    """위키 페이지의 표 줄 → (첫 칸, 둘째 칸)."""
    p = _index().get(name)
    if not p:
        return []
    out = []
    for ln in p.read_text("utf-8").splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if ln.startswith("|") and len(c) >= 2 and not set(c[0]) <= set("-: "):
            out.append((c[0], c[1]))
    return out


# ── 경남 전체 ───────────────────────────────────────────────────────────
def overview(base: str) -> dict:
    def build():
        w = ai._get(base, "/api/ai/emdwin")             # 읍면동 × 창 — 한 번에. 시군 값 = 그 시군 읍면동 가운데 최대

        def g(key):
            best = {}
            for r in w["rows"]:
                v = r.get(key)
                if v is not None and (r["sig"] not in best or v > best[r["sig"]]["sum"]):
                    best[r["sig"]] = {"sum": v, "name": r["emd"]}
            return best
        a1, a3, a24 = g("1h"), g("3h"), g("24h")
        tm = w.get("tm")
        m15 = {k: {"max": v["sum"]} for k, v in g("15m").items()}
        fc = {r["sigun"]: r for r in ai._get(base, "/api/forecast", hours=6).get("sigun", [])}
        al = ai._get(base, "/api/alerts").get("data") or {}
        groups = al.get("groups", [])
        rows = []
        for sg in ai.SIGUN_FULL:
            r1, r3, r24 = (a1.get(sg) or {}), (a3.get(sg) or {}), (a24.get(sg) or {})
            v1, v3, v24 = r1.get("sum") or 0, r3.get("sum") or 0, r24.get("sum") or 0
            sites = ai._lookup()(ai.wiki(), ai.SIGUN_FULL[sg], kind="all")["sites"]
            f = fc.get(sg) or {}
            rows.append({"sigun": sg, "emd1": r1.get("name"), "r1": v1, "r3": v3, "emd3": r3.get("name"), "r24": v24,
                         "m15": (m15.get(sg) or {}).get("max"), "fc_sum": f.get("sum"), "fc_emd": f.get("emd"),
                         "fc_peak": f.get("peak"),
                         "alerts": [x["name"] for x in groups if sg in x.get("siguns", [])],
                         "relay": v1 >= 20 or v24 >= 100, "cbs": (v1 >= 50 and v3 >= 90) or v1 >= 72,
                         "risk": dict(Counter(ai.FAMILY_OF.get(s["유형"], "야외·기타") for s in sites)),
                         "under": Counter(s["유형"] for s in sites)})
        lv = lambda r: 2 if "호우경보" in r["alerts"] else 1 if "호우주의보" in r["alerts"] else 0  # noqa: E731
        rows.sort(key=lambda r: (-lv(r), -r["r3"], -r["r24"]))
        now = datetime.strptime(tm, "%Y%m%d%H%M") if tm else datetime.now()
        return {"tm": tm, "night": now.hour >= 21 or now.hour < 6, "groups": groups, "pending": al.get("pending", []),
                "stage": ai._stage(groups), "rows": rows, "computed": bool(al.get("computed"))}
    return _cached(("ov", base), build)


def situation(sigun: str, base: str) -> dict:
    return _cached(("sg", base, sigun), lambda: ai.situation(sigun, base))


def _when(tm: str | None) -> str:
    if not tm:
        return ""
    return f"{int(tm[4:6])}.{int(tm[6:8])}. {tm[8:10]}:{tm[10:12]}"


def _next(tm: str | None) -> str:
    if not tm:
        return "다음 정시"
    t = datetime.strptime(tm, "%Y%m%d%H%M").replace(minute=0) + timedelta(hours=1)
    return f"{t:%H}:00 정시"


STL = {"met": "해당", "near": "가까움"}


def _gt(c: dict) -> str:
    """판정 줄 뒤에 붙일 '[기준 78% · 남은 22㎜(일/누적) · 예보대로면 14시경 닿음]' — 모르면 빈 글."""
    t = ai.gap_text(c)
    return f" [{t}]" if t else ""


def _emd_line(s: dict, r: dict, sites_by: dict) -> str:
    rn = r["rain"]
    bits = [f"시간당 {rn['1h']:g}㎜" if rn["1h"] is not None else "", f"3시간 {rn['3h']:g}㎜" if rn["3h"] is not None else "",
            f"24시간 {rn['24h']:g}㎜" if rn["24h"] is not None else ""]
    ln = f"{s['sigun']} {r['emd']} — " + " · ".join(b for b in bits if b)
    if r.get("fc6h"):
        ln += f" · 앞으로 6시간 {r['fc6h']:g}㎜"
    if r.get("ante") is not None and r["ante"] >= 60:
        ln += f" · 직전 5일 {r['ante']:g}㎜(선행강우 기준 120㎜)"
    hits = [f"{fam} {c['stage']} 기준({c['rule']}) {STL[c['st']]}{_gt(c)}" for fam, cs in r["ladders"].items() for c in cs if c["st"] in STL]
    if hits:
        ln += ". " + "; ".join(hits[:3])
    names = [f"{x['유형']} {_site_name(x)}({x['리']}{', ' + x['인원'] + '명' if x['인원'] not in ('', '-') else ''}{' → ' + x['대피장소'] if x['대피장소'] not in ('', '-') else ''})"
             for x in sites_by.get(r["emd"], [])[:3]]
    if names:
        ln += ". 우려지역: " + ", ".join(names)
    return ln


def _ante_note(sits: list[dict]) -> str:
    """'선행 5일 강우' 확인 문구 — 5일치 격자가 모였으면 대시보드가 계산했다는 것, 아니면 데이터가 없어 못 한다는 것."""
    a = next((s.get("ante") for s in sits if s.get("ante")), None)
    if a and a.get("ok"):
        return "직전 5일 강우는 대시보드가 격자로 계산했다(읍면동 최대 칸). 산림청 산사태 예측정보 · 토양함수 · 하천 수위는 따로 확인"
    if a:
        return (f"직전 5일 강우는 계산하지 못했다 — 정시 격자 {a.get('have')}시간치뿐(5일 = {a.get('want')}시간 필요). "
                "산림청 산사태 예측정보 · 토양함수 · 하천 수위도 따로 확인")
    return "직전 5일 강우 · 산림청 산사태 예측정보 · 토양함수 · 하천 수위는 따로 확인"


def _site_name(x: dict) -> str:
    """지구명 — 창원은 그 칸에 구 이름('마산합포구')이 와서 리 이름으로 부른다."""
    n = (x.get("지구명") or "").strip()
    return x.get("리") or n if (not n or n.endswith("구")) else n


def _few(items: list[str], n: int = 6) -> str:
    """길면 자른다 — 'A, B, C 외 4곳'."""
    items = list(dict.fromkeys(items))
    return ", ".join(items[:n]) + (f" 외 {len(items) - n}곳" if len(items) > n else "")


def _relay_txt(r: dict) -> str:
    """상황전파에 걸린 까닭 — 시간당이 넘었으면 시간당, 아니면 일(24시간)."""
    if r["r1"] >= 20:
        return f"{r['sigun']}({r['emd1']} 시간당 {r['r1']:g}㎜)"
    return f"{r['sigun']}(24시간 {r['r24']:g}㎜)"


def _sites_by(sigun: str) -> dict:
    out: dict = {}
    for x in ai._lookup()(ai.wiki(), ai.SIGUN_FULL.get(sigun, sigun), kind="all")["sites"]:
        out.setdefault(x["읍면동"], []).append(x)
    return out


def _tasks(stage, relay_where: str, s_list: list[dict], night: bool, cbs: list[str], sg_for_relay: str) -> list[str]:
    t = []
    if stage:
        t.append(f"도 {stage['stage']} 기준 — 근무 편성 확인, 상황판단회의로 단계 확정 ({'[[위기경보와 비상단계]] · [[상황판단회의]]'})")
    if relay_where:
        t.append(f"{sg_for_relay}재난상황실에 유선 전파 — {relay_where}: 시간당 20㎜ 이상(또는 일 100㎜ 이상), "
                 "우려지역 통제·사전대피 여부 판단 요청, 통화 기록 남기기 ([[시군 상황관리반 행동매뉴얼]])")
    emerg, pre, ctrl = [], [], []
    for s in s_list:
        for r in s["emd"]:
            for fam, cs in r["ladders"].items():
                for c in cs:
                    if c["st"] != "met":
                        continue
                    where = f"{s['sigun']} {r['emd']} {fam}"
                    (emerg if c["stage"] == "긴급대피" else pre if c["stage"] == "사전대피" else ctrl).append(where)
    if emerg:
        t.append("긴급대피 실황 기준 해당 — " + _few(emerg, 6) +
                 ": 시장·군수 보고, 대피명령 검토 지원, 대피 현황(세대 · 인원) 파악 ([[대피명령 길라잡이]] · [[통제·대피 기준]])")
    if pre:
        t.append("사전대피 기준 해당 — " + _few(pre, 6) +
                 ": 상황판단회의로 사전대피 권고 검토, 취약계층 먼저 · 일몰 전 원칙 ([[대피명령 길라잡이]])")
    if ctrl:
        t.append("통제 기준 해당 — " + _few(ctrl, 6) + ": 통제 상황 확인 (지하차도 · 하천변 산책로 · 둔치주차장 · 산사태 지구) ([[통제·대피 기준]])")
    if cbs:
        t.append("긴급재난문자 기준(1시간 50 + 3시간 90 · 또는 1시간 72㎜) 해당 가능 — " + _few(cbs, 8) +
                 ": 기상청 송출 여부 확인, 시군 문자 문안 ([[재난문자 송출기준]] · [[재난문자 표준문안]])")
    if night:
        t.append("야간(취약시간대) — 현장 확인은 2인 1조, 단독 출입 · 붕괴 위험지역 접근 금지 ([[시군 상황관리반 행동매뉴얼]])")
    if not t:
        t.append("특이사항 없음 — 정시마다 실황 · 예측 확인 유지")
    return t


def _refs(names: list[str]) -> list[str]:
    return [ref(n) for n in dict.fromkeys(names)] + [CONTACTS]


BASE_REFS = ["통제·대피 기준", "시군 상황관리반 행동매뉴얼", "대피명령 길라잡이", "위기경보와 비상단계", "재난문자 송출기준"]
Q_ALL = [("relay", "상황전파 해야 할 곳은?"), ("stage", "비상단계 · 다음 단계 조건은?"),
         ("evac", "대피 기준에 닿은 곳은?"), ("control", "통제할 시설은? (지하차도 · 하천변 · 둔치)"),
         ("forecast", "앞으로 6시간 비가 더 올 곳은?"), ("msg", "재난문자 기준 · 문안은?"),
         ("book", "연락처 · 책자 어디를 보면 되나?")]
Q_SIG = [("order", "어느 읍면동을 먼저 봐야 하나?"), ("sites", "산사태 지구 · 대피장소는?"),
         ("control", "통제할 시설은?"), ("evac", "사전대피 · 긴급대피 기준까지 얼마나 남았나?"),
         ("msg", "주민 재난문자 문안 초안"), ("book", "연락처 · 책자 어디를 보면 되나?")]


MODES = [("all", "종합"), ("meeting", "상황판단회의"), ("dept", "단계별 부서 임무"), ("evac", "대피 판단"),
         ("control", "통제(지하차도 · 하천)"), ("msg", "재난문자"), ("brief", "상황보고")]


def report(base: str, sigun: str | None = None, mode: str = "all") -> dict:
    """mode — all(종합) · meeting(상황판단회의) · evac(대피 판단) · control(지하차도 · 하천 통제) · msg(재난문자) · brief(상황보고)."""
    if mode and mode != "all":
        fn = {"meeting": _m_meeting, "dept": _m_dept, "evac": _m_evac, "control": _m_control, "msg": _m_msg, "brief": _m_brief}.get(mode)
        if fn:
            r = fn(base, sigun)
            r.setdefault("questions", [{"id": k, "label": v} for k, v in (Q_SIG if sigun else Q_ALL)])
            r["mode"] = mode
            return r
    if sigun:
        return _report_sigun(base, sigun)
    o = overview(base)
    rows = o["rows"]
    hoou = [(g["name"], g["siguns"]) for g in o["groups"] if g["name"].startswith("호우")]
    others = [g["name"] for g in o["groups"] if not g["name"].startswith("호우")]
    sit = [f"{_when(o['tm'])} 실황" + (" · 취약시간대(21~06시)" if o["night"] else "") +
           (" · 특보는 산출값(가상)" if o["computed"] else "")]
    sit.append("특보: " + (" · ".join(f"{n} {len(s)}개 시군({'·'.join(s)})" for n, s in hoou) or "호우특보 없음")
               + (f" · 그 밖에 {', '.join(others)}" if others else ""))
    if o["stage"]:
        sit.append(f"도 비상단계 기준: {o['stage']['stage']} ({o['stage']['why']}) — 최종은 상황판단회의")
    over = ai.overrides()
    own = {sg: d for sg in ai.SIGUN_FULL
           if (d := ai.sigun_stage(sg, next((r["alerts"] for r in rows if r["sigun"] == sg), []),
                                   [x["name"] for x in o["pending"] if x.get("sigun") == sg], over.get(sg)))}
    sit.append("시군 비상단계(거제 · 통영은 자기 매뉴얼, 나머지는 거제 기준 준용 — 평시가 아닌 시군만): "
               + (" · ".join(f"{ai.SIGUN_FULL[sg]} {d['stage']}" + (f"(수동 입력 · 특보 기준 {d['auto']})" if d["set"] else f"({d['why']})")
                             for sg, d in own.items() if d["stage"] != ai._manual(sg)["base"]) or "모든 시군 평시") + " — 도 단계와 별개")
    wet = [r for r in rows if r["fc_sum"]]
    top_fc = max(wet, key=lambda r: r["fc_sum"]) if wet else None
    rs = river.summary()
    if rs:
        sit.append(rs["text"])
    sit.append("앞으로 6시간: " + (f"가장 많은 곳 {top_fc['sigun']} {top_fc['fc_emd']} {top_fc['fc_sum']:g}㎜(최대 시간당 {top_fc['fc_peak']:g}㎜)"
                                if top_fc else "비 예보 거의 없음"))
    relay = [r for r in rows if r["relay"]]
    cbs = [r["sigun"] for r in rows if r["cbs"]]
    # 살펴볼 곳 — 특보 · 비가 많은 시군 셋을 읍면동까지
    focus = [r["sigun"] for r in rows if r["relay"] or r["alerts"]][:3]
    sits = [situation(sg, base) for sg in focus]
    imp = []
    if relay:
        imp.append(f"시간당 20㎜ · 일 100㎜ 넘은 시군 {len(relay)}곳: " + _few([_relay_txt(r) for r in relay], 8))
    if cbs:
        imp.append("긴급재난문자 기준 해당 가능: " + ", ".join(cbs))
    for s in sits:
        hits = [f"{r['emd']} {fam} {c['stage']}" for r in s["emd"] for fam, cs in r["ladders"].items() for c in cs if c["st"] == "met" and c["stage"] != "통제"]
        if hits:
            imp.append(f"{s['sigun']}: 대피 기준 해당 — " + _few(hits, 5))
    if not imp:
        imp.append("기준에 닿은 곳 없음")
    tasks = _tasks(o["stage"], _few([r["sigun"] for r in relay], 8), sits, o["night"], cbs, "해당 시군 ")
    look = []
    for s in sits:
        sb = _sites_by(s["sigun"])
        for r in [x for x in s["emd"] if x["risk"]][:2]:
            look.append(_emd_line(s, r, sb))
    nxt = [f"{_next(o['tm'])} 실황 · 초단기 새 발표"]
    st = (o["stage"] or {}).get("stage")
    if st != "비상 2단계":
        nxt.append("호우경보 3개 시군 이상 → 도 비상 2단계" if st == "비상 1단계" else "호우주의보 4개 시군 이상 → 도 비상 1단계")
    nxt.append(_ante_note(sits))
    return {"scope": "경남", "title": "경남 전체", "tm": o["tm"], "flash": _flash_all(o, sits, own),
            "sections": [{"h": "상황", "items": sit}, {"h": "중요한 점", "items": imp}, {"h": "할 일", "items": tasks},
                         {"h": "살펴볼 곳", "items": look or ["특별히 살펴볼 읍면동 없음"]}, {"h": "다음 확인", "items": nxt},
                         {"h": "참고 — 위키 · 책자", "items": _refs(BASE_REFS + ["상황판단회의"])}],
            "questions": [{"id": k, "label": v} for k, v in Q_ALL]}


def _flash_sigun(s: dict, full: str) -> dict:
    """속보 한 줄 — 시군 하나. 시군 비상단계(매뉴얼이 있으면) · 우려지역 강우 기준 상태 · 가장 센 기준 한 개.
    톤(tone)은 화면 줄 색 — 0 없음 · 1 근접만 · 2 통제 충족 · 3 사전대피/긴급대피 충족."""
    cs = [c for r in s["emd"] for v in r["ladders"].values() for c in v]
    tone, rain = ai.rain_state(cs)
    sd = ai.sigun_stage(s["sigun"], s["alerts"], [p["name"] for p in s["pending"]], ai.overrides().get(s["sigun"]))
    txt = f"{_when(s['tm'])} 실황 · {full}"
    if sd:
        txt += f" 비상단계 {sd['stage']}" + (f"(수동 입력 · 특보 기준 {sd['auto']})" if sd["set"] else "")
    txt += f" · 우려지역 기준: {rain or '닿은 곳 없음'}"
    rv = s.get("river")
    if rv and rv["stage"] >= 1:
        txt += f" · 하천 {rv['name']} {ai.RV_NAME[rv['stage']]} 수위"
        tone = max(tone, 3 if rv["stage"] >= 3 else rv["stage"])
    rank = {"긴급대피": 3, "사전대피": 2, "통제": 1}
    best = max(((rank[c["stage"]], c["st"] == "met", r["emd"], fam, c) for r in s["emd"] for fam, cs2 in r["ladders"].items()
                for c in cs2 if c["st"] in ("met", "near") and c.get("gap")), key=lambda x: x[:2], default=None)
    if best:
        _, _, emd, fam, c = best
        txt += f". 가장 센 기준: {emd} {fam} {c['stage']} — {ai.gap_text(c)}"
    return {"tone": tone, "text": txt}


def _flash_all(o: dict, sits: list[dict], own: dict) -> dict:
    """속보 한 줄 — 경남 전체. 도 비상단계 · 시군 비상단계(평시가 아닌 것) · 우려지역 기준에 닿은 시군(훑은 시군만)."""
    parts = [f"{_when(o['tm'])} 실황"]
    if o["stage"]:
        parts.append(f"도 비상단계 {o['stage']['stage']}({o['stage']['why']})")
    up = [f"{ai.SIGUN_FULL[sg]} {d['stage']}" + ("(수동 입력)" if d["set"] else "") for sg, d in own.items()
          if d["stage"] != ai._manual(sg)["base"]]
    if up:
        parts.append("시군 비상단계 " + ", ".join(up))
    tone, hit = 0, []
    for s in sits:
        t, txt = ai.rain_state([c for r in s["emd"] for v in r["ladders"].values() for c in v])
        if t:
            hit.append(f"{s['sigun']} {txt}")
        tone = max(tone, t)
    if hit:
        parts.append("우려지역 기준: " + _few(hit, 4))
    rs = river.summary()
    if rs and rs["n"]:
        parts.append(f"하천 {rs['top']}" + (f" 외 {rs['n'] - 1}곳" if rs["n"] > 1 else ""))
        tone = max(tone, 3 if rs["tone"] >= 3 else rs["tone"])
    if len(parts) == 1:
        parts.append("경남 전체 평시 — 호우특보 · 우려지역 기준 근접 없음")
    return {"tone": tone, "text": " · ".join(parts)}


def _report_sigun(base: str, sigun: str) -> dict:
    s = situation(sigun, base)
    sb = _sites_by(sigun)
    sit = [f"{_when(s['tm'])} 실황" + (" · 취약시간대(21~06시)" if s["night"] else "")]
    sit.append("특보: " + (", ".join(s["alerts"]) or "없음") + (f" · 예비 {', '.join(p['name'] for p in s['pending'])}" if s["pending"] else ""))
    if s["stage"]:
        sit.append(f"도 비상단계 기준: {s['stage']['stage']} ({s['stage']['why']})")
    sd = ai.sigun_stage(sigun, s["alerts"], [p["name"] for p in s["pending"]], ai.overrides().get(sigun))
    sit.append("시군 비상단계: " + (ai.stage_text(sigun, sd) if sd else "이 시군의 매뉴얼은 위키에 아직 없다 — 도 기준만 본다"))
    sit.append("우려지역(위키): " + " · ".join(f"{FAM_SHORT[k]} {v}" for k, v in sorted(s["risk_total"].items(), key=lambda x: -x[1])))
    sit.append(ai.river_text(s.get("river")))
    relay = [r for r in s["emd"] if r["relay"]]
    imp = []
    if relay:
        imp.append(f"시간당 20㎜ · 일 100㎜ 넘은 읍면동 {len(relay)}곳: " +
                   ", ".join(f"{r['emd']}({r['rain']['1h']:g}㎜/h)" for r in sorted(relay, key=lambda x: -(x['rain']['1h'] or 0))[:8]))
    for r in s["emd"]:
        for fam, cs in r["ladders"].items():
            for c in cs:
                if c["st"] == "met":
                    imp.append(f"{r['emd']} {fam} {c['stage']} 기준 해당 — {c['rule']}")
    cbs = [r["emd"] for r in s["emd"] if r["cbs"]]
    if cbs:
        imp.append("긴급재난문자 기준 해당 가능: " + _few(cbs, 8))
    rv = s.get("river")
    if rv and rv["stage"] >= 2:
        imp.append(f"하천 수위: {rv['name']} {ai.RV_NAME[rv['stage']]} 수위 이상({rv['wl']:.2f}m) — 하천변 통제 · 대피 판단 확인(홍수통제소 홍수정보)")
    if not imp:
        imp.append("기준에 닿은 곳 없음")
    full = ai.SIGUN_FULL.get(sigun, sigun)
    tasks = _tasks(s["stage"], _few([r["emd"] for r in relay], 6), [s], s["night"], cbs, f"{full} ")
    look = [_emd_line(s, r, sb) for r in [x for x in s["emd"] if x["risk"]][:4]]
    nxt = [f"{_next(s['tm'])} 실황 · 초단기 새 발표"]
    near = [f"{r['emd']} {fam} {c['stage']}({c['rule']}){_gt(c)}" for r in s["emd"] for fam, cs in r["ladders"].items() for c in cs if c["st"] == "near"]
    if near:
        nxt.append("가까워진 기준: " + "; ".join(near[:4]))
    if s["night"]:
        nxt.append("취약시간대 — 시간당 30㎜ 이상 예보가 나오면 산사태 사전대피 조건")
    nxt.append(_ante_note([s]))
    return {"scope": sigun, "title": full, "tm": s["tm"], "flash": _flash_sigun(s, full),
            "sections": [{"h": "상황", "items": sit}, {"h": "중요한 점", "items": imp}, {"h": "할 일", "items": tasks},
                         {"h": "살펴볼 곳", "items": look or ["우려지역이 있는 읍면동에 비 없음"]}, {"h": "다음 확인", "items": nxt},
                         {"h": "참고 — 위키 · 책자", "items": _refs([full] + BASE_REFS + ["시군별 통제·대피계획"])}],
            "questions": [{"id": k, "label": v} for k, v in Q_SIG]}


# ── 예상 질문 — 규칙으로 답한다 ──────────────────────────────────────────
def answer(base: str, qid: str, sigun: str | None = None) -> dict:
    sec = []
    if qid == "book":
        names = ([ai.SIGUN_FULL.get(sigun, sigun)] if sigun else []) + BASE_REFS + ["재난문자 표준문안", "시군별 통제·대피계획", "상황판단회의"]
        sec = [{"h": "책자 · 위키 페이지", "items": [ref(n) for n in dict.fromkeys(names)]},
               {"h": "연락처", "items": [CONTACTS, "시군 상황실 · 스마트방재시스템 계정은 위키에 없다 — 원문 p.109~114 (위키 [[시군 상황관리반 행동매뉴얼]] '옮기지 않은 것')"]}]
    elif qid == "msg":
        rows = _rows("재난문자 표준문안")
        want = ("산사태", "대응1", "사전대비1", "대피", "호우경보", "호우주의보")
        sec = [{"h": "표준문안(위키 [[재난문자 표준문안]] — 90자, ○○에 시각 · 지역 · 대피소)",
                "items": [f"{a}: {b}" for a, b in rows if any(w in a for w in want)][:8] or ["위키에서 문안 표를 못 읽었다"]},
               {"h": "송출 기준", "items": [ref("재난문자 송출기준"), "1시간 50㎜ + 3시간 90㎜ 동시, 또는 1시간 72㎜ — 기상청 긴급재난문자"]}]
    elif sigun:
        s = situation(sigun, base)
        sb = _sites_by(sigun)
        if qid == "order":
            sec = [{"h": "먼저 볼 읍면동", "items": [_emd_line(s, r, sb) for r in [x for x in s["emd"] if x["risk"]][:6]]}]
        elif qid == "sites":
            items = [f"{e} — {x['유형']} {_site_name(x)}({x['리']}, {x['인원']}명) · 대피기준 '{x['대피기준']}' · 대피장소 {x['대피장소']}"
                     for e, xs in sb.items() for x in xs if ai.FAMILY_OF.get(x["유형"]) == "산사태"]
            sec = [{"h": f"산사태 지구 {len(items)}곳 (위키 [[{ai.SIGUN_FULL.get(sigun, sigun)}]])", "items": items[:30] or ["없음"]}]
        elif qid == "control":
            items = [f"{e} — {x['유형']} {_site_name(x)}({x['리']}) · {x['대피장소'] or x['대피기준']}"
                     for e, xs in sb.items() for x in xs if ai.FAMILY_OF.get(x["유형"]) in ("하천", "지하공간")]
            sec = [{"h": "통제 대상(하천변 · 둔치 · 지하차도 · 지하공간)", "items": items[:30] or ["없음"]},
                   {"h": "기준", "items": ["지하차도: 호우특보 발령 시 통제 · 하천: 30㎜/h 이상 3시간 지속 예보 시 통제 (위키 [[통제·대피 기준]])"]}]
        elif qid == "evac":
            items = []
            for r in s["emd"]:
                for fam, cs in r["ladders"].items():
                    for c in cs:
                        if c["stage"] != "통제" and c["st"] in ("met", "near", "unknown"):
                            items.append(f"{r['emd']} {fam} {c['stage']} — {c['rule']}: {({'met': '해당', 'near': '가까움', 'unknown': '모름(자료 없음)'})[c['st']]}")
                for x in r["sites"][:1]:
                    if x["conds"]:
                        items.append(f"{r['emd']} 지구 원문 '{x['rule']}' — 지금 " + ", ".join(f"{c['label']} {c['now']}㎜(기준 {c['mm']:g})" for c in x["conds"]))
            sec = [{"h": "대피 기준 대조", "items": items[:20] or ["가까운 기준 없음"]},
                   {"h": "주의", "items": ["원문의 그리고/또는 · 토양함수 같은 붙은 조건은 판정하지 않는다", "대피명령은 시장·군수 권한 (위키 [[대피명령 길라잡이]])"]}]
    else:
        o = overview(base)
        rows = o["rows"]
        if qid == "relay":
            sec = [{"h": "상황전파 대상(시간당 20㎜ · 일 100㎜)", "items": [f"{r['sigun']} — {r['emd1']} 시간당 {r['r1']:g}㎜ · 24시간 {r['r24']:g}㎜" for r in rows if r["relay"]] or ["없음"]},
                   {"h": "전파 방법", "items": ["유선으로 시군 재난상황실에 — 수신자 · 송신자 · 통화시간 · 내용 기록 (위키 [[시군 상황관리반 행동매뉴얼]] 전파 문안)"]}]
        elif qid == "stage":
            sec = [{"h": "지금", "items": [f"{o['stage']['stage']} — {o['stage']['why']}" if o["stage"] else "호우특보 없음 — 상시대비"]},
                   {"h": "단계 기준(호우)", "items": ["초기대응: 주의보 3개 시군 이하", "비상 1단계: 주의보 4개 시군 이상 · 경보 2개 이하",
                                                    "비상 2단계: 경보 3개 시군 이상 · 국지적 피해", "비상 3단계: 광역적 경보 · 광역적 피해",
                                                    "도서 · 산지 · 먼바다 특보는 셈에서 뺀다 — " + ref("위기경보와 비상단계")]}]
        elif qid == "evac":
            items = []
            for r in rows:
                if not (r["relay"] or r["alerts"]):
                    continue
                s = situation(r["sigun"], base)
                for e in s["emd"]:
                    for fam, cs in e["ladders"].items():
                        for c in cs:
                            if c["stage"] != "통제" and c["st"] in ("met", "near"):
                                items.append(f"{r['sigun']} {e['emd']} {fam} {c['stage']} — {c['rule']}: {STL[c['st']]}")
            sec = [{"h": "대피 기준 해당 · 가까움", "items": items[:25] or ["없음"]}]
        elif qid == "control":
            items = []
            for r in rows:
                if not r["alerts"]:
                    continue
                n = r["under"]
                parts = [f"{t} {n[t]}" for t in ("지하차도", "하천변산책로", "둔치주차장", "지하시설,지하주차장,지하상가", "반지하주택가") if n.get(t)]
                if parts:
                    items.append(f"{r['sigun']}({', '.join(r['alerts'])}) — " + " · ".join(parts))
            sec = [{"h": "특보 시군의 통제 대상(위키 우려지역)", "items": items or ["없음"]},
                   {"h": "기준", "items": ["지하차도는 호우특보 발령 시 통제 · 하천은 30㎜/h 3시간 지속 예보 시 통제 — " + ref("통제·대피 기준")]}]
        elif qid == "forecast":
            items = [f"{r['sigun']} {r['fc_emd']} — 앞으로 6시간 {r['fc_sum']:g}㎜(최대 시간당 {r['fc_peak']:g}㎜)"
                     for r in sorted([x for x in rows if x["fc_sum"]], key=lambda x: -x["fc_sum"])[:8]]
            sec = [{"h": "초단기 예보(앞으로 6시간, 읍면동 최대)", "items": items or ["비 예보 거의 없음"]},
                   {"h": "주의", "items": ["초단기 예보 시우량은 30㎜ 에서 막혀 온다 — 그 위는 기상청 예보문 · 특보로 확인"]}]
    if not sec:
        sec = [{"h": "답", "items": ["이 질문은 시군을 고른 뒤에 답한다" if qid in dict(Q_SIG) else "모르는 질문"]}]
    return {"sections": sec, "source": "규칙(대시보드 수치 + 위키)"}


SYSTEM_HEAD = ("너는 경상남도 재난안전상황실의 풍수해 상황판단 보조다. 아래 [지시문]과 [지금 상황]만 근거로 짧게 답한다. "
               "위키에 없는 것은 '모름'이라 하고, 대피 결정은 권한자 몫으로 남긴다. 연락처 · 실명은 쓰지 않는다.")


def ask_free(base: str, text: str, sigun: str | None = None) -> dict:
    from . import llm
    if not llm.mode():
        return {"sections": [{"h": "자유 질문", "items": [
            "LLM 이 연결되지 않았다 — 위 예상 질문은 바로 답한다.",
            "켜는 법: GN_AI=claude-cli(Claude Code — PC 로그인 또는 config/claude/token.txt) 또는 "
            "GN_AI=openai(Hermes 등 OpenAI 호환 주소 · 키)."]}], "source": "없음"}
    rep = report(base, sigun)
    ctx = "\n".join(f"[{s['h']}]\n" + "\n".join("- " + i for i in s["items"]) for s in rep["sections"])
    if sigun:
        ctx += "\n\n[읍면동 수치]\n" + ai.brief(situation(sigun, base), top=8)
    skill = (ai.Path(__file__).resolve().parent.parent / "deploy" / "hermes" / "gn-situation" / "SKILL.md")
    system = SYSTEM_HEAD + "\n\n[지시문]\n" + (skill.read_text("utf-8") if skill.exists() else "")
    try:
        out = llm.ask(system, f"[지금 상황]\n{ctx}\n\n[질문]\n{text}")
    except Exception as e:                      # noqa: BLE001
        return {"sections": [{"h": "자유 질문", "items": [f"LLM 이 답하지 못했다 — {e}"[:300]]}], "source": llm.mode()}
    return {"text": out, "source": llm.mode()}


# ── 목적별 보고 ─────────────────────────────────────────────────────────
def _scope(base: str, sigun: str | None) -> tuple[dict, list[dict]]:
    """경남 전체면 특보 · 상황전파 시군(최대 6)을, 시군이면 그 시군을 읍면동까지."""
    o = overview(base)
    if sigun:
        return o, [situation(sigun, base)]
    focus = [r["sigun"] for r in o["rows"] if r["relay"] or r["alerts"]][:6]
    return o, [situation(sg, base) for sg in focus]


def _hdr(o: dict, sigun: str | None, title: str) -> dict:
    return {"scope": sigun or "경남", "title": f"{ai.SIGUN_FULL.get(sigun, sigun) if sigun else '경남 전체'} — {title}", "tm": o["tm"]}


def _hits(sits: list[dict], stages=("긴급대피", "사전대피", "통제"), states=("met",)) -> list[tuple]:
    out = []
    for s_ in sits:
        for r in s_["emd"]:
            for fam, cs in r["ladders"].items():
                for c in cs:
                    if c["stage"] in stages and c["st"] in states:
                        out.append((s_["sigun"], r, fam, c))
    return out


def _history(siguns: list[str], n: int = 6) -> list[str]:
    """위키 [[경남 자연재난 이력]] 표에서 그 시군이 든 사건(또는 전 시군)."""
    rows = []
    p_ = _index().get("경남 자연재난 이력")
    if not p_:
        return ["위키에 [[경남 자연재난 이력]] 이 없다"]
    for ln in p_.read_text("utf-8").splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if not ln.startswith("|") or len(c) < 8 or not c[0][:4].isdigit():
            continue
        area = c[7]
        if any(sg in area for sg in siguns) or "전 시군" in area or "개 시군" in area:
            dead = "·".join(x for x in (f"사망 {c[3]}" if c[3] not in ("–", "-", "") else "", f"실종 {c[4]}" if c[4] not in ("–", "-", "") else "") if x)
            rows.append(f"{c[0]} {c[1]} {c[2]} — {dead + ' · ' if dead else ''}이재민 {c[5]} · 재산피해 {c[6]}억 · {area}".replace("**", ""))
    return rows[:n] or ["이 시군이 든 사건이 위키 표에 없다"]


def _uosim(siguns: list[str]) -> list[str]:
    """위키 [[경남 시군별 우심피해 이력]] — 국고 지원 기준 이상 피해가 난 해 · 금액(재해연보 4-4.6)."""
    p_ = _index().get("경남 시군별 우심피해 이력")
    if not p_:
        return []
    head, out = None, {}
    for ln in p_.read_text("utf-8").splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if not ln.startswith("|") or len(c) < 4:
            continue
        if c[0] == "시군":
            head = c
            continue
        if not head or set(c[0]) <= set("-: "):
            continue
        name = re.sub(r"[\[\]]", "", c[0]).replace("시", "").replace("군", "") if c[0] else ""
        short = next((k for k, v in ai.SIGUN_FULL.items() if v == re.sub(r"[\[\]]", "", c[0])), name)
        yrs = [f"{head[i]} {re.sub(r'\s*\(\d+\)', '', c[i])}" for i in range(1, len(head) - 2) if i < len(c) and c[i] not in ("–", "-", "")]
        out[short] = (yrs, c[-2] if len(c) >= 2 else "")
    rows, none = [], []
    for sg in siguns:
        if sg in out:
            yrs, n = out[sg]
            if yrs:
                rows.append(f"{sg} — 우심피해 {n}회: {' · '.join(yrs)}")
            else:
                none.append(sg)
    if none:
        rows.append(f"{' · '.join(none)} — 2014~2024 우심피해 없음")
    return rows


@lru_cache(maxsize=1)
def _cases() -> list[dict]:
    """위키 이력/ 의 사례 페이지(tags 에 사례) — '## 기상' 표에서 지역별 누적 · 최대일 · 일최대 60분."""
    out = []
    for name, p_ in _index().items():
        if "이력" not in p_.parts:
            continue
        t = p_.read_text("utf-8")
        fm = t.split("---", 2)[1] if t.startswith("---") else ""
        if "사례" not in fm:
            continue
        sec = t.split("## 기상", 1)[1].split("\n## ", 1)[0] if "## 기상" in t else ""
        rows = {}
        for ln in sec.splitlines():
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if ln.startswith("|") and len(c) >= 4 and c[0] in ai.SIGUN_FULL:
                nums = [re.search(r"([\d.]+)\s*mm", x) for x in c[1:4]]
                if all(nums):
                    rows[c[0]] = {"total": float(nums[0].group(1)), "day": float(nums[1].group(1)), "h1": float(nums[2].group(1))}
        if rows:
            out.append({"name": name, "rows": rows, "summary": page(name).get("summary", "")})
    return out


def _analogs(o: dict, siguns: list[str]) -> list[str]:
    """지금 비 ↔ 위키 사례의 그때 비(같은 시군) — 시간당 · 24시간 최대를 그때 일최대 60분 · 최대일과 나란히."""
    by = {r["sigun"]: r for r in o["rows"]}
    out = []
    for c in _cases():
        for sg in siguns:
            if sg in c["rows"] and sg in by:
                now_, then = by[sg], c["rows"][sg]
                if now_["r1"] < 10 and now_["r24"] < 20:     # 비가 거의 없으면 견줄 것이 없다
                    continue
                cmp1 = "시간당은 그때를 넘었다" if now_["r1"] > then["h1"] else f"시간당은 그때보다 {then['h1'] - now_['r1']:.0f}㎜ 적다"
                cmp24 = ("24시간은 그때 최대일을 넘었다" if now_["r24"] > then["day"]
                         else f"24시간은 그때 최대일보다 {then['day'] - now_['r24']:.0f}㎜ 적다")
                out.append(f"{sg}: 지금 시간당 {now_['r1']:g}㎜ · 24시간 {now_['r24']:g}㎜ ↔ [[{c['name']}]] 때 일최대 60분 {then['h1']:g}㎜ · "
                           f"최대일 {then['day']:g}㎜ · 누적 {then['total']:g}㎜ — {cmp1}, {cmp24}")
    return out


def _calm(o: dict, rows: list[dict], hit: bool = False) -> bool:
    """비가 없고 올 우려도 없다 — 호우특보 · 상황전파(시간당 20㎜ · 일 100㎜) · 재난문자 기준 · 대피 기준 해당 없음,
    앞으로 6시간 시군 합 30㎜ 미만 · 시간당 20㎜ 미만. 이때는 자료를 펼치지 않고 '언제부터 필요한가'만 보인다."""
    return not (hit or any(g["name"].startswith("호우") for g in o["groups"])
                or any(r["relay"] or r["cbs"] or (r["fc_sum"] or 0) >= 30 or (r["fc_peak"] or 0) >= 20 for r in rows))


def _quiet(o: dict, sigun: str | None, rows: list[dict], title: str, when: list[str], refs: list[str]) -> dict:
    """한가할 때의 짧은 보고 — 지금 상태 한 줄 + 언제부터 필요한가 + 참고."""
    top = max(rows, key=lambda r: r["fc_sum"] or 0, default=None)
    now_ = "호우특보 없음 · 기준에 닿은 곳 없음 · " + (f"앞으로 6시간 가장 많은 곳 {top['sigun']} {top['fc_sum']:g}㎜" if top and top["fc_sum"] else "앞으로 6시간 비 예보 거의 없음")
    return {**_hdr(o, sigun, f"{title} — 지금은 해당 없음"),
            "sections": [{"h": "지금", "items": [now_]}, {"h": "이렇게 되면 필요하다", "items": when},
                         {"h": "참고 — 위키 · 책자", "items": _refs(refs)}]}


# ── 판례로 본 점검(⚠️) — 위키 [[판례 업무별 적용]] · 판례 쪽. 작성자 해석이며 판시가 아니다([[판례 인용규칙]]) ──
def _pan(num: int) -> dict | None:
    stem = next((k for k in _index() if k.startswith(f"판례 {num:02d} ")), None)
    if not stem:
        return None
    t = _index()[stem].read_text("utf-8")
    fm = t.split("---", 2)[1] if t.startswith("---") else ""
    g = lambda k: (m.group(1).strip().strip('"') if (m := re.search(rf"^{k}:\s*(.+)$", fm, re.M)) else "")  # noqa: E731
    app = ""
    if "## 도·시군 등 업무 적용" in t:
        app = t.split("## 도·시군 등 업무 적용", 1)[1].split("\n", 1)[1].strip().split("\n\n", 1)[0].replace("\n", " ")
    summ = g("summary").split(" — ", 1)[-1]
    return {"stem": stem, "court": g("court"), "date": g("decision_date"), "no": g("case_number"), "type": g("legal_type"),
            "status": g("status"), "grade": g("evidence_grade"), "summary": summ, "apply": app}


def _record_items(*labels: str) -> list[str]:
    """[[판례 업무별 적용]] '권장 기록 항목' 중 그 이름으로 시작하는 줄."""
    p_ = _index().get("판례 업무별 적용")
    if not p_:
        return []
    sec = p_.read_text("utf-8").split("## 권장 기록 항목", 1)[-1]
    return [ln.lstrip("- ").strip() for ln in sec.splitlines() if ln.startswith("- ") and any(ln.lstrip("- ").startswith(x) for x in labels)]


def _judicial(nums: list[int], record: tuple[str, ...], why: str) -> dict | None:
    """⚠️ 판례로 본 점검 — 지금 상황(why)에서 예전에 책임이 문제된 조치와, 그래서 남겨 둘 기록. 비가 없을 때는 쓰지 않는다."""
    items = [f"⚠️ {why} — 아래는 판례를 바탕으로 한 업무 점검 해석이다(판시 아님). 책임은 사무분장 · 관리청 · 정보를 안 시점 · 조치 가능성에 따라 다르다 ([[판례 인용규칙]])"]
    for n in nums:
        c = _pan(n)
        if c:
            items.append(f"⚠️ [[{c['stem']}]] — {c['court']} {c['date']} {c['no']}({c['type']} · {c['status']} · 근거 {c['grade']}): {c['summary']}"
                         + (f" ▶ 점검: {c['apply'][:230]}" if c["apply"] else ""))
    rec = _record_items(*record)
    if rec:
        items.append("⚠️ 남겨 둘 기록 — " + " / ".join(rec[:3]) + " (하지 않은 조치를 나중에 문서로 보충하지 않는다)")
    return {"h": "⚠️ 판례로 본 점검", "items": items} if len(items) > 1 else None


def _table(page_name: str, heading: str) -> list[list[str]]:
    """위키 페이지의 '## 제목' 아래 표 줄(머리줄 · 구분선 뺀 것)."""
    p_ = _index().get(page_name)
    if not p_:
        return []
    sec = p_.read_text("utf-8").split(f"## {heading}", 1)
    if len(sec) < 2:
        return []
    out = []
    for ln in sec[1].split("\n## ", 1)[0].splitlines():
        c = [x.strip().replace("**", "") for x in ln.strip().strip("|").split("|")]
        if ln.startswith("|") and len(c) >= 2 and not set(c[0]) <= set("-: ") and c[0] not in ("단계", "반", "기관"):
            out.append(c)
    return out


MEETING = {"초기대응": ("예비 상황판단회의", "자연재난과장"), "비상 1단계": ("초기 상황판단회의", "자연재난과장"),
           "비상 2단계": ("본 상황판단회의", "도민안전본부장")}


def _m_meeting(base, sigun):
    o, sits = _scope(base, sigun)
    st = (o["stage"] or {}).get("stage")
    name, chair = MEETING.get(st, ("상황판단회의(필요 시)", "본부장이 정한 사람"))
    rows = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    wx = [f"특보: " + (" · ".join(f"{g['name']} {len(g['siguns'])}개 시군" for g in o["groups"] if g["name"].startswith("호우")) or "호우특보 없음")
          + (" (산출 · 가상)" if o["computed"] else "")]
    wx += [f"{r['sigun']} — 시간당 최대 {r['r1']:g}㎜{'(' + r['emd1'] + ')' if r['r1'] else ''} · 3시간 {r['r3']:g}㎜ · 24시간 {r['r24']:g}㎜"
           + (f" · 앞으로 6시간 {r['fc_sum']:g}㎜" if r["fc_sum"] else "") for r in sorted(rows, key=lambda x: -x["r24"])[:6]]
    if o["night"]:
        wx.append("야간 · 취약시간대(21~06시) — 일몰 전 사전대피 원칙을 이미 넘겼다")
    hit = _hits(sits, ("긴급대피", "사전대피"), ("met",))
    dis = [f"대피 기준 해당 {len({(a, b['emd']) for a, b, _, _ in hit})}개 읍면동: " + _few([f"{a} {b['emd']} {f} {c['stage']}" for a, b, f, c in hit], 6)] if hit else ["대피 기준 해당 없음"]
    relay = [r["sigun"] for r in rows if r["relay"]]
    if relay:
        dis.append(f"상황전파 기준(시간당 20 · 일 100㎜) 시군 {len(relay)}곳: {_few(relay, 8)}")
    cbs = [r["sigun"] for r in rows if r["cbs"]]
    if cbs:
        dis.append("긴급재난문자 기준 해당 가능: " + _few(cbs, 8))
    risk_sg = list(dict.fromkeys(a for a, *_ in hit)) or [r["sigun"] for r in rows if r["relay"]][:5]
    decide = [f"비상근무 단계 — 지금 기준 {st or '상시대비'} → {name}(주재 {chair}) ([[상황판단회의]] · [[위기경보와 비상단계]])"]
    if risk_sg:
        decide.append("현장상황관리관 파견 시군 — " + _few(risk_sg, 6) + " ([[현장상황관리관]])")
    if hit:
        decide.append("도 → 시군 사전대피 권고 · 대피명령 요청 여부 ([[통제·대피 기준]] 실행 절차)")
    decide += ["대책본부 회의 개최 · 시군 지원(인력 · 장비 · 방재물자)",
               "학교 휴교 협의(교육청) — 등교 시간 전 호우 지속 예보면", "재난문자 · 재난방송 요청(통합지원본부장 → 지상파)"]
    if _calm(o, rows, bool(hit)):
        return _quiet(o, sigun, rows, "상황판단회의", [
            "예비 상황판단회의 · 초기대응 — 호우주의보 발표(3개 시군 이하) ([[위기경보와 비상단계]])",
            "초기 상황판단회의 · 비상 1단계 — 주의보 4개 시군 이상 또는 경보 2개 시군 이하",
            "본 상황판단회의 · 비상 2단계 — 호우경보 3개 시군 이상",
            "그 전이라도 상황전파 기준(시간당 20㎜ · 일 100㎜)에 닿는 곳이 생기면 이 화면이 자료를 펼친다"],
            ["상황판단회의", "위기경보와 비상단계"])
    jud = _judicial([18, 3, 19, 20], ("판단", "위험정보"), "상황판단회의 · 비상근무 단계에서")
    sec = [{"h": "1. 기상상황(현황 · 전망)", "items": wx}, {"h": "2. 재난상황", "items": dis},
           {"h": "3. 과거 재해이력 비교", "items": _analogs(o, risk_sg or [r["sigun"] for r in rows])
            + _uosim((risk_sg or [r["sigun"] for r in rows])[:6])
            + _history(risk_sg or [r["sigun"] for r in rows][:3], 4)
            + ["강우 ↔ 피해 사례 비교는 위키에 사례 페이지가 있는 시군만 된다(지금 " + _few([sg for c in _cases() for sg in c["rows"]], 6) + ")"]},
           {"h": "4. 논의 · 결정할 것", "items": decide},
           {"h": "5. 후속조치", "items": ["비상근무 실시 · 회의 결과 시군 · 관계기관 전파", "현장상황지원관 파견 · 현장 비상지원본부(현장CP) 전진배치 검토",
                                         "상황전파 통화 기록 · 대피 · 통제 현황 집계(세대 · 인원)"]},
           *([jud] if jud else []),
           {"h": "참고 — 위키 · 책자", "items": _refs(["상황판단회의", "위기경보와 비상단계", "판례 업무별 적용", "경남 시군별 우심피해 이력", "경남 자연재난 피해 통계 2015-2024",
                                                    "재해연보 읽는 법과 한계", "경남 자연재난 이력"] + [c["name"] for c in _cases()] + ["현장상황관리관"])}]
    return {**_hdr(o, sigun, f"{name} 자료"), "sections": sec}


def _m_dept(base, sigun):
    """비상단계별 어느 부서(반)가 무엇을 하나 — 위키 [[비상단계별 협업부서 임무]] 표를 지금 상황에 맞춰 보인다."""
    o, sits = _scope(base, sigun)
    st = (o["stage"] or {}).get("stage")
    rows = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    cmd = {c[0]: c[1] for c in _table("비상단계별 협업부서 임무", "단계별 지휘")}
    hit = _hits(sits, ("긴급대피", "사전대피"), ("met", "near"))
    if not st and _calm(o, rows, bool(hit)):
        return _quiet(o, sigun, rows, "단계별 부서 임무", [
            f"{k} — {v[:150]}" for k, v in cmd.items()] + ["주의보가 나면(초기대응) 이 화면이 지금 단계에서 일하는 반 · 부서와 먼저 부를 협업기관을 보여 준다"],
            ["비상단계별 협업부서 임무", "위기경보와 비상단계"])
    bans = _table("비상단계별 협업부서 임무", "비상1~3단계 임무반")
    kinds = {c[0]: c for c in bans}
    why: dict[str, str] = {}
    fams = {f for _, _, f, _ in hit}
    if hit:
        for k in kinds:
            if any(w in k for w in ("긴급 생활안정", "사회질서", "수습구조")):
                why[k] = "대피 기준 해당 · 가까움 — 취약계층 대피 · 출입통제 · 강제대피 협조"
    if fams & {"하천", "지하공간", "침수·해안"} or any(a.startswith("호우") for r in rows for a in r["alerts"]):
        for k in kinds:
            if any(w in k for w in ("시설응급복구", "교통대책")):
                why[k] = "지하차도 · 하천 · 도로 통제 대상 — 시설 응급조치 · 우회"
    if any(r["cbs"] or r["relay"] for r in rows):
        for k in kinds:
            if "홍보" in k:
                why[k] = "상황전파 · 재난문자 기준 — 주민 행동요령 홍보"
    first = [k for k in kinds if "상황관리 총괄" in k]
    rel = [k for k in kinds if k in why and k not in first]
    rest = [k for k in kinds if k not in first and k not in rel]
    sec = [{"h": "지금 단계", "items": [f"{st or '초기대응 이전(주의보 없음)'} — " + (cmd.get("초기대응", "") if st == "초기대응" else cmd.get("비상1~3단계", ""))[:200]]}]
    if st and st != "초기대응":
        sec.append({"h": "일을 맡는 반 — 지금 상황에 맞는 것 먼저", "items": [f"{k}: {kinds[k][1]} — {kinds[k][2][:170]}" for k in first]
                    + [f"{k}: {kinds[k][1]} — {kinds[k][2][:150]}  ◀ {why[k]}" for k in rel]
                    + (["그 밖의 반: " + " · ".join(re.sub(r"^[①-⑬]\s*", "", k) for k in rest)] if rest else [])})
    co = {c[0]: c[1] for c in _table("비상단계별 협업부서 임무", "협업기관")}
    pick = ["창원기상대", "경상남도경찰청", "한국전력공사", "제39보병사단"] + (["한국농어촌공사", "한국수자원공사"] if "하천" in fams else [])
    firm = [f"{k}: {v[:140]}" for k in co for v in [co[k]] if any(k.startswith(x[:6]) or x in k for x in pick)]
    sec.append({"h": "협업기관 — 먼저 연락할 곳", "items": firm[:6] or ["위키 표를 읽지 못했다"]})
    nxt = {"초기대응": "호우주의보 4개 시군 이상 또는 호우경보 발표 → 비상 1단계(초기 상황판단회의)",
           "비상 1단계": "호우경보 3개 시군 이상 → 비상 2단계(본 상황판단회의)", "비상 2단계": "더 오르는 단계는 없다 — 대책본부 운영 · 중앙 보고"}.get(st or "", "호우주의보 발표 → 초기대응")
    sec.append({"h": "다음 단계", "items": [nxt]})
    sec.append({"h": "참고 — 위키 · 책자", "items": _refs(["비상단계별 협업부서 임무", "상황근무체계", "재난안전대책본부 조직", "실국별 행동매뉴얼", "시군 상황관리반 행동매뉴얼"])})
    return {**_hdr(o, sigun, "단계별 부서 임무"), "sections": sec}


def _m_evac(base, sigun):
    o, sits = _scope(base, sigun)
    emerg = _hits(sits, ("긴급대피",), ("met",))
    pre = _hits(sits, ("사전대피",), ("met", "near"))
    rows0 = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    if _calm(o, rows0, bool(emerg or pre)):
        return _quiet(o, sigun, rows0, "대피 판단", [
            "산사태 · 하천 · 지하공간 · 침수 — 읍면동마다 위키 우려지역 기준에 닿거나 가까워지면(70% 이상) 이 화면이 대상 지구와 대피장소를 펼친다",
            "사전대피는 예보, 긴급대피는 실황이 기준 — 시군을 고르면 그 시군 읍면동까지 본다 ([[통제·대피 기준]])",
            "야간(21~06시) 전에 비가 예상되면 일몰 전 사전대피를 먼저 본다"],
            ["통제·대피 기준", "대피명령 길라잡이"])
    sec = []
    sec.append({"h": "긴급대피 기준 — 실황으로 해당", "items": [f"{a} {b['emd']} {f}: {c['rule']}" for a, b, f, c in emerg][:12] or ["없음"]})
    sec.append({"h": "사전대피 기준 — 예보로 해당 · 가까움", "items": [f"{a} {b['emd']} {f}: {c['rule']} ({STL[c['st']]})" for a, b, f, c in pre][:12] or ["없음"]})
    tgt = []
    for a, b, f, c in emerg + pre:
        sb = _sites_by(a)
        for x in sb.get(b["emd"], []):
            if ai.FAMILY_OF.get(x["유형"]) == f:
                tgt.append(f"{a} {b['emd']} — {x['유형']} {_site_name(x)}({x['리']}{', ' + x['인원'] + '명' if x['인원'] not in ('', '-') else ''}) → {x['대피장소'] or '대피장소 미기재'}")
    sec.append({"h": "대상 지구 · 대피장소 (위키 우려지역)", "items": list(dict.fromkeys(tgt))[:20] or ["해당 지구 없음"]})
    sec.append({"h": "판단 · 절차", "items": [
        "사전대피 권고 = 행정지도(강제 · 과태료 없음) · 대피명령 = 행정처분(강제대피 · 200만원 이하 과태료) — [[대피명령 길라잡이]]",
        "발령권자: 시장 · 군수 · 구청장(대책본부장) — 긴급하면 읍면동장이 주민대피명령 (재난안전법 제40조)",
        "취약계층 먼저 · 일몰 전 사전대피 원칙" + (" — 지금 야간: 대피로 · 이동 수단 안전 먼저 확인" if o["night"] else ""),
        "사전대피는 예보, 긴급대피는 실황이 기준 — 지구별 원문 기준은 [[시군별 통제·대피계획]]"]})
    jud = _judicial([1, 3, 22], ("위험정보", "대피"), "대피 판단 · 경보 전파에서")
    if jud:
        sec.append(jud)
    sec.append({"h": "확인할 것", "items": [_ante_note(sits) + " (사전대피 첫 조건: 산림청 예측정보)",
                                         "원문 기준의 '그리고/또는' · 붙은 조건은 판정하지 않았다"]})
    sec.append({"h": "참고 — 위키 · 책자", "items": _refs(["대피명령 길라잡이", "통제·대피 기준", "시군별 통제·대피계획", "주민대피관리계획", "판례 업무별 적용"])})
    return {**_hdr(o, sigun, "대피 판단"), "sections": sec}


def _m_control(base, sigun):
    o, sits = _scope(base, sigun)
    rows = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    if _calm(o, rows):
        return _quiet(o, sigun, rows, "통제(지하차도 · 하천)", [
            "지하차도 · 지하공간 — 호우특보가 나면 통제 기준에 해당(침수심 5㎝ 이상이면 통제)",
            "지하공간 15분 강우 14㎜ 이상이면 눈여겨보고, 20㎜ 사전대피 · 30㎜(+ 시간당 55㎜) 긴급대피 기준 ([[통제·대피 기준]])",
            "하천 — 시간당 30㎜ 이상이 3시간 지속된다는 예보 · 홍수주의보면 통제"],
            ["통제·대피 기준", "인명피해 우려지역"])
    under, river = [], []
    for r in rows:
        sb = _sites_by(r["sigun"])
        on = "호우특보 발령 — 통제 기준 해당" if any(a.startswith("호우") for a in r["alerts"]) else "특보 없음"
        for e, xs in sb.items():
            for x in xs:
                fam = ai.FAMILY_OF.get(x["유형"])
                if fam == "지하공간" and (r["alerts"] or sigun):
                    under.append(f"{r['sigun']} {e} — {x['유형']} {_site_name(x)}({x['리']}) · {on}")
                elif fam == "하천" and (r["alerts"] or r["relay"] or sigun):
                    river.append(f"{r['sigun']} {e} — {x['유형']} {_site_name(x)}({x['리']})")
    hot15 = []
    for s_ in sits:
        for e in s_["emd"]:
            if (e["m15"] or 0) >= 14 and e["risk"].get("지하공간"):
                hot15.append(f"{s_['sigun']} {e['emd']} — 15분 {e['m15']:g}㎜ · 시간당 {e['rain']['1h']:g}㎜ (지하공간 사전대피 15분 20 · 긴급 15분 30 + 시간당 55㎜)")
    rv = _hits(sits, ("통제", "사전대피", "긴급대피"), ("met", "near"))
    rv = [f"{a} {b['emd']} 하천 {c['stage']}: {c['rule']} ({STL[c['st']]})" for a, b, f, c in rv if f == "하천"]
    sec = [{"h": "지하차도 · 지하공간", "items": under[:20] or ["특보 시군에 지하공간 우려지역 없음"]},
           {"h": "지하공간 15분 강우 높은 곳", "items": hot15[:10] or ["15분 14㎜ 넘은 지하공간 읍면동 없음"]},
           {"h": "하천변 산책로 · 둔치주차장 · 세천 · 소교량", "items": river[:20] or ["대상 없음"]},
           {"h": "하천 기준 대조", "items": rv[:10] or ["하천 통제 · 대피 기준에 닿은 곳 없음(30㎜/h 3시간 지속 예보 · 누적 200㎜ + 30㎜/h)"]},
           {"h": "기준 · 유의", "items": ["지하차도: 호우특보 발령 · 침수심 5㎝ 이상이면 통제. 4인 담당자(공무원 2 · 민간 1 · 경찰 1) — [[통제·대피 기준]]",
                                         "하천: 30㎜/h 이상 3시간 지속 예보 · 홍수주의보면 통제", "하천 수위 · 침수심 · CCTV 는 대시보드에 없다 — 시군 · 홍수통제소 확인"]},
           *([j] if (j := _judicial([18, 4, 6, 11], ("대피", "시설"), "지하차도 · 하천 · 도로 통제에서")) else []),
           {"h": "참고 — 위키 · 책자", "items": _refs(["통제·대피 기준", "인명피해 우려지역", "도로 침수 낙석 사면붕괴 확인사항", "판례 업무별 적용"])}]
    return {**_hdr(o, sigun, "통제(지하차도 · 하천)"), "sections": sec}


def _m_msg(base, sigun):
    o, sits = _scope(base, sigun)
    rows = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    cbs = [f"{r['sigun']} — 시간당 {r['r1']:g}㎜ · 3시간 {r['r3']:g}㎜" for r in rows if r["cbs"]]
    if _calm(o, rows, bool(_hits(sits, ("긴급대피", "사전대피"), ("met", "near")))):
        return _quiet(o, sigun, rows, "재난문자", [
            "긴급재난문자 기준 — 시간당 50㎜ + 3시간 90㎜, 또는 시간당 72㎜ (기상청 송출)",
            "호우특보 · 대피 기준 해당 · 상황전파 기준에 닿으면 상황에 맞는 표준문안(90자)을 이 화면이 골라 보여 준다"],
            ["재난문자 송출기준", "재난문자 표준문안"])
    tbl = {}
    for a, b in _rows("재난문자 표준문안"):
        tbl.setdefault(a.replace("**", "").strip(), b)
    want = []
    if any(r["alerts"] for r in rows):
        want += [g for g in ("호우경보", "호우주의보") if any(g in r["alerts"] for r in rows)][:1]
    if _hits(sits, ("긴급대피",), ("met",)):
        want.append("대피명령 발령")
    if _hits(sits, ("사전대피",), ("met", "near")) or _hits(sits, ("긴급대피",), ("met",)):
        want.append("사전대피권고")
    if any(e["risk"].get("산사태") and e["relay"] for s_ in sits for e in s_["emd"]):
        want += ["대응1", "산사태 사전대비2"]
    if any(e["risk"].get("지하공간") and e["relay"] for s_ in sits for e in s_["emd"]):
        want += ["침수1", "지하1"]
    want = list(dict.fromkeys(want)) or ["사전대비1"]
    sec = [{"h": "긴급재난문자 기준(1시간 50 + 3시간 90 · 또는 1시간 72㎜) — 기상청 송출", "items": cbs or ["해당 없음"]},
           {"h": "상황에 맞는 표준문안 (90자 · ○○ 채우기)", "items": [f"{k}: {tbl[k]}" for k in want if k in tbl] or ["위키 문안을 못 읽었다"]},
           {"h": "송출 · 유의", "items": ["대피 정보는 긴급재난문자 + 민방위 경보(사이렌) + 마을방송 + 현장 전파를 동시에 — [[통제·대피 기준]]",
                                         "대피 지역 주변 주민에게도 알려 유입을 막는다 — [[대피명령 길라잡이]]"]},
           {"h": "참고 — 위키 · 책자", "items": _refs(["재난문자 송출기준", "재난문자 표준문안", "대피명령 길라잡이"])}]
    return {**_hdr(o, sigun, "재난문자"), "sections": sec}


def _m_brief(base, sigun):
    o, sits = _scope(base, sigun)
    rows = o["rows"] if not sigun else [r for r in o["rows"] if r["sigun"] == sigun]
    t = _when(o["tm"])
    head = [f"{t} 현재 · 특보 " + (" · ".join(f"{g['name']} {len(g['siguns'])}개 시군({'·'.join(g['siguns'])})" for g in o["groups"] if g["name"].startswith("호우")) or "없음")
            + (" (산출 · 가상)" if o["computed"] else ""),
            "도 비상단계 기준: " + ((o["stage"] or {}).get("stage") or "상시대비")]
    rain = [f"{r['sigun']}: 시간당 {r['r1']:g} · 3시간 {r['r3']:g} · 24시간 {r['r24']:g}㎜ (다우 {r['emd3'] or r['emd1']})"
            for r in sorted(rows, key=lambda x: -x["r24"]) if r["r24"] or r["r1"]]
    hit = _hits(sits, ("긴급대피", "사전대피", "통제"), ("met",))
    act = [_few([f"{a} {b['emd']} {f} {c['stage']}" for a, b, f, c in hit], 8) + " — 기준 해당"] if hit else ["기준 해당 없음"]
    act.append("상황전파 시군: " + (_few([r["sigun"] for r in rows if r["relay"]], 10) or "없음"))
    fc = sorted([r for r in rows if r["fc_sum"]], key=lambda x: -x["fc_sum"])[:5]
    sec = [{"h": "1. 개요", "items": head},
           {"h": "2. 시군별 강우(읍면동 최대 칸 · 격자 500m)", "items": rain or ["비 없음"]},
           {"h": "3. 기준 해당 · 조치", "items": act},
           {"h": "4. 전망(초단기 앞으로 6시간)", "items": [f"{r['sigun']} {r['fc_emd']} {r['fc_sum']:g}㎜(최대 시간당 {r['fc_peak']:g}㎜)" for r in fc] or ["비 예보 거의 없음"]},
           {"h": "서식", "items": ["표준 업무보고 1 · 2(기상상황 및 강우예상 · 호우 대처상황) 구성 — 18개 시군 강우량 · 다우지점 · 특보 · 레이더 ([[표준 문서 목록]])",
                                 "다우지점은 관측소가 아니라 격자 최대 칸 읍면동이다 — 보고서에는 관측소 값(AWS)을 쓴다"]},
           {"h": "참고 — 위키 · 책자", "items": _refs(["표준 문서 목록", "위기경보와 비상단계"])}]
    return {**_hdr(o, sigun, "상황보고"), "sections": sec}


def reset_cache() -> None:
    """위키 폴더를 바꿨을 때 — 위키에서 읽어 둔 것을 다 비운다."""
    _TTL.clear()
    _index.cache_clear()
    page.cache_clear()
    _cases.cache_clear()
