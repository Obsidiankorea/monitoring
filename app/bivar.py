"""두 변수 판단 — 지도 색 = 이번 비 누적 × 최근 1시간, 빗금 = 앞으로 6시간 가장 센 시우량.

시각(정시)마다 경남 500m 칸을 9색(누적 3단 × 1시간 3단)과 빗금 4단(없음 · 성김 · 촘촘 · 지그재그)으로 나누고,
시군마다 최대값으로 판단 단계(평온 ~ 비상)를 매긴다. 화면(07e-bivar.js)은 시각마다 그림 · 시군 줄 · 칸 수를 받아
지도 · 시간표 · 판단표를 그리고, 마우스 설명은 1시간 격자(0.5㎜ 단위 PNG)로 12 · 24 · 3시간 합을 스스로 더한다.

실황: 누적 구간(강수 누적 카드와 같은 것)의 정시 60분 격자 + 가장 최근 초단기예보 +1 ~ +6(5km → 500m).
      '앞으로 6시간'은 지난 시각이면 그 뒤 실제로 내린 비(사후 검토), 지금 · 예보 시각이면 초단기예보.
      ⚠️ 지난 시각의 그때 예보는 남아 있지 않다(초단기는 발표 셋만 보관) — 지난 칸 빗금은 '실제로 온 비'다.
사례: data/demo/map/<slug> 의 시각 전부(예보 없음 — 앞으로는 실제로 온 비).
끊는 값은 위키 판정값(ai.rules) — 누적 100 · 200, 1시간 20 · 50, 앞 6시간 20 · 30 · 50.
"""
from __future__ import annotations

import base64
import csv
import io
from datetime import datetime

import numpy as np
from PIL import Image

from . import ai, clock, gridcase, gridstore, gridview

PAL = [["#3a414b", "#8c3f63", "#ff4f8b"],
       ["#2f6c8c", "#7b5aa6", "#c4479e"],
       ["#36b3e6", "#8f86f5", "#f05bff"]]
NAMES = [["평온", "비 시작", "갑자기 쏟아짐"], ["조금 옴 · 그침", "꾸준히 옴", "많이 오는 중"],
         ["많이 왔고 그침", "많이 왔고 계속", "많이 왔고 쏟아짐"]]
RGB = np.array([[tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in r] for r in PAL], np.uint8)
_CACHE: dict[tuple, dict] = {}


def _cuts() -> tuple[dict, tuple, tuple, tuple]:
    """판정값 {항목: {v, doc, src}} 와 세 축의 끊는 값. 근거 문서 · 원문은 위키 CSV 에서(없으면 빈칸)."""
    v = ai.rules()["v"]
    doc: dict[str, tuple[str, str]] = {}
    try:
        with open(ai.wiki() / ai.RULES_CSV, encoding="utf-8-sig", newline="") as f:
            doc = {r["항목"]: (r.get("근거 문서") or "", r.get("원문") or "") for r in csv.DictReader(f)}
    except (OSError, csv.Error, KeyError, UnicodeDecodeError):
        pass
    V = {k: {"v": x, "doc": doc.get(k, ("판정값", ""))[0] or "판정값", "src": doc.get(k, ("", ""))[1]} for k, x in v.items()}
    return (V, (v["상황전파_일"], v["하천_사전대피_누적"]), (v["상황전파_1시간"], v["긴급재난문자_1시간"]),
            (v["상황전파_1시간"], v["하천_사전대피_예보시우량"], v["산사태_사전대피_예보시우량"]))


def _cls(v: np.ndarray, cut) -> np.ndarray:
    return np.where(np.isfinite(v), sum((v >= c).astype(int) for c in cut), -1)


def _png(img: np.ndarray, mode: str | None = None) -> str:
    b = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(img[::-1]), mode).save(b, "PNG", compress_level=6)   # 행 남→북 → 그림은 위가 북
    return base64.b64encode(b.getvalue()).decode()


def _live(now: datetime) -> tuple[list[str], list[np.ndarray], int, dict]:
    hours, since = gridview.acc_window()
    want, have = gridview._acc_keys(hours, since, now, False)
    H = [gridstore.load("obs60", k) if k in have else None for k in want]
    if not any(h is not None for h in H):
        raise LookupError("이 구간에 받은 정시 격자가 없다")
    shp = next(h for h in H if h is not None).shape
    H = [h if h is not None else np.full(shp, np.nan) for h in H]
    tms, last = list(want), want[-1]
    tmfc, tmefs = gridview.vsrt_run()
    fc = [e for e in tmefs if e.ljust(12, "0") > last][:6] if tmfc else []
    for e in fc:
        a = gridstore.load("vsrt", f"{tmfc}_{e}")
        if a is None:
            break
        H.append(np.where(np.isfinite(h5 := gridstore.to_hr(a)), h5, 0.0))
        tms.append(e.ljust(12, "0"))
    return tms, H, len(want) - 1, {"live": True, "tmfc": tmfc, "missing": len(want) - len(have),
                                    "title": f"{_md(want[0])}부터"}


def _md(t: str) -> str:
    return f"{int(t[4:6])}. {int(t[6:8])}. {t[8:10]}시"


def _case(slug: str) -> tuple[list[str], list[np.ndarray], int, dict]:
    m = gridcase.meta(slug)
    F = m["frames"]
    H = [np.array(gridcase.obs(slug, t), float) for t in F]
    i = F.index(m["peak"]) if m.get("peak") in F else len(F) - 1
    return list(F), H, i, {"live": False, "title": m["title"], "peak": m.get("peak")}


def build(case: str | None = None, now: datetime | None = None) -> dict:
    """화면 자료 — {frames: [{tm, fc, now(png), mask(png), h1(png), c3, rows, left}], now_i, 끊는 값, 판정값, 읍면동 그림 …}."""
    now = now or clock.now()
    tms, H, now_i, info = _case(case) if case else _live(now)
    V, ACC, H1, FUT = _cuts()
    ck = (case, tuple(tms), info.get("tmfc"), tuple(ACC), tuple(H1), tuple(FUT))
    if ck in _CACHE:
        return _CACHE[ck]
    msig, memd = gridstore.masks()
    geo = gridstore.geo()
    sig = {s["id"]: s["name"] for s in geo["sigun"] if s.get("kind") == "gn"}
    gn = np.isin(msig, list(sig))
    edge = np.zeros_like(gn)
    edge[1:] |= msig[1:] != msig[:-1]
    edge[:, 1:] |= msig[:, 1:] != msig[:, :-1]
    edge &= gn
    cells = {sid: np.flatnonzero(msig == sid) for sid in sig}
    Z = [np.nan_to_num(h) for h in H]
    acc = np.zeros(msig.shape)
    out = []
    n = len(tms)
    for i, tm in enumerate(tms):
        acc = acc + Z[i]
        a = np.where(np.isfinite(H[i]), acc, np.nan)
        h = H[i]
        fm = np.max(Z[i + 1:i + 7], axis=0) if i + 1 < n else np.zeros(msig.shape)
        ca, ch, cf = _cls(a, ACC), _cls(h, H1), _cls(fm, FUT)
        ok = gn & (ca >= 0) & (ch >= 0)
        img = np.zeros(msig.shape + (4,), np.uint8)
        img[ok, :3] = RGB[ca[ok], ch[ok]]
        img[ok, 3] = 255
        img[gn & ~ok] = (90, 90, 90, 255)
        img[edge] = (20, 22, 26, 255)
        mk = np.zeros(msig.shape + (3,), np.uint8)
        mk[..., 0] = np.where(ok, cf * 80, 0)
        key = np.where(ok, ca * 12 + ch * 4 + cf, -1).ravel()
        cnt = np.bincount(key[key >= 0], minlength=36)
        c3 = cnt.reshape(3, 3, 4).tolist()
        rows = []
        af, hf, ff, okf = a.ravel(), h.ravel(), fm.ravel(), ok.ravel()
        for sid, nm in sig.items():
            ix = cells[sid][okf[cells[sid]]]
            if ix.size:
                A, Hm, Fm = float(np.max(af[ix])), float(np.max(hf[ix])), float(np.max(ff[ix]))
                rows.append([nm, round(A), round(Hm, 1), round(Fm, 1),
                             sum(A >= c for c in ACC), sum(Hm >= c for c in H1), sum(Fm >= c for c in FUT)])
        hp = np.clip(np.rint(Z[i] * 2), 0, 255).astype(np.uint8)        # 0.5㎜ 단위, 127.5㎜ 에서 멈춤
        out.append({"tm": tm, "fc": info["live"] and i > now_i, "now": _png(img), "mask": _png(mk), "h1": _png(hp, "L"),
                    "c3": c3, "rows": rows, "left": min(6, n - 1 - i)})
    ed = np.zeros(msig.shape + (3,), np.uint8)
    ed[..., 0] = memd >> 8
    ed[..., 1] = memd & 255
    res = {**info, "acc": ACC, "h1": H1, "fut": FUT, "pal": PAL, "names": NAMES, "v": V, "now_i": now_i,
           "emd": {e["id"]: f'{e["sigun"]} {e["name"]}' for e in geo["emd"]}, "emdpng": _png(ed),
           "frames": out, "w": int(msig.shape[1]), "h": int(msig.shape[0])}
    if len(_CACHE) > 3:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[ck] = res
    return res
