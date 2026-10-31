"""하천 수위 · 댐 · 보 — 경남에 영향을 주는 곳을 지도에 올린다(한강홍수통제소 OpenAPI, 전국 4대강 자료를 모아 준다).

10분마다 한 번(서버 한 곳) 수위 · 댐 · 보 전체 최신값과 홍수예보 발령을 받아, 경남에 있거나(수위 · 댐 · 보) 경남으로 흘러드는 낙동강 위쪽(댐 · 보)인 곳만 남긴다.
  · 수위 — 관측소 제원의 관심 · 주의보 · 경보 · 심각 수위와 견줘 단계를 낸다(제원이 있는 지점만. 없으면 값만).
  · 댐 · 보 — 수위 · 유입 · 총방류량. 방류가 느는지(1시간 전보다)만 짚는다 — 방류 판단 기준은 위키에 숫자가 없어 만들어 내지 않는다.
  · 홍수예보 발령(fldfct) — 우리 지점에 걸린 것만 가려낸다.
⚠️ 자료는 T/M 관측소 원시값(보정 전)이라 최종 확정치와 다를 수 있다 — 안전 판단은 홍수통제소 공식 발표로. 키는 config/api_keys.txt 의 HRFCO_KEY.
⚠️ 낙동강권역 자료는 한강보다 11분 이상 늦게 들어온다 — 지점마다 마지막 시각이 다르다(그 시각을 그대로 보인다).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import config, db
from .domain.gridproj import hr_xy

log = logging.getLogger("river")

BASE = "https://api.hrfco.go.kr"
INFO_FILE = config.STATE / "cache" / "river_info.json"
STAGES = ("정상", "관심", "주의보", "경보", "심각")        # 수위 단계 — 홍수통제소 제원의 이름 그대로
HIST_KEEP = 40                                             # 지점당 10분 값 40개(약 6시간)
STALE_MIN = 90                                             # 마지막 값이 이보다 오래되면 '지연'

_LIVE: dict = {"at": None, "err": None, "rows": [], "fld": [], "nfld": 0}
_HIST: dict[str, list[tuple[str, float]]] = {}             # 코드 → [(ymdhm, 수위·방류)] 오래된 것부터


def _key() -> str:
    return config.KEYS.get("HRFCO_KEY", "")


def _f(v) -> float | None:
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x


def _dms(s) -> float | None:
    """'128-33-04' → 128.551… (도-분-초)."""
    try:
        d, m, sec = (float(p) for p in str(s).strip().split("-"))
    except ValueError:
        return None
    return d + m / 60 + sec / 3600


def _sigun(addr: str, name: str) -> str | None:
    """'경상남도 합천군 야로면' → '합천'. 경남이 아니면 None."""
    p = (addr or "").split()
    if p[:1] == ["경상남도"] and len(p) > 1:
        return p[1].rstrip("시군")
    if "창녕" in name:                                      # 창녕·함안보처럼 주소가 비어 있는 곳
        return "창녕"
    return None


def pick(infos: dict[str, list[dict]]) -> list[dict]:
    """제원 목록에서 경남에 영향을 주는 곳만 — 수위: 경남 안 / 댐: 경남 안 + 낙동강 본류권역(코드 20…) 위쪽 / 보: 낙동강 본류(코드 2…, 하굿둑 뺌)."""
    out = []
    for r in infos.get("waterlevel", []):
        sg = _sigun(r.get("addr") or "", r.get("obsnm") or "")
        nm = r.get("obsnm") or ""
        if (r.get("addr") or "").startswith("경상남도") and not any(k in nm for k in ("댐", "방수로")):   # 댐 자리의 수위계는 댐 표식과 겹친다
            out.append(_st("wl", r["wlobscd"], r, sg, False))
    for r in infos.get("dam", []):
        code, ad = r["dmobscd"], r.get("addr") or ""
        if ad.startswith("경상남도"):
            out.append(_st("dam", code, r, _sigun(ad, r.get("obsnm") or ""), False))
        elif code.startswith("20"):                         # 낙동강 본류권역 — 경북 · 대구의 위쪽 댐(울산 · 동해로 가는 대곡 · 회야 · 감포는 코드가 다르다)
            out.append(_st("dam", code, r, None, True))
    for r in infos.get("bo", []):
        code = r["boobscd"]
        if code.startswith("20") and "하굿둑" not in r["obsnm"]:
            sg = _sigun(r.get("addr") or "", r.get("obsnm") or "")
            out.append(_st("bo", code, r, sg, sg is None))
    return [s for s in out if s["x"] is not None]


def _st(kind: str, code: str, r: dict, sigun: str | None, up: bool) -> dict:
    lon, lat = _dms(r.get("lon")), _dms(r.get("lat"))
    x, y = hr_xy(lon, lat) if lon and lat else (None, None)
    return {"id": code, "kind": kind, "name": r.get("obsnm", ""), "agency": r.get("agcnm", ""), "addr": ((r.get("addr") or "") + " " + (r.get("etcaddr") or "")).strip(),
            "sigun": sigun, "up": up, "lon": lon, "lat": lat, "x": x, "y": y,
            "thr": [_f(r.get(k)) for k in ("attwl", "wrnwl", "almwl", "srswl")] if kind == "wl" else None,
            "pfh": _f(r.get("pfh")), "lim": _f(r.get("fldlmtwl")) if kind == "dam" else _f(r.get("spcwl"))}


def stage(wl: float | None, thr: list[float | None]) -> tuple[int, float | None]:
    """수위 단계 0~4 와 다음 단계 수위(없으면 None). 제원에 수위가 비었거나 0 이면 단계를 내지 않는다(-1)."""
    if wl is None or not any(thr):                          # 제원 수위가 비었거나 0 이면 단계를 내지 않는다
        return -1, None
    s = 0
    for i, t in enumerate(thr):
        if t and wl >= t:
            s = i + 1
    nxt = next((t for t in thr[s:] if t), None)
    return s, nxt


def _at(hist: list[tuple[str, float]], ymdhm: str, minutes: int) -> float | None:
    """minutes 분 전(±12분) 값."""
    try:
        t = datetime.strptime(ymdhm, "%Y%m%d%H%M") - timedelta(minutes=minutes)
    except ValueError:
        return None
    best = None
    for k, v in hist:
        try:
            d = abs((datetime.strptime(k, "%Y%m%d%H%M") - t).total_seconds())
        except ValueError:
            continue
        if d <= 12 * 60 and (best is None or d < best[0]):
            best = (d, v)
    return best[1] if best else None


def _push(code: str, ymdhm: str, v: float | None) -> None:
    if v is None:
        return
    h = _HIST.setdefault(code, [])
    if not h or h[-1][0] < ymdhm:
        h.append((ymdhm, v))
        del h[:-HIST_KEEP]


def _rows(body) -> list[dict]:
    c = (body or {}).get("content") if isinstance(body, dict) else None
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []     # 목록에 null 이 끼어 오는 때가 있다


async def _get(cli: httpx.AsyncClient, path: str):
    r = await cli.get(f"{BASE}/{_key()}/{path}")
    r.raise_for_status()
    return r.json()


async def _infos(cli: httpx.AsyncClient) -> list[dict]:
    """제원은 거의 안 바뀐다 — 하루 한 번 받아 파일에 둔다."""
    try:
        d = json.loads(INFO_FILE.read_text("utf-8"))
        if datetime.fromisoformat(d["at"]) > datetime.now() - timedelta(hours=24) and d.get("stations"):
            return d["stations"]
    except (OSError, ValueError, KeyError):
        pass
    infos = {h: _rows(await _get(cli, f"{h}/info.json")) for h in ("waterlevel", "dam", "bo")}
    sts = pick(infos)
    try:
        INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
        INFO_FILE.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "stations": sts}, ensure_ascii=False), "utf-8")
    except OSError:
        pass
    return sts


async def refresh() -> dict:
    """한 번 훑는다 → 화면용 행 목록. 실패하면 이전 값을 그대로 두고 err 만 적는다."""
    if not _key():
        raise RuntimeError("HRFCO_KEY 없음 — 설정 › 시스템 › API 키")
    async with httpx.AsyncClient(timeout=30, verify=config.VERIFY_SSL) as cli:
        sts = await _infos(cli)
        live = {}
        for h, field in (("waterlevel", "wlobscd"), ("dam", "dmobscd"), ("bo", "boobscd")):
            for r in _rows(await _get(cli, f"{h}/list/10M.json")):
                live[r[field]] = r
        try:
            fld = _rows(await _get(cli, "fldfct/list.json"))
        except (httpx.HTTPError, ValueError):                # 발령이 없으면 990(자료 없음)이 온다
            fld = []
        for s in sts:                                         # 값이 쌓이는 만큼 추세를 낸다
            r = live.get(s["id"])
            if r:
                _push(s["id"], r["ymdhm"], _f(r.get("wl") if s["kind"] == "wl" else r.get("tototf")))
        # 이미 높은 곳은 3시간 전부터 한 번 더 받아 추세를 바로 낸다(방금 켠 서버도 1시간 변화를 보이게) — 지점당 한 번, 많아야 8곳
        warm = 0
        for s in sts:
            r = live.get(s["id"])
            if not r or s["kind"] != "wl" or len(_HIST.get(s["id"], [])) > 6 or warm >= 8:
                continue
            st, _ = stage(_f(r.get("wl")), s["thr"])
            if st >= 1 or _near(s, _f(r.get("wl"))):
                warm += 1
                end = datetime.strptime(r["ymdhm"], "%Y%m%d%H%M")
                try:
                    for h in reversed(_rows(await _get(cli, f"waterlevel/list/10M/{s['id']}/{(end - timedelta(hours=3)):%Y%m%d%H%M}/{end:%Y%m%d%H%M}.json"))):
                        _push(s["id"], h["ymdhm"], _f(h.get("wl")))
                except (httpx.HTTPError, ValueError):
                    pass
    rows = [_row(s, live.get(s["id"])) for s in sts]
    ids = {s["id"] for s in sts}
    names = {s["name"] for s in sts}
    mine = [{"kind": f.get("KIND") or f.get("kind"), "obs": f.get("OBSNM") or f.get("obsnm"), "river": f.get("RVRNM") or f.get("rvrnm"),
             "at": f.get("ANCDT") or f.get("ancdt"), "no": f.get("NO") or f.get("no"), "area": f.get("WRNARANM") or f.get("wrnaranm"),
             "cur": f.get("STTCURHGT") or f.get("sttcurhgt"), "eta": f.get("FCTDT") or f.get("fctdt")}
            for f in fld if _low(f).get("sttnm") in ids or _low(f).get("obsnm") in names or "낙동" in str(_low(f).get("rvrnm", ""))]
    _LIVE.update(at=datetime.now().isoformat(timespec="seconds"), err=None, rows=rows, fld=mine, nfld=len(fld))
    return _LIVE


def _low(d: dict) -> dict:
    return {k.lower(): v for k, v in d.items()}


def _near(s: dict, wl: float | None) -> bool:
    """다음 단계 수위의 70% 이상(값이 있는 곳만) — 켜자마자 추세를 채울 곳."""
    t = next((x for x in (s["thr"] or []) if x), None)
    return bool(wl is not None and t and wl >= 0.7 * t)


def _row(s: dict, r: dict | None) -> dict:
    """제원 + 최신값 → 화면용 한 줄."""
    o = {k: s[k] for k in ("id", "kind", "name", "agency", "addr", "sigun", "up", "x", "y", "pfh", "lim")}
    o["thr"] = s["thr"]
    if not r:
        return o | {"t": None, "v": None, "stage": -1}
    h = _HIST.get(s["id"], [])
    o["t"] = r["ymdhm"]
    o["stale"] = (datetime.now() - datetime.strptime(r["ymdhm"], "%Y%m%d%H%M")).total_seconds() > STALE_MIN * 60
    if s["kind"] == "wl":
        wl = _f(r.get("wl"))
        st, nxt = stage(wl, s["thr"])
        o |= {"v": wl, "q": _f(r.get("fw")), "stage": st, "next": nxt, "gap": round(nxt - wl, 2) if (wl is not None and nxt) else None}
        p = _at(h, r["ymdhm"], 60)
        o["d1h"] = round(wl - p, 2) if (wl is not None and p is not None) else None
        o["hist"] = [round(v, 2) for _, v in h[-37:]]
    else:                                                     # 댐 · 보 — 수위(swl) · 유입(inf) · 총방류(tototf)
        out = _f(r.get("tototf"))
        p = _at(h, r["ymdhm"], 60)
        o |= {"v": _f(r.get("swl")), "inf": _f(r.get("inf")), "out": out, "owl": _f(r.get("owl")), "stage": -1,
              "rise": bool(out is not None and p is not None and out - p >= 10 and out >= p * 1.2),
              "d1h": round(out - p, 1) if (out is not None and p is not None) else None,
              "hist": [round(v, 1) for _, v in h[-37:]]}
    return o


def status() -> dict:
    on = bool(_key())
    n = len([r for r in _LIVE["rows"] if r.get("stage", -1) >= 1])
    return {"on": on, "demo": config.DEMO, "at": _LIVE["at"], "err": _LIVE["err"], "rows": _LIVE["rows"], "fld": _LIVE["fld"],
            "nfld": _LIVE["nfld"], "high": n}


def summary() -> dict | None:
    """경남 전체 한 줄 — AI 보고 · 속보용. tone: 0 없음 · 1 관심 · 2 주의보 · 3 경보 이상. 자료가 없으면 None."""
    rows = _LIVE["rows"]
    wl = [s for s in rows if s["kind"] == "wl" and s.get("stage", -1) >= 0 and not s["up"] and "저수지" not in s["name"] and (s["thr"][0] or 0) < 30]
    if not wl:
        return None
    cnt = [sum(1 for s in wl if s["stage"] == i) for i in range(5)]
    hi = sorted((s for s in wl if s["stage"] >= 1), key=lambda s: (-s["stage"], s.get("gap") or 99))
    rise = [s for s in rows if s["kind"] != "wl" and s.get("rise")]
    t = f"하천 · 댐(홍수통제소 원시값): 기준 수위 있는 {len(wl)}곳 중 "
    if hi:
        t += "관심 수위 이상 " + ", ".join(f"{s['name']} {STAGES[s['stage']]}({s['v']:.2f}m)" for s in hi[:4]) + (f" 외 {len(hi) - 4}곳" if len(hi) > 4 else "")
    else:
        near = min((s for s in wl if s.get("gap") is not None), key=lambda s: s["gap"], default=None)
        t += "관심 수위 이상 없음" + (f"(가장 가까운 곳 {near['name']} {near['v']:.2f}m, 관심까지 {near['gap']}m)" if near else "")
    t += " · 방류 늘어난 댐·보: " + (", ".join(f"{s['name']} {s['out']:g}㎥/s{'(위쪽)' if s['up'] else ''}" for s in rise[:4]) or "없음")
    return {"text": t, "tone": max(s["stage"] for s in wl) if hi else 0, "n": len(hi), "cnt": cnt,
            "top": f"{hi[0]['name']} {STAGES[hi[0]['stage']]}" if hi else ""}


def _diff_alerts(rows: list[dict], state: dict) -> tuple[list[str], dict]:
    """새로 알릴 것 — 경남 수위 관측소가 주의보 수위 이상으로 오르거나 한 단계 더 오를 때 · 댐 · 보 방류가 늘기 시작할 때(한 번씩).
    관심 수위 밑으로 내려오면 다시 알릴 수 있게 지운다."""
    new, st = [], dict(state)
    for s in rows:
        k, n = s["id"], s["name"]
        if s["kind"] == "wl":
            if s["up"] or "저수지" in n or s.get("stage", -1) < 0:
                continue
            if s["stage"] >= 2 and s["stage"] > st.get(k, 0):
                new.append(f"{n} {STAGES[s['stage']]} 수위 도달 — {s['v']:.2f}m" + (f"(1시간 {s['d1h']:+g}m)" if s.get("d1h") else ""))
                st[k] = s["stage"]
            elif s["stage"] < 1:
                st.pop(k, None)
        elif s.get("rise"):
            if not st.get(k):
                new.append(f"{n} 방류 늘어남 — {s['out']:g}㎥/s(1시간 {s['d1h']:+g})" + (" · 낙동강 위쪽" if s["up"] else ""))
                st[k] = 1
        else:
            st.pop(k, None)
    return new, st


async def _notify() -> None:
    from . import aiwatch                                      # 순환 import 를 피해 부를 때 읽는다
    if not aiwatch.ready() or not aiwatch.cfg()["on"]:
        return
    new, st = _diff_alerts(_LIVE["rows"], db.get_setting("river_alert", {}) or {})
    if new:
        await aiwatch.send("🌊 하천 · 댐 (홍수통제소 원시값)\n" + "\n".join("· " + x for x in new) + "\n공식 판단은 홍수통제소 발표로.")
    db.put_setting("river_alert", st)                          # 보낸 뒤에 기억 — 보내다 실패하면 다음에 다시


async def run() -> None:
    """스케줄러가 10분마다 부른다 — 키가 없거나 시연 서버면 건너뛴다."""
    if config.DEMO or not _key():
        return
    try:
        await refresh()
    except Exception as e:                                    # noqa: BLE001
        _LIVE["err"] = str(e)[:160].replace(_key(), "***")
        log.warning("하천 수집 실패: %s", _LIVE["err"])
        return
    try:
        await _notify()
    except Exception as e:                                    # noqa: BLE001
        log.warning("하천 알림 실패: %s", str(e)[:100].replace(_key(), "***"))
