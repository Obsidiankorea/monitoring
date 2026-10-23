"""시연(스냅숏)에 경남 AWS(스방)를 덧붙일 자료 — 내부망 PC 에서 돌린다.

    .venv\\Scripts\\python.exe tools\\snap_bangjae.py live-20261019-0024 "2026-10-19 00:24"

서버(언레이드)는 스방에 닿지 않아 서버에서 굳힌 시연에는 경남 AWS 가 없다. 스방은 지난 날짜의 시간 강수도
주므로(dt096), 그 시각 앞 72시간(시연이 남기는 관측 깊이와 같다)을 받아 data/demo/bangjae/<시연 이름>.json 에 둔다.
저장소에 넣어 서버를 갱신하면 시연 서버가 그 시연을 띄울 때 사본 DB 에 얹는다(app/snaps.add_bangjae).

⚠️ 그 시각이 든 스방 칸(00:24 면 00시 = 00:00~00:59)은 넣지 않는다 — 지금 받으면 그 뒤에 온 비까지 들어 있다.
   스방 칸은 시 단위라 '00:24 까지'를 따로 받을 길이 없다. 그 앞 칸까지만(시연의 기상청 값은 그 시각까지 그대로).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bangjae import Client  # noqa: E402
from app.snaps import BANGJAE_DIR, check_name  # noqa: E402

HOURS = 72


async def fetch(days: list[datetime]) -> dict[str, list[dict]]:
    async with Client() as c:
        return {d.strftime("%Y-%m-%d"): await c.station_hourly(d.strftime("%Y%m%d")) for d in days}


def main(argv=None) -> None:
    argv = argv or sys.argv[1:]
    name, now = check_name(argv[0]), datetime.strptime(argv[1], "%Y-%m-%d %H:%M")
    end = now.replace(minute=0)                                   # 이 칸부터는 넣지 않는다(위)
    start = end - timedelta(hours=HOURS)
    days = [start + timedelta(days=i) for i in range((end.date() - start.date()).days + 1)]
    rows, stns = [], set()
    for day, sts in asyncio.run(fetch(days)).items():
        for st in sts:
            for h, mm in enumerate(st["mm"]):
                tm = datetime.strptime(f"{day} {h:02d}", "%Y-%m-%d %H")
                if mm is None or not (start <= tm < end):
                    continue
                rows.append([tm.strftime("%Y-%m-%d %H:%M"), st["stn"], st["name"], st["sigun"], mm])
                stns.add(st["stn"])
    rows.sort()
    out = {"snap": name, "now": now.strftime("%Y-%m-%d %H:%M"), "made": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "from": start.strftime("%Y-%m-%d %H:%M"), "until": end.strftime("%Y-%m-%d %H:%M"),
           "stations": len(stns), "rows": rows}
    BANGJAE_DIR.mkdir(parents=True, exist_ok=True)
    f = BANGJAE_DIR / f"{name}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), "utf-8")
    top = {}
    for tm, stn, nm, sg, mm in rows:
        top[(sg, nm)] = top.get((sg, nm), 0) + mm
    best = sorted(top.items(), key=lambda x: -x[1])[:5]
    print(json.dumps({"file": str(f), "rows": len(rows), "stations": len(stns), "from": out["from"], "until": out["until"],
                      "top72h": [f"{sg} {nm} {v:.1f}" for (sg, nm), v in best]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
