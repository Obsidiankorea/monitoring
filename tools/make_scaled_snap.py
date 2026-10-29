"""가상 시연 — 굳혀 둔 실제 시연의 비를 k배로 키워 '대피 기준까지 간 비'를 만든다(발표 · 훈련용, 실제 아님).

    .venv\\Scripts\\python.exe tools\\make_scaled_snap.py live-20261019-0024 fake-20261019-x4 --factor 4 --qpf-from 202409210000

키우는 것: 격자(obs15 · obs60 · obsday · odam · 초단기 vsrt · 단기 shrt), 관측 매시(rn_hr1 · rn_day) · 매분(rn_15m · rn_60m ·
rn_day), 스방 매시, 초단기 RN1(읍면동), 단기 PCP. 예측 분포 그림(QPF)은 그림이라 키울 수 없어 뺀다 —
--qpf-from <발표시각> 을 주면 그 과거 발표분(실제 큰비)을 기상청에서 받아 이 시연의 발표 시각 자리에 넣는다
(그림 속 비는 그날 비다 — meta.note 에 적는다). 2024.9.21 00:00 은 남해안 띠 모양이 10.19 와 닮았고 훨씬 세다.
특보는 키운 비에 [[기상특보 발표기준]] 호우 기준(주의보 3시간 60 · 12시간 110㎜, 경보 3시간 90 · 12시간 180㎜)을
시군 최대 칸으로 적용해 **산출**한다 — 발표 내역이 아니다(기준은 '예상'인데 여기서는 실측으로 본다).
meta.fake = true → 화면이 '가상'으로 표시한다. 원본 시연은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, gridstore  # noqa: E402

SIGUN_FULL = {"창원": "창원시", "진주": "진주시", "통영": "통영시", "사천": "사천시", "김해": "김해시", "밀양": "밀양시",
              "거제": "거제시", "양산": "양산시", "의령": "의령군", "함안": "함안군", "창녕": "창녕군", "고성": "고성군",
              "남해": "남해군", "하동": "하동군", "산청": "산청군", "함양": "함양군", "거창": "거창군", "합천": "합천군"}


def scale_grids(cache: Path, k: float) -> dict:
    n = {}
    for layer in ("obs15", "obs60", "obsday", "odam", "vsrt", "shrt"):
        for f in sorted((cache / "grid" / layer).glob("*.u16.gz")):
            u = np.frombuffer(gzip.decompress(f.read_bytes()), "<u2").astype("f8")
            ok = u != gridstore.MISSING
            u[ok] = np.minimum(np.round(u[ok] * k), gridstore.MISSING - 1)
            f.write_bytes(gzip.compress(u.astype("<u2").tobytes(), 6))
            n[layer] = n.get(layer, 0) + 1
    return n


def scale_db(db: Path, k: float) -> None:
    c = sqlite3.connect(db)
    for sql in ("UPDATE obs_hourly SET rn_hr1 = rn_hr1 * ? WHERE rn_hr1 > 0",
                "UPDATE obs_hourly SET rn_day = rn_day * ? WHERE rn_day > 0",
                "UPDATE obs_minute SET rn_60m = rn_60m * ? WHERE rn_60m > 0",
                "UPDATE obs_minute SET rn_15m = rn_15m * ? WHERE rn_15m > 0",
                "UPDATE obs_minute SET rn_day = rn_day * ? WHERE rn_day > 0",
                "UPDATE bangjae_hourly SET mm = mm * ? WHERE mm > 0",
                "UPDATE fcst_rn1 SET rn1 = rn1 * ? WHERE rn1 > 0",
                "UPDATE fcst_short SET val = val * ? WHERE var = 'PCP' AND val > 0"):
        c.execute(sql, (k,))
    c.execute("DELETE FROM qpf_frame")
    c.commit()
    c.close()


def borrow_qpf(cache: Path, db: Path, src_tm: str) -> tuple[str, int]:
    """과거 발표분 src_tm 의 예측 분포 그림을 받아 시연의 마지막 발표 시각(qpf_publish) 자리에 넣는다."""
    import asyncio

    from app.collectors import qpf
    qpf._legend_cache.update({"colors": ["-"]})          # 범례는 시연 DB 에 이미 있다 — 실황 DB 에 쓰지 않게
    c = sqlite3.connect(db)
    dst = c.execute("SELECT MAX(tmfc) FROM qpf_publish").fetchone()[0]
    outdir = cache / "qpf" / dst
    outdir.mkdir(parents=True, exist_ok=True)

    async def get(ef):
        for _ in range(3):
            try:
                png, notyet = qpf._crop(await qpf._one(src_tm, ef, config.QPF["size"]))
                if not notyet:
                    return png
            except qpf.KmaError:
                await asyncio.sleep(0.6)
        return None

    n = 0
    for ef in qpf.frame_efs(config.QPF):                 # 한꺼번에 부르면 중간이 빠진다(qpf.py) — 차례로
        png = asyncio.run(get(ef))
        if png is None:
            continue
        (outdir / f"{ef:03d}.png").write_bytes(png)
        c.execute("INSERT OR REPLACE INTO qpf_frame(tmfc, ef, path, bytes, fetched_at) VALUES(?,?,?,?,?)",
                  (dst, ef, f"qpf/{dst}/{ef:03d}.png", len(png), datetime.now().strftime("%Y-%m-%d %H:%M")))
        n += 1
    c.commit()
    c.close()
    return dst, n


def computed_alerts(cache: Path, now: datetime) -> dict:
    """키운 매시 격자로 시군 최대 3 · 12시간 합 → 호우주의보 · 경보(산출)."""
    gridstore.ROOT = cache / "grid"
    ks = sorted(k for k in gridstore.keys("obs60") if k.endswith("00") and k <= now.strftime("%Y%m%d%H%M"))

    def tot(n):
        arr = None
        for k in ks[-n:]:
            a = gridstore.load("obs60", k)
            arr = a if arr is None else arr + np.nan_to_num(a)
        return arr

    s3 = {r["sigun"]: r["max"] for r in gridstore.sigun_stats(tot(3)) if r.get("kind") == "gn"}
    s12 = {r["sigun"]: r["max"] for r in gridstore.sigun_stats(tot(12)) if r.get("kind") == "gn"}
    warn = [s for s in SIGUN_FULL if (s3.get(s) or 0) >= 90 or (s12.get(s) or 0) >= 180]
    watch = [s for s in SIGUN_FULL if s not in warn and ((s3.get(s) or 0) >= 60 or (s12.get(s) or 0) >= 110)]
    hm = now.strftime("%H:%M")
    groups = []
    for name, lv, sg in (("호우경보", "warn", warn), ("호우주의보", "watch", watch)):
        if sg:
            groups.append({"lv": lv, "name": name, "sea": False, "tmfc": hm, "count": len(sg), "unit": "개시군",
                           "regions": [SIGUN_FULL[s] for s in sg], "siguns": sg, "computed": True})
    return {"groups": groups, "pending": [], "computed": True,
            "basis": {s: {"3h": round(s3.get(s) or 0, 1), "12h": round(s12.get(s) or 0, 1)} for s in SIGUN_FULL}}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("name")
    ap.add_argument("--factor", type=float, default=4.0)
    ap.add_argument("--root", type=Path, default=config.SNAPS)
    ap.add_argument("--qpf-from", metavar="YYYYMMDDHHMM", help="이 과거 발표분의 예측 분포 그림을 빌려 넣는다(기상청에서 받음)")
    a = ap.parse_args(argv)
    src, out = a.root / a.src, a.root / a.name
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    shutil.rmtree(out / "state" / "cache" / "qpf", ignore_errors=True)
    m = json.loads((out / "meta.json").read_text("utf-8"))
    now = datetime.strptime(m["now"], "%Y%m%d%H%M")
    k = a.factor
    files = scale_grids(out / "state" / "cache", k)
    db = out / "state" / "gnweather.db"
    scale_db(db, k)
    al = computed_alerts(out / "state" / "cache", now)
    qpf_note = ""
    if a.qpf_from:
        dst, nq = borrow_qpf(out / "state" / "cache", db, a.qpf_from)
        src = datetime.strptime(a.qpf_from, "%Y%m%d%H%M")
        qpf_note = (f"예측 분포 그림 {nq}장은 {src.year}.{src.month}.{src.day}. {src:%H:%M} 발표분(실제 다른 날 비)을 "
                    f"{dst[8:10]}:{dst[10:12]} 발표 자리에 빌려 넣음.")
        files["qpf"] = nq
    T = now.strftime("%Y-%m-%d %H:%M")
    c = sqlite3.connect(db)
    c.execute("DELETE FROM snapshot WHERE kind='alerts'")
    c.execute("INSERT INTO snapshot(kind, base_time, fetched_at, payload) VALUES('alerts', ?, ?, ?)",
              (T, T, json.dumps(al, ensure_ascii=False)))
    c.commit()
    c.close()
    al_txt = [f"{g['name']}({'·'.join(g['siguns'])})" for g in al["groups"]]
    m.update(name=a.name, fake=True, factor=k,
             title=f"가상 — {m['title'].split(' · ')[0]} ×{k:g} (실제 아님)",
             note=f"실제 {m['title']} 의 비를 {k:g}배로 키운 가상 상황. 특보는 키운 비에 호우 기준을 적용해 산출(발표 아님). "
                  + (qpf_note or "예측 분포 그림 없음."),
             alerts=al_txt, warn=sorted(set((m.get("warn") or []) + ([] if qpf_note else ["예측 분포 그림 없음(가상)"]))),
             made_at=datetime.now().strftime("%Y-%m-%d %H:%M"), files=files)
    m["mb"] = round(sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1048576, 1)
    (out / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"out": str(out), "title": m["title"], "alerts": al_txt,
                      "basis_top": sorted(al["basis"].items(), key=lambda x: -x[1]["12h"])[:6]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
