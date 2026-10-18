"""지금 시점을 시연용으로 굳힌다 — 서버(또는 PC)의 쌓인 자료(DB · 격자 · 예측 그림)를 떠서 그 시각으로 잘라 둔다.

    .venv\\Scripts\\python.exe tools\\snapshot.py <떠 온 폴더> <이름> --now 202610181536 --title "…"

<떠 온 폴더> = gnweather.db + cache/ (서버 GN_STATE 를 SQLite 백업 · cp 로 뜬 것).
만드는 것: data/demo/snap/<이름>/{meta.json, state/gnweather.db, state/cache/{grid,qpf}}
띄우기:   python -m app.main --snap <이름>     (수집 안 함 · 시계를 그 시각에 멈춘다 · 기본 포트 8001)
          서버는 deploy.sh 가 gn-demo 컨테이너(:8001)로 가장 새 시연을 띄운다.

잘라 두는 것(그 시각 T 이후는 다 버린다 — 화면이 '가장 새 것'을 고르므로 뒤 자료가 남으면 안 된다):
  관측 매시 72시간 · 매분 50시간 · 격자 실측 72시간
  초단기(읍면동 · 격자) · 단기 · 예측 분포 그림은 T 이전 마지막 두 발표분(그림은 마지막 하나)
  특보 스냅숏은 T 이전 마지막 몇 개 · 설정 · 수집 기록은 그대로
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demo" / "snap"


def _keys_upto(names, t, n=None):
    ks = sorted(k for k in names if k <= t)
    return set(ks[-n:]) if n else set(ks)


def prune_db(db: Path, now: datetime) -> dict:
    T = now.strftime("%Y-%m-%d %H:%M")
    T12, T10 = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H")
    c = sqlite3.connect(db)
    out = {}
    h72 = (now - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M")
    h50 = (now - timedelta(hours=50)).strftime("%Y-%m-%d %H:%M")
    c.execute("DELETE FROM obs_hourly WHERE tm > ? OR tm < ?", (T, h72))
    c.execute("DELETE FROM obs_minute WHERE tm > ? OR tm < ?", (T, h50))
    for tbl, col, t, n in (("fcst_rn1", "tmfc", T12, 2), ("fcst_short", "tmfc", T10, 2),
                           ("fcst_short_run", "tmfc", T10, 2), ("qpf_frame", "tmfc", T12, 1)):
        keep = _keys_upto([r[0] for r in c.execute(f"SELECT DISTINCT {col} FROM {tbl}")], t, n)
        q = ",".join("?" * len(keep)) or "''"
        c.execute(f"DELETE FROM {tbl} WHERE {col} NOT IN ({q})", tuple(keep))
        out[tbl] = sorted(keep)
    c.execute("DELETE FROM qpf_publish WHERE tmfc > ?", (T12,))
    c.execute("DELETE FROM qpf_publish WHERE rowid NOT IN (SELECT rowid FROM qpf_publish ORDER BY tmfc DESC LIMIT 200)")
    c.execute("DELETE FROM snapshot WHERE base_time > ? OR fetched_at > ?", (T, T))
    c.execute("DELETE FROM snapshot WHERE rowid NOT IN (SELECT rowid FROM snapshot ORDER BY fetched_at DESC LIMIT 6)")
    for tbl in ("bangjae_rain", "bangjae_hourly"):
        c.execute(f"DELETE FROM {tbl} WHERE tm > ?", (T,))
    c.commit()
    c.execute("VACUUM")
    out["rows"] = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    return out


def copy_cache(src: Path, dst: Path, now: datetime, kept: dict) -> dict:
    T12, T10 = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H")
    h72 = (now - timedelta(hours=72)).strftime("%Y%m%d%H%M")
    n = {}
    for kind in ("obs15", "obs60", "obsday", "odam"):
        d = src / "grid" / kind
        for f in sorted(d.glob("*.u16.gz")) if d.exists() else []:
            k = f.name[:12]
            if h72 <= k <= T12:
                (dst / "grid" / kind).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst / "grid" / kind / f.name)
                n[kind] = n.get(kind, 0) + 1
    for kind, tl, last in (("vsrt", 12, T12), ("shrt", 10, T10)):
        d = src / "grid" / kind
        files = sorted(d.glob("*.u16.gz")) if d.exists() else []
        runs = _keys_upto({f.name.split("_")[0] for f in files}, last, 2)
        for f in files:
            if f.name.split("_")[0] in runs:
                (dst / "grid" / kind).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst / "grid" / kind / f.name)
                n[kind] = n.get(kind, 0) + 1
    for tmfc in kept.get("qpf_frame", []):
        s = src / "qpf" / tmfc
        if s.exists():
            shutil.copytree(s, dst / "qpf" / tmfc, dirs_exist_ok=True)
            n["qpf"] = n.get("qpf", 0) + len(list(s.iterdir()))
    return n


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("name")
    ap.add_argument("--now", required=True, help="시연 시각 YYYYMMDDHHMM(KST)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    now = datetime.strptime(a.now, "%Y%m%d%H%M")
    out = OUT / a.name
    if out.exists():
        shutil.rmtree(out)
    (out / "state" / "cache").mkdir(parents=True)
    db = out / "state" / "gnweather.db"
    src = sqlite3.connect(f"file:{a.src / 'gnweather.db'}?mode=ro", uri=True)
    dst = sqlite3.connect(db)
    src.backup(dst)
    dst.close()
    src.close()
    kept = prune_db(db, now)
    n = copy_cache(a.src / "cache", out / "state" / "cache", now, kept)
    meta = {"name": a.name, "title": a.title, "now": a.now, "note": a.note,
            "made_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "kept": {k: v for k, v in kept.items() if k != "rows"}, "rows": kept["rows"], "files": n}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(json.dumps({"out": str(out), "MB": round(size / 1048576, 1), "rows": kept["rows"], "files": n},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
