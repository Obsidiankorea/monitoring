"""읍면동 · 시군마다 '최근 10년 호우 피해 이력'을 미리 세어 data/geo/dz_history.json 에 둔다 — 상황판단의 지역 여건용.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_dz_history.py

쓰는 자료(PC 에만 있다)
  위키 raw/풍수해 이력 구축/복구계획 원본 파싱/recovery_facility_detail.csv — 경남도 복구계획 20건(2016.10~2026.8)의 공공시설 복구 세부내역
  위키 data/경남 풍수해 사건×시군 피해.csv — 사건×시군 복구액 · 산사태 복구건수(검수된 표)
  tools/.cache/vworld/AL_D010_48_*.zip — 법정동 · 리 이름(리 → 읍면 찾기)
읍면동은 시설 이름에 읍면동 · 리 이름이 적힌 줄만 안다(전체의 1/3쯤) — 건수는 '확인된 것만'이고 실제보다 적다.
세부내역의 금액은 단위가 섞여 있어 쓰지 않는다(금액은 시군 표에서만).
"""
from __future__ import annotations

import csv
import json
import re
import struct
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "obsidian" / "재난"
OUT = ROOT / "data" / "geo" / "dz_history.json"
SKIP = re.compile(r"지원금|위로금|^[<※]|해양쓰레기")


def legal_names() -> set[str]:
    """GIS건물통합정보의 법정동명('경상남도 산청군 단성면 운리') 전부."""
    z = zipfile.ZipFile(sorted((ROOT / "tools" / ".cache" / "vworld").glob("AL_D010_48_*.zip"))[-1])
    out = set()
    for n in [n for n in z.namelist() if n.endswith(".dbf")]:
        d = z.open(n)
        cnt, hl, rl = struct.unpack("<IHH", d.read(32)[4:12])
        hd, o, at = d.read(hl - 32), 1, None
        for k in range(0, len(hd) - 1, 32):
            f = hd[k:k + 32]
            if f[0] == 0x0D:
                break
            if f[:11].split(bytes([0]))[0] == b"A4":
                at = (o, f[16])
            o += f[16]
        for _ in range(cnt):
            r = d.read(rl)
            if len(r) < rl:
                break
            out.add(r[at[0]:at[0] + at[1]].replace(bytes([0]), b"").decode("euc-kr", "replace").strip())
    return out


def main():
    emd = defaultdict(set)
    for f in json.loads((ROOT / "tools" / ".cache" / "emd_grid.json").read_text("utf-8"))["features"]:
        emd[f["properties"]["sigun"]].add(f["properties"]["name"])
    ri = defaultdict(lambda: defaultdict(set))             # 시군 → 리 · 법정동 → {읍면(동이면 자신)}
    for nm in legal_names():
        p = nm.split()
        tail = [x for x in p[2:] if not x.endswith("구")]
        if len(p) < 3 or not tail:
            continue
        if tail[0][-1] in "읍면":
            if len(tail) > 1:
                ri[p[1][:-1]][tail[1]].add(tail[0])
        else:
            ri[p[1][:-1]][tail[0]].add(tail[0])

    def place(sg, text):
        hit = [e for e in emd[sg] if e in text]
        if hit:
            return max(hit, key=len)
        for m in re.finditer(r"[가-힣]{1,4}[리동](?![가-힣])", text):
            for k in range(len(m.group()) - 1):              # '오부면양촌리'처럼 붙은 글도
                c = ri[sg].get(m.group()[k:])
                if c and len(c) == 1 and next(iter(c)) in emd[sg]:   # 같은 이름의 리가 여러 읍면에 있으면 버린다
                    return next(iter(c))
        return None

    rows = [r for r in csv.DictReader(open(WIKI / "raw" / "풍수해 이력 구축" / "복구계획 원본 파싱" / "recovery_facility_detail.csv", encoding="utf-8-sig"))
            if not SKIP.search(r["시설명"])]
    E = defaultdict(lambda: {"ev": set(), "n": 0, "ty": Counter(), "last": ""})
    tot, got = Counter(), Counter()
    for r in rows:
        sg = r["시군"][:-1]
        tot[sg] += 1
        e = place(sg, r["시설명"])
        if not e:
            continue
        got[sg] += 1
        a = E[f"{sg}|{e}"]
        a["n"] += 1; a["ev"].add(r["사건폴더"]); a["ty"][r["시설유형"].split("(")[0]] += 1
        a["last"] = max(a["last"], r["시작일"][:7])
    S = defaultdict(lambda: {"ev": set(), "won": 0.0, "slide": 0, "last": ""})
    for r in csv.DictReader(open(WIKI / "data" / "경남 풍수해 사건×시군 피해.csv", encoding="utf-8-sig")):
        if r["event_id"][:4] < "2016":
            continue
        a = S[r["시군"].split("(")[0].strip()[:-1]]
        a["ev"].add(r["event_id"]); a["last"] = max(a["last"], f"{r['event_id'][:4]}-{r['event_id'][4:6]}")
        a["won"] += float(r["총복구액_천원"] or 0); a["slide"] += int(float(r["산사태복구건수"] or 0))
    out = {"built": date.today().isoformat(), "span": "2016.10~2026.8",
           "src": "경남도 피해현황 및 복구계획 20건(공공시설 복구 세부내역 · 사건×시군 표) — 읍면동은 시설 이름에 적힌 것만",
           "sigun": {k: {"ev": len(v["ev"]), "eok": round(v["won"] / 1e5), "slide": v["slide"], "last": v["last"],
                         "known": round(got[k] / tot[k] * 100) if tot[k] else None, "n": tot[k]} for k, v in sorted(S.items())},
           "emd": {k: {"ev": len(v["ev"]), "n": v["n"], "ty": [t for t, _ in v["ty"].most_common(3)], "last": v["last"]} for k, v in sorted(E.items())}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"→ {OUT} · 세부내역 {len(rows):,}줄 중 읍면동을 아는 줄 {sum(got.values()):,} · 읍면동 {len(E)} · 시군 {len(S)}")


if __name__ == "__main__":
    main()
