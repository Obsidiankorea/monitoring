"""상황판단회의 — 특보 시군 기준 자료 셋(보고서 창 · jaenan meeting 작업의 본문 '특보지역현황' · '과거사례' · '조위현황').

  · 특보 시군 = 지금 발효 중인 특보(+ 예비특보)가 걸린 시군 — 지도의 특보 자료(queries.alerts). 풍수해 · 겨울 종류만(건조 · 황사 등은 뺀다).
  · 줄은 jaenan 의 Ⅱ장 문구와 같은 꼴 [{text, subs}] — '**…**' 굵게, '※ …' 로 시작하는 줄은 끝의 출처 · 기준 시각(작게, 글머리 없이).
  · 우려지역: 위키 인명피해 우려지역(지구 · 유형) + 지형 표(지구 둘레 건물 · 오래된 약한 구조) + 상황판단 판정 캐시(있을 때만 — 새로 세지 않는다).
    ⚠️ 담당자 이름 · 연락처는 쓰지 않는다(contacts.districts 는 위키 공개 자료만 준다 — of_sigun 은 부르지 않는다).
  · 과거 사례: 위키 data/경남 풍수해 사건×시군 피해.csv + 경남 풍수해 사건 이력.csv — A 등급(경남도 복구계획, 2016~) 사건만,
    재난 종류가 맞는 사건 먼저 · 피해액 큰 것 둘([[과거 사례 찾는 법 (상황판단회의)]]의 규칙).
  · 조위: tide.status() — 태풍 · 풍랑 · 호우 특보가 있거나 특보 시군에 해안 시군이 있을 때만.
"""
from __future__ import annotations

import csv
from datetime import datetime

from . import ai, contacts, judge, queries, terrain, tide

KINDS = ("호우", "태풍", "강풍", "풍랑", "대설", "한파", "폭염")
NO_ALERT = [{"text": "발효 중인 특보 없음", "subs": []}]


def alert_siguns() -> tuple[list[str], list[str], str | None]:
    """(특보 시군 — 경남 차례, 걸린 특보 이름, 특보 자료 시각). 예비특보(pending)의 시군도 넣는다(회의 기간 안에 발효)."""
    a = queries.alerts()
    d = a.get("data") or {}
    names, sgs = [], set()
    for g in d.get("groups") or []:
        if any(k in (g.get("name") or "") for k in KINDS):
            names.append(g["name"])
            sgs.update(g.get("siguns") or [])
    for p in d.get("pending") or []:
        if any(k in (p.get("name") or "") for k in KINDS):
            names.append(f"{p['name']} 예비")
            if p.get("sigun"):
                sgs.add(p["sigun"])
    return [s for s in ai.SIGUN_FULL if s in sgs], list(dict.fromkeys(names)), a.get("fetched_at") or a.get("base_time")


def _judged() -> tuple[list[dict], str | None]:
    """상황판단 판정 캐시(경남 전체, 가장 최근) — 없으면 ([], None). 오래 걸리니 새로 세지 않는다."""
    hits = [v for k, v in list(judge._BC.items()) if k[0] == "all"]
    if not hits:
        return [], None
    t, v = max(hits, key=lambda x: x[0])
    return v.get("rows") or [], v.get("computed_at")


def district_lines(sgs: list[str]) -> tuple[list[dict], list[dict]]:
    """특보 시군마다 — 우려지구 수(유형별) · 지구 둘레 건물 · 판정 단계별 지구 수. (줄, 기준 시각들)"""
    if not sgs:
        return NO_ALERT, []
    rows, at = _judged()
    ter = terrain.table()
    out = []
    for sg in sgs:
        ds = [d for v in contacts.districts(sg)["emd"].values() for d in v]
        if not ds:
            out.append({"text": f"**{ai.SIGUN_FULL[sg]}** 우려지구 없음(위키 목록)", "subs": []})
            continue
        fam = {}
        for d in ds:
            fam[d["fam"]] = fam.get(d["fam"], 0) + 1
        sub = []
        tr = [ter.get("rows", {}).get(d["id"]) or {} for d in ds]
        b100, b300, bo = (sum(t.get(k) or 0 for t in tr) for k in ("b100", "b300", "bo"))
        if b300:
            sub.append(f"- 지구 둘레 건물 100m 안 {b100:,}동 · 300m 안 {b300:,}동 · 그중 오래된 약한 구조 {bo:,}동(지구끼리 겹쳐 센다)")
        if at:
            mine = [r for r in rows if r.get("sigun") == sg]
            n = {s: sum(1 for r in mine if ((r["b"].get("grid") or {}).get("st", {}).get(s) or {}).get("met")) for s in judge.STAGES}
            sub.append(f"- 지금 판정: 통제 필요 {n['통제']} · 사전대피 {n['사전대피']} · 긴급대피 {n['긴급대피']}곳(판정한 {len(mine)}곳 가운데)")
        out.append({"text": f"**{ai.SIGUN_FULL[sg]}** 우려지구 {len(ds)}곳 — " + " · ".join(f"{f} {fam[f]}" for f in ai.FAMILY if fam.get(f)),
                    "subs": sub})
    try:
        wd = datetime.fromtimestamp((ai.wiki() / "data" / "인명피해 우려지역.csv").stat().st_mtime).strftime("%Y.%m.%d.")
    except OSError:
        wd = "-"
    jt = at[11:16] if at else None
    out.append({"text": f"※ {'판정 ' + jt + ' 기준(지도 상황판단) · ' if jt else '판정 캐시 없음(상황판단 창을 열면 센다) · '}"
                        f"지구 자료 위키 {wd} · 건물 지형 표 {ter.get('built') or '-'}", "subs": []})
    basis = [{"name": "우려지역 판정(지도 상황판단)", "at": at.replace("T", " ")[:16]}] if at else []
    return out, basis


def _csv(name: str) -> list[dict]:
    try:
        with open(ai.wiki() / "data" / name, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _event_label(eid: str) -> str:
    """'20250716_호우' → '2025.7 호우'."""
    d, _, nm = eid.partition("_")
    return f"{d[:4]}.{int(d[4:6])} {nm}" if len(d) == 8 and d.isdigit() else eid


def past_lines(sgs: list[str], kinds: list[str]) -> list[dict]:
    """특보 시군마다 피해액 큰 A 등급 사건 1~2개 — 종류가 맞는 사건 먼저."""
    if not sgs:
        return NO_ALERT
    ev = {e["event_id"]: e for e in _csv("경남 풍수해 사건 이력.csv") if e.get("신뢰도") == "A"}
    dmg = _csv("경남 풍수해 사건×시군 피해.csv")
    out = []
    for sg in sgs:
        full = ai.SIGUN_FULL[sg]
        mine = [r for r in dmg if r.get("시군") == full and r.get("event_id") in ev and _num(r.get("총피해액_천원"))]
        match = lambda r: any(k in ev[r["event_id"]].get("재해유형", "") for k in kinds)   # noqa: E731
        mine.sort(key=lambda r: (not match(r), -_num(r["총피해액_천원"])))
        if not mine:
            out.append({"text": f"**{full}** — 복구계획(2016~)에 피해액이 적힌 사건 없음", "subs": []})
            continue

        def line(r):
            p = [f"{_event_label(r['event_id'])}: 피해 {_num(r['총피해액_천원']) / 1e5:,.1f}억"]
            if _num(r.get("max1h")):
                p.append(f"1시간 최대 {_num(r['max1h']):g}mm" + (f"({r['max1h_stn']})" if r.get("max1h_stn") else ""))
            if _num(r.get("max24h")):
                p.append(f"24시간 {_num(r['max24h']):g}mm")
            if _num(r.get("산사태복구건수")):
                p.append(f"산사태 복구 {_num(r['산사태복구건수']):g}건")
            if (r.get("특별재난지역여부") or "").startswith("Y"):
                p.append("특별재난지역")
            return " · ".join(p)
        out.append({"text": f"**{full}** — {line(mine[0])}", "subs": [f"- {line(r)}" for r in mine[1:2]]})
    try:
        wd = datetime.fromtimestamp((ai.wiki() / "data" / "경남 풍수해 사건×시군 피해.csv").stat().st_mtime).strftime("%Y.%m.%d.")
    except OSError:
        wd = "-"
    out.append({"text": f"※ 경남도 피해현황 및 복구계획(A 등급, 2016~ — 그 전은 시군 공식 피해액 없음) · 피해액은 그 해 명목가 · "
                        f"강우는 시군 안 AWS 지점 최대(시자료) · 위키 자료 {wd}", "subs": []})
    return out


def tide_lines(sgs: list[str], names: list[str]) -> tuple[list[dict] | None, list[dict]]:
    """태풍 · 풍랑 · 호우 특보가 있거나 특보 시군에 해안 시군이 있을 때만 — 지점마다 다음 만조. 아니면 (None, [])."""
    st = tide.status()
    rows = [r for r in st.get("rows") or [] if r.get("next")]
    coast = [r for r in rows if set(r.get("sigun") or []) & set(sgs)]
    if not rows or not (coast or any(k in n for n in names for k in ("태풍", "풍랑", "호우"))):
        return None, []
    use = coast or [r for r in rows if r.get("cuts")]
    hm = lambda t: f"{int(t[6:8])}일 {t[8:10]}:{t[10:12]}"   # noqa: E731

    def one(r):
        nx = r["next"]
        lv = f"({r['scale']} {r['names'][nx['stage']]})" if nx.get("stage") is not None and r.get("scale") else ""
        return f"{r['name']} {hm(nx['t'])} {nx['h']:g}cm{lv}"
    out = [{"text": "다음 만조 — " + " · ".join(one(r) for r in use), "subs": []}]
    wet = sorted({w for r in use for w in r.get("wet") or []})
    if wet:
        out.append({"text": "7일 안 만조가 지반고에 닿는 시설: " + ", ".join(wet), "subs": []})
    sp = tide._spring_text()
    if sp:
        out.append({"text": sp, "subs": []})
    t = max((r.get("t") or "" for r in use), default="")
    tt = f"{int(t[4:6])}.{int(t[6:8])}. {t[8:10]}:{t[10:12]}" if len(t) >= 12 else "-"
    out.append({"text": f"※ 국립해양조사원 조위 {tt} 관측 · 예측(단계는 고조정보 4단계, 폭풍해일 특보 기준과 다름)", "subs": []})
    return out, ([{"name": "조위(국립해양조사원)", "at": f"{tt} 관측"}] if len(t) >= 12 else [])


def extras(kinds: list[str], on: dict | None = None) -> tuple[dict, list[dict]]:
    """켠 묶음만 → (jaenan 본문에 더할 것, 화면 팝업에 보일 우리 자료 시각). on 은 {묶음: bool}(없으면 켬).
    조위는 해당 없으면 본문에 넣지 않는다(jaenan 이 소제목째 지운다)."""
    on = {k: (on or {}).get(k) is not False for k in ("특보지역현황", "과거사례", "조위현황")}
    sgs, names, at = alert_siguns()
    body, basis = {}, []
    if at:
        basis.append({"name": "특보 시군(지도 특보 자료)", "at": str(at)[:16] + (f" — {', '.join(names)}" if names else " — 해당 특보 없음")})
    if on["특보지역현황"]:
        body["특보지역현황"], b = district_lines(sgs)
        basis += b
    if on["과거사례"]:
        body["과거사례"] = past_lines(sgs, [k for k in kinds if k in KINDS] + [k for n in names for k in KINDS if k in n])
    if on["조위현황"]:
        t, b = tide_lines(sgs, names)
        if t is not None:
            body["조위현황"] = t
            basis += b
    return body, basis
