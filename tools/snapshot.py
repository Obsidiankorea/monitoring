"""떠 온 서버 자료로 시연을 굳힌다 — 화면의 '지금 저장'(app/snaps.py)과 같은 일을 PC 에서.

    .venv\\Scripts\\python.exe tools\\snapshot.py <떠 온 폴더> --now 202610190024 [--name …] [--title …]
        [--acc 6 | today | yesterday]   시연을 열면 이 누적 구간(지도 설정 · 종합 화면). 없으면 굳힐 때 설정 그대로
        [--alerts db]                   특보를 모아 둔 것으로(기본은 그 시각으로 기상청에서 다시 읽는다)
        [--out <폴더>]                   기본 config.SNAPS(PC data/snaps) — 서버로는 scp 로 /state/snaps 에

<떠 온 폴더> = gnweather.db + cache/ (서버 GN_STATE 를 SQLite 백업 · cp 로 뜬 것).
보통은 이것을 쓰지 않는다 — 실황 화면(지도 설정 › 데모 · 종합 화면 설정 › 데모 시연)의 '지금 저장'이 서버에서 바로 굳힌다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, snaps  # noqa: E402


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--now", required=True, help="시연 시각 YYYYMMDDHHMM(KST)")
    ap.add_argument("--name")
    ap.add_argument("--title", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--acc", help="6 · 12 · 24 · 48 · today · yesterday")
    ap.add_argument("--alerts", choices=("kma", "db"), default="kma")
    ap.add_argument("--out", type=Path, default=config.SNAPS)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    acc = None
    if a.acc:
        acc = {"from": a.acc, "hours": 12} if a.acc in ("today", "yesterday") else {"from": "hours", "hours": int(a.acc)}
    meta = snaps.make(now=datetime.strptime(a.now, "%Y%m%d%H%M"), name=a.name, title=a.title, note=a.note,
                      acc=acc, src=a.src, overwrite=a.overwrite, alerts=a.alerts, out_root=a.out)
    print(json.dumps({k: meta[k] for k in ("name", "title", "now", "acc", "alerts", "warn", "mb", "files")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
