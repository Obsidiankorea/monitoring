"""연속지적도(공개 자료)로 인명피해 우려지역 지구의 필지를 찾아 좌표 · 모양을 위키에 쓴다 — 브이월드 없이(저장 가능한 자료).

    .venv/Scripts/python.exe -X utf8 tools/build_parcels.py <지적도 .shp(확장자 빼도 됨)> <법정동코드 전체자료.txt>
    .venv/Scripts/python.exe -X utf8 tools/build_parcels.py --selftest

쓰는 곳: 위키 data/지구좌표.csv(지역ID · 위도 · 경도 · PNU · 지번 · 방법 · 메모) · data/지구필지.geojson(필지 모양).
방법: 정확 = 지번 그대로 · 대시복원 = 위키 지번에 '-' 가 빠져(84939) 나눠 보니 하나만 있음 · 본번근사 = 부번 필지가 없어(분할 · 합병) 같은 본번의 가장 큰 필지.
      리중심 · 읍면동중심 = 지번이 없거나(○○리 일원) 못 찾아 그 리(읍면동) 필지들의 가운데 — 지도 표시용 근사, 판정은 읍면동 최대 칸(app/geocode.py APPROX).
      리 이름이 위키에 틀리게(용탸라) 적혔으면 같은 읍면동에서 가장 비슷한 이름으로 — 메모에 남긴다.
필요: pip install pyshp pyproj (개발용 — 서버에는 필요 없다. 서버는 결과 csv 만 읽는다)
지적도는 분기마다 바뀐다 — 지구 자료가 바뀌거나 반년에 한 번쯤 새로 받아 다시 돌린다.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GU = {"의창구", "성산구", "마산합포구", "마산회원구", "진해구"}


def codes(path: str) -> dict[str, str]:
    """법정동코드 전체자료(탭, cp949) → 경남 '존재' 리 · 동 이름 → 코드."""
    out = {}
    raw = Path(path).read_bytes()
    for enc in ("cp949", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    for ln in text.splitlines()[1:]:
        p = ln.split("\t")
        if len(p) >= 3 and p[0].startswith("48") and p[2].strip() == "존재" and not p[0].endswith("00000"):
            out[p[1].strip()] = p[0].strip()
    return out


DASH = ("", "–", "-")


def norm(w: dict) -> dict:
    """위키 칸 바로잡기 — '삼랑 진읍' 띄어쓰기, '고례리산 | 555'(산이 리에 붙음), 한 칸씩 밀린 줄('덕곡리 | 93-1 | –')."""
    w = {**w, **{k: (w.get(k) or "").strip() for k in ("읍면동", "리", "지번")}}
    w["읍면동"] = w["읍면동"].replace(" ", "")
    if w["리"].endswith("리산"):
        w["리"], w["지번"] = w["리"][:-1], "산" + w["지번"]
    if re.fullmatch(r"산?\d+(-\d+)?", w["리"]) and w["지번"] in DASH:        # 리 칸에 지번이 들어 있다
        w["리"], w["지번"] = "", w["리"]
        if w["읍면동"].endswith("리"):                                         # 읍면동 칸에 리가 들어 있다
            w["읍면동"], w["리"] = "", w["읍면동"]
    elif w["리"] in DASH and re.fullmatch(r"산?\d+(-\d+)?", w["지번"]):
        w["리"] = ""
    return w


def _emd_variants(emd: str) -> list[str]:
    """'제황 산동' · '양덕 일동'(행정동) · '신포동 일가' · '장대동 옥봉동'(둘) 같은 위키 표기 → 법정동 이름 후보."""
    out = []
    for e in (emd, emd.replace(" ", ""), emd.split()[0] if emd.split() else ""):
        e = e.replace("일가", "1가").replace("이가", "2가").replace("일동", "1동").replace("이동", "2동")
        first = re.match(r"(.+?[동읍면가])(?=.)", e)              # '장대동옥봉동' → '장대동'
        out += [e, re.sub(r"\d+동$", "동", e)] + ([first.group(1)] if first else [])
    return list(dict.fromkeys(x for x in out if x))


def dong_code(w: dict, cd: dict[str, str]) -> str:
    """지구 → 법정동(리) 코드. 위키에 '광도 · 죽림'처럼 면 · 리를 줄여 쓴 곳이 있어 붙여 본다."""
    sg, emd, ri = (w.get(k, "").strip() for k in ("시군", "읍면동", "리"))
    ri = "" if ri in ("–", "-") else re.split(r"[\s~,]+", ri)[0]
    for e in [x for v in _emd_variants(emd) for x in [v] + ([v + s for s in ("면", "읍", "동")] if v[-1] not in "읍면동가로" else [])] or [""]:
        for r in [ri] + ([ri + "리", ri + "동"] if ri and ri[-1] not in "리동가" else [ri + "리"] if ri.endswith("동") else []):   # '우동' → 우동리
            c = _dong(sg, e, r, w, cd)
            if c:
                return c
    return ""


def dong_fuzzy(w: dict, cd: dict[str, str]) -> tuple[str, str]:
    """리 이름 오타(용탸라 · 작전리) — 같은 시군 · 읍면동의 리 중 가장 비슷한 것. (코드, 메모) 또는 ('', '')."""
    import difflib
    sg, emd, ri = (w.get(k, "").strip() for k in ("시군", "읍면동", "리"))
    if not ri or ri in ("–", "-"):
        return "", ""
    for e in _emd_variants(emd):
        pre = [n for n in cd if n.startswith(f"경상남도 {sg} ") and f" {e} " in n + " " and n.split()[-1] != e]
        names = [n.split()[-1] for n in pre]
        got = difflib.get_close_matches(ri, names, n=1, cutoff=0.5) or [x for x in difflib.get_close_matches(ri, names, n=3, cutoff=0.3) if x[0] == ri[0]][:1]
        if got:
            n = next(x for x in pre if x.split()[-1] == got[0])
            return cd[n], f"리 이름 비슷(오타 의심) — 위키 '{ri}' · 가까운 리 '{got[0]}'"   # 확정 표현은 쓰지 않는다(위키 검토 11-07)
    return "", ""


def _dong(sg: str, emd: str, ri: str, w: dict, cd: dict[str, str]) -> str:
    """창원은 구가 지구명 칸에 있거나 없다 — 없으면 이름 끝이 같은 것 중 하나뿐일 때."""
    tail = f" {emd} {ri}".rstrip() if emd and ri else f" {emd or ri}"
    gu = (w.get("지구명") or "").strip()
    if gu in GU and f"경상남도 {sg} {gu}{tail}" in cd:
        return cd[f"경상남도 {sg} {gu}{tail}"]
    if f"경상남도 {sg}{tail}" in cd:
        return cd[f"경상남도 {sg}{tail}"]
    hit = [c for n, c in cd.items() if n.startswith(f"경상남도 {sg} ") and n.endswith(tail)]
    if len(hit) == 1:
        return hit[0]
    if ri:                                                   # 행정동 이름이 법정동과 다를 때 — 시군 안에서 리 이름만으로
        hit = [c for n, c in cd.items() if n.startswith(f"경상남도 {sg} ") and n.endswith(f" {ri}")]
        if len(hit) == 1:
            return hit[0]
    return ""


def jibuns(s: str) -> tuple[str, list[tuple[int, int]]]:
    """위키 지번 → ('1' 일반 · '2' 산, [(본번, 부번) 후보]). 대시가 빠진 숫자(84939)는 나눌 수 있는 곳을 모두 후보로."""
    s = (s or "").replace("번지", "").strip()
    m = re.match(r"(산)?\s*(\d+)(?:-(\d+))?", s)
    if not m:
        return "1", []
    san = "2" if m.group(1) else "1"
    a, b = m.group(2), m.group(3)
    if b is not None:
        return san, [(int(a), int(b))]
    cands = [(int(a), 0)]
    if len(a) >= 4:                                          # 본번 · 부번이 붙어 버린 것 — 본번 두 자리 이상, 부번 앞자리 0 아님
        cands += [(int(a[:i]), int(a[i:])) for i in range(2, len(a)) if a[i] != "0" and int(a[:i]) <= 9999 and int(a[i:]) <= 9999]
    return san, cands


def pnu(dc: str, san: str, a: int, b: int) -> str:
    return f"{dc}{san}{a:04d}{b:04d}"


def centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """다각형 넓이 중심(바깥 고리). 넓이가 0 이면 점들의 평균."""
    s = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        c = x0 * y1 - x1 * y0
        s += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(s) < 1e-9:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * s), cy / (3 * s)


def area(pts) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def main(shp: str, code_txt: str) -> int:
    import shapefile
    from pyproj import Transformer

    from app import ai
    src = ai.wiki() / "data" / "인명피해 우려지역.csv"
    rows = [w for w in csv.DictReader(open(src, encoding="utf-8-sig", newline="")) if w.get("지역ID")]
    cd = codes(code_txt)
    plan, out, area_of = {}, {}, {}                       # area_of: 지번으로 못 가면 그 리(읍면동) 가운데로 — {지역ID: (코드, 메모)}
    for w in map(norm, rows):
        dc, memo = dong_code(w, cd), ""
        if not dc:
            dc, memo = dong_fuzzy(w, cd)
        san, cands = jibuns(w.get("지번", ""))
        if not dc:
            out[w["지역ID"]] = {"지역ID": w["지역ID"], "메모": "법정동 못 찾음"}
            continue
        area_of[w["지역ID"]] = (dc, memo)
        if cands:
            plan[w["지역ID"]] = (dc, san, cands)
    want = {pnu(dc, san, a, b) for dc, san, cs in plan.values() for a, b in cs}
    bonbun = {pnu(dc, san, cs[0][0], 0)[:15] for dc, san, cs in plan.values()}   # 본번까지(부번 필지가 없을 때)
    print(f"지구 {len(rows)}곳 · 법정동 찾음 {len(plan)} · 찾을 PNU {len(want)} — 지적도 읽는 중(몇 분)…")

    r = shapefile.Reader(shp.removesuffix(".shp"), encoding="euc-kr")
    hit, near = {}, {}
    # 리 코드(…00 이 아닌 끝) 는 그 리, 읍면동 코드(끝 00) 는 앞 8자리로 그 읍면동 전부
    zone = {dc if not dc.endswith("00") else dc[:8] for dc, _ in area_of.values()}
    zpick: dict[str, list] = {}
    for i, rec in enumerate(r.iterRecords(fields=["PNU", "JIBUN"])):
        p = rec["PNU"]
        for z in (p[:10], p[:8]):
            if z in zone and len(zpick.setdefault(z, [])) < 600:  # 리마다 600필지면 가운데가 충분히 선다
                zpick[z].append(i)
        if p in want:
            hit[p] = (i, rec["JIBUN"])
        if p[:15] in bonbun:
            near.setdefault(p[:15], []).append((i, rec["JIBUN"]))
        if i % 1_000_000 == 0 and i:
            print(f"  {i:,}필지…")

    tf = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
    feats = []

    def put(rid: str, i: int, p: str, jb: str, how: str, memo: str = "") -> None:
        sh = r.shape(i)
        parts = list(sh.parts) + [len(sh.points)]
        rings = [sh.points[a:b] for a, b in zip(parts, parts[1:])]
        outer = max(rings, key=area)
        x, y = centroid(outer)
        lon, lat = tf.transform(x, y)
        out[rid] = {"지역ID": rid, "위도": f"{lat:.6f}", "경도": f"{lon:.6f}", "PNU": p, "지번": jb, "방법": how, "메모": memo}
        ring = [[round(a, 6), round(b, 6)] for a, b in (tf.transform(px, py) for px, py in outer)]
        feats.append({"type": "Feature", "properties": {"id": rid, "pnu": p, "how": how},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})

    for rid, (dc, san, cs) in plan.items():
        got = [(pnu(dc, san, a, b), a, b) for a, b in cs if pnu(dc, san, a, b) in hit]
        if got and got[0][0] == pnu(dc, san, *cs[0]):              # 적힌 지번 그대로 있으면 그것 — 대시를 끼워 보는 건 없을 때만
            got = got[:1]
        if len(got) == 1:
            p = got[0][0]
            put(rid, hit[p][0], p, hit[p][1], "정확" if p == pnu(dc, san, *cs[0]) else "대시복원")
        elif len(got) > 1:
            p = got[0][0]
            put(rid, hit[p][0], p, hit[p][1], "확인 필요", "지번 후보 " + " · ".join(f"{a}-{b}" if b else str(a) for _, a, b in got))
        elif near.get(pnu(dc, san, cs[0][0], 0)[:15]):
            i, jb = max(near[pnu(dc, san, cs[0][0], 0)[:15]], key=lambda t: area(r.shape(t[0]).points))
            put(rid, i, r.record(i)["PNU"], jb, "본번근사", "그 지번 필지가 없어(분할 · 합병) 같은 본번에서")
        else:
            out[rid] = {"지역ID": rid, "메모": "지적도에 그 지번 없음"}
    # 지번이 없거나 못 찾은 곳 — 그 리(읍면동) 필지들 가운데(바운딩 상자 가운데의 평균)
    for rid, (dc, memo) in area_of.items():
        if out.get(rid, {}).get("위도"):
            continue
        z = dc if not dc.endswith("00") else dc[:8]
        idx = zpick.get(z) or []
        if not idx:
            continue
        cs = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in (r.shape(i).bbox for i in idx)]
        x, y = sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs)
        lon, lat = tf.transform(x, y)
        how = "리중심" if not dc.endswith("00") else "읍면동중심"
        out[rid] = {"지역ID": rid, "위도": f"{lat:.6f}", "경도": f"{lon:.6f}", "PNU": "", "지번": "", "방법": how,
                    "메모": " · ".join(x for x in (memo, f"지번으로 못 찾아 그 {how[:-2]} 필지 {len(cs)}곳 가운데 — 지도 표시용") if x)}

    d = ai.wiki() / "data"
    cols = ["지역ID", "위도", "경도", "PNU", "지번", "방법", "메모"]
    with open(d / "지구좌표.csv", "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(out.get(w["지역ID"], {"지역ID": w["지역ID"]}) for w in rows)
    (d / "지구필지.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), "utf-8")
    from collections import Counter
    c = Counter(v.get("방법") or v.get("메모", "?") for v in out.values())
    print("결과:", " · ".join(f"{k} {n}" for k, n in c.most_common()))
    return 0


def selftest() -> None:
    assert jibuns("산83") == ("2", [(83, 0)])
    assert jibuns("1087-1") == ("1", [(1087, 1)])
    assert jibuns("산58번지") == ("2", [(58, 0)])
    s, c = jibuns("84939")
    assert s == "1" and (84939, 0) in c and (849, 39) in c and (8493, 9) in c and (84, 939) in c
    assert jibuns("–") == ("1", [])
    cd = {"경상남도 창원시 의창구 북면 무곡리": "4812132021", "경상남도 창원시 마산회원구 내서읍 중리": "4812725021",
          "경상남도 창녕군 창녕읍 말흘리": "4874025030", "경상남도 밀양시 삼문동": "4827010500"}
    assert dong_code({"시군": "창원시", "지구명": "의창구", "읍면동": "북면", "리": "무곡리"}, cd) == "4812132021"
    assert dong_code({"시군": "창원시", "지구명": "", "읍면동": "내서읍", "리": "중리"}, cd) == "4812725021"
    assert dong_code({"시군": "밀양시", "지구명": "", "읍면동": "삼문동", "리": "–"}, cd) == "4827010500"
    cd["경상남도 통영시 광도면 죽림리"] = "4822036021"
    assert dong_code({"시군": "통영시", "지구명": "광도죽림지구", "읍면동": "광도", "리": "죽림"}, cd) == "4822036021"
    assert pnu("4874025030", "1", 849, 39) == "4874025030108490039"
    n = norm({"읍면동": "단장면", "리": "고례리산", "지번": "555"})
    assert (n["리"], n["지번"]) == ("고례리", "산555")
    n = norm({"읍면동": "덕곡리", "리": "93-1", "지번": "–"})
    assert (n["읍면동"], n["리"], n["지번"]) == ("", "덕곡리", "93-1")
    n = norm({"읍면동": "산호동", "리": "346", "지번": "–"})
    assert (n["읍면동"], n["리"], n["지번"]) == ("산호동", "", "346")
    assert norm({"읍면동": "삼랑 진읍", "리": "용전리", "지번": "1"})["읍면동"] == "삼랑진읍"
    assert centroid([(0, 0), (2, 0), (2, 2), (0, 2)]) == (1.0, 1.0)
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main(sys.argv[1], sys.argv[2]))
