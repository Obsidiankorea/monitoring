"""시연(스냅숏) — 지금을 굳혀 두고 나중에 그대로 띄운다. 만들기 · 목록 · 지우기.

굳힌 것은 config.SNAPS 에 쌓인다(서버 /state/snaps, PC data/snaps) — 저장소에는 넣지 않는다.
  <SNAPS>/<이름>/meta.json · state/gnweather.db · state/cache/{grid,qpf}
띄우기는 시연 서버(:8001, GN_DEMO) — /snap/<이름> 으로 열면 그 시연으로 갈아 탄다(main.snap_open).

잘라 두는 것(그 시각 T 뒤는 다 버린다 — 화면이 '가장 새 것'을 고르므로 뒤 자료가 남으면 안 된다):
  관측 매시 72시간 · 매분 50시간 · 격자 실측 72시간(그전까지 온 비)
  초단기(읍면동 · 격자) · 단기(오늘~모레) · 예측 분포 그림 — T 이전 마지막 두 발표분(그림은 마지막 하나)
  특보 — T 에 기상청에서 다시 읽은 것(tm=T). 못 읽으면 모아 둔 것
  설정(지도 층 · 누적 구간 …) · 수집 기록은 그대로
⚠️ 지난 시각으로 굳히지 않는다 — 서버는 예측 격자 · 그림을 마지막 몇 발표분만 남겨서 그때 예측이 없다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import clock, config, db as _db

log = logging.getLogger("snaps")

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LOCK = threading.Lock()
JOB: dict | None = None          # 지금 굳히는 중인 것 {name, started, done, error, meta}


def root() -> Path:
    return config.SNAPS


def check_name(name: str) -> str:
    if not NAME_RE.match(name or "") or name.startswith(".tmp"):
        raise ValueError(f"시연 이름이 낯설다: {name!r}")
    return name


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
    for kind, last in (("vsrt", T12), ("shrt", T10)):
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


def set_acc(db: Path, acc: dict | None) -> dict:
    """시연을 열면 이 누적 구간으로 — 지도 설정 'map'(acc_from · acc_hours). acc 가 없으면 굳힐 때 설정 그대로."""
    c = sqlite3.connect(db)
    r = c.execute("SELECT value FROM setting WHERE key='map'").fetchone()
    cur = json.loads(r[0]) if r else {}
    if acc:
        cur.update(acc_from=acc.get("from", "hours"), acc_hours=int(acc.get("hours") or cur.get("acc_hours") or 12))
        c.execute("INSERT OR REPLACE INTO setting(key, value) VALUES('map', ?)", (json.dumps(cur, ensure_ascii=False),))
        c.commit()
    c.close()
    return {"from": cur.get("acc_from", "hours"), "hours": int(cur.get("acc_hours", 12))}


def alerts_at(now: datetime) -> dict:
    """그 시각에 발효 중이던 특보 — 기상청 tm=그 시각. 실패하면 KmaError."""
    from .collectors.alerts import normalize
    from .kma import fetch_bytes
    raw = asyncio.run(fetch_bytes("/api/typ01/url/wrn_now_data.php",
                                  {"fe": "f", "tm": now.strftime("%Y%m%d%H%M"), "disp": "1", "help": "0"}))
    return normalize(raw, now)


def put_alerts(db: Path, now: datetime, data: dict) -> None:
    """그 시각 특보 한 장으로 — 앞 장은 지운다(모은 것이 틀렸을 수 있다: 10.19 까지 특보 응답을 못 읽었다)."""
    T = now.strftime("%Y-%m-%d %H:%M")
    c = sqlite3.connect(db)
    c.execute("DELETE FROM snapshot WHERE kind='alerts'")
    c.execute("INSERT INTO snapshot(kind, base_time, fetched_at, payload) VALUES('alerts', ?, ?, ?)",
              (T, T, json.dumps(data, ensure_ascii=False)))
    c.execute("UPDATE collect_log SET detail=? WHERE kind='alerts'", (f"{len(data['groups'])}종",))
    c.commit()
    c.close()


def _alerts_kept(db: Path) -> dict | None:
    c = sqlite3.connect(db)
    r = c.execute("SELECT payload FROM snapshot WHERE kind='alerts' ORDER BY base_time DESC LIMIT 1").fetchone()
    c.close()
    return json.loads(r[0]) if r else None


def _size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def make(*, now: datetime | None = None, name: str | None = None, title: str | None = None, note: str = "",
         acc: dict | None = None, src: Path | None = None, overwrite: bool = False,
         alerts: str = "kma", out_root: Path | None = None) -> dict:
    """굳힌다 → meta. src 가 없으면 이 서버의 쌓인 자료(config.DB_PATH · CACHE)에서.
    alerts='kma' 면 특보를 그 시각으로 기상청에서 다시 읽는다(못 읽으면 모아 둔 것), 'db' 면 모아 둔 것만."""
    now = (now or clock.now()).replace(second=0, microsecond=0)
    name = check_name(name or f"snap-{now:%Y%m%d-%H%M}")
    base = out_root or root()
    base.mkdir(parents=True, exist_ok=True)
    out, tmp = base / name, base / f".tmp-{name}"
    if out.exists() and not overwrite:
        raise FileExistsError(name)
    db_src = (src / "gnweather.db") if src else _db.DB_PATH
    cache_src = (src / "cache") if src else config.CACHE
    with _LOCK:
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "state" / "cache").mkdir(parents=True)
        try:
            db = tmp / "state" / "gnweather.db"
            s = sqlite3.connect(f"file:{db_src.as_posix()}?mode=ro", uri=True)
            d = sqlite3.connect(db)
            s.backup(d)
            d.close()
            s.close()
            kept = prune_db(db, now)
            files = copy_cache(cache_src, tmp / "state" / "cache", now, kept)
            acc = set_acc(db, acc)
            al, al_src = None, "db"
            if alerts == "kma":
                try:
                    al = alerts_at(now)
                    put_alerts(db, now, al)
                    al_src = "kma"
                except Exception as e:             # 키 없음 · 기상청 실패 — 모아 둔 것으로
                    log.warning("특보를 그 시각으로 다시 못 읽었다: %s", e)
            al = al or _alerts_kept(db) or {"groups": []}
            warn = []
            if not files.get("vsrt"):
                warn.append("초단기 격자 없음")
            if not files.get("shrt"):
                warn.append("단기 격자 없음")
            if not files.get("qpf"):
                warn.append("예측 분포 그림 없음")
            if not files.get("obs60"):
                warn.append("실측 격자 없음")
            al_txt = [f"{g['name']}({'·'.join(g['siguns']) or g['count']})" for g in al["groups"]]
            meta = {"name": name, "title": (title or "").strip() or _title(now, al_txt), "now": now.strftime("%Y%m%d%H%M"),
                    "note": note.strip(), "acc": acc, "alerts": al_txt, "alerts_src": al_src, "warn": warn,
                    "made_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "kept": {k: v for k, v in kept.items() if k != "rows"}, "rows": kept["rows"], "files": files}
            meta["mb"] = round(_size(tmp) / 1048576, 1)
            (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
            if out.exists():
                shutil.rmtree(out)
            tmp.rename(out)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    log.info("시연 굳힘 %s (%s MB)", name, meta["mb"])
    return meta


def _title(now: datetime, al: list[str]) -> str:
    t = f"{now.month}.{now.day}. {now:%H:%M}"
    return t + (" · " + ", ".join(al) if al else "")


def list_all(base: Path | None = None) -> list[dict]:
    """굳힌 것 — 새 것(시각)부터."""
    out = []
    base = base or root()
    for m in base.glob("*/meta.json") if base.exists() else []:
        if m.parent.name.startswith(".tmp"):
            continue
        try:
            j = json.loads(m.read_text("utf-8"))
        except ValueError:
            continue
        acc = j.get("acc") or ({"from": "hours", "hours": j["hours"]} if j.get("hours") else None)
        out.append({"name": m.parent.name, "title": j.get("title"), "now": j.get("now"), "note": j.get("note"),
                    "acc": acc, "alerts": j.get("alerts"), "warn": j.get("warn") or [], "mb": j.get("mb"),
                    "made_at": j.get("made_at")})
    out.sort(key=lambda x: (x["now"] or "", x["name"]), reverse=True)
    return out


def delete(name: str) -> None:
    p = root() / check_name(name)
    if not (p / "meta.json").exists():
        raise FileNotFoundError(name)
    with _LOCK:
        shutil.rmtree(p)
    log.info("시연 지움 %s", name)


def start(**kw) -> dict:
    """뒤에서 굳힌다 — 서버 DB 가 크면 수십 초 걸려 PC 가 서버로 넘길 때(20초) 끊긴다. 화면은 JOB 을 본다."""
    global JOB
    if JOB and not JOB.get("done"):
        raise RuntimeError(f"이미 굳히는 중이다({JOB['name']})")
    now = (kw.pop("now", None) or clock.now()).replace(second=0, microsecond=0)
    name = check_name(kw.pop("name", None) or f"snap-{now:%Y%m%d-%H%M}")
    if (root() / name).exists() and not kw.get("overwrite"):
        raise FileExistsError(name)
    JOB = {"name": name, "started": datetime.now().strftime("%H:%M:%S"), "done": False, "error": None, "meta": None}
    job = JOB

    def run():
        try:
            job["meta"] = make(now=now, name=name, **kw)
        except Exception as e:                       # noqa: BLE001 — 화면에 까닭을 남긴다
            log.exception("시연 굳히기 실패")
            job["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            job["done"] = True

    threading.Thread(target=run, name="snap-make", daemon=True).start()
    return job


# ── 경남 AWS(스방) 덧붙이기 — 서버(언레이드)는 스방에 닿지 않아 굳힌 시연에 경남 AWS 가 없다 ────────────────
# 내부망 PC 에서 그 시각까지의 스방 시간 강수를 받아 저장소(data/demo/bangjae/<시연 이름>.json)에 넣어 두면
# (tools/snap_bangjae.py), 시연 서버가 그 시연을 띄울 때 **사본** DB 에 얹는다 — 굳힌 원본은 손대지 않는다.
BANGJAE_DIR = config.DATA / "demo" / "bangjae"


def add_bangjae(db: Path, name: str | None) -> int:
    """data/demo/bangjae/<name>.json 의 스방 시간 강수를 db 에 얹는다(없는 칸만). 얹은 줄 수."""
    f = BANGJAE_DIR / f"{name}.json" if name else None
    if not f or not f.exists():
        return 0
    j = json.loads(f.read_text("utf-8"))
    c = sqlite3.connect(db)
    n = 0
    for tm, stn, nm, sg, mm in j["rows"]:
        n += c.execute("INSERT OR IGNORE INTO bangjae_hourly(tm, stn, name, sigun, mm, fetched_at) VALUES(?,?,?,?,?,?)",
                       (tm, stn, nm, sg, mm, j.get("made", "demo"))).rowcount
    c.execute("INSERT OR REPLACE INTO collect_log(kind, ok_at, tried_at, ok, detail) VALUES('bangjae', ?, ?, 1, ?)",
              (j["now"], j["now"], f"경남 AWS {j.get('stations', '')}곳 — 내부망에서 덧붙임({f.name})"))
    c.commit()
    c.close()
    log.info("시연 %s 에 경남 AWS %d칸을 얹었다", name, n)
    return n
