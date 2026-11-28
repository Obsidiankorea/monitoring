"""산림청 산사태정보시스템(sansatai.forest.go.kr) 공개 화면 뒤의 자료를 모두 받아 md 로 정리한다.

    python tools/sansatai_dump.py            받기 + md 만들기
    python tools/sansatai_dump.py --video    첨부 동영상(mp4)도 받는다(기본은 pdf 만)

- 원본 json · 첨부 → data/sansatai/ (git 에 안 올림)
- 정리 md → docs/산사태/현황.md · 피해통계.md · 대피소.md (덮어씀). 받는 길은 docs/산사태/산사태정보시스템.md
로그인 없이 공개 화면이 부르는 주소만 쓴다. 예보 · 예측 · 실황 목록은 '지금 발령 중'만 주고 지난 이력은 없다.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

HOST = "https://sansatai.forest.go.kr"
P = "/mhms_pub/mhms"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "sansatai"
DOCS = ROOT / "docs" / "산사태"
GN = "경상남도"

# 이름 → 주소. 값은 화면 js 에서 그대로 옮겼다(2026-11-28)
ENDPOINTS = {
    "위기경보": "/mhms_pub/mhms/main/landslideWarningList.do",
    "응급복구_위기경보": "/mhms_pub/mhms/forecast/getErctnWarningList.do",
    "메인_예보": "/mhms_pub/mhms/main/landslideForecastData.do",
    "예보발령": P + "/forecast/forecastList.do",
    "예보발령_지도": P + "/forecast/getForecastMapData.do",
    "예측정보": P + "/forecast/expectList.do",
    "예측정보_지도": P + "/forecast/getPrctnInfoMapData.do",
    "실황정보": P + "/forecast/rltmList.do",
    "실황정보_지도": P + "/forecast/getRltmMapData.do",
    "중기예측_시각": "/midterm/tankRainDtm.do",
    "산악기상": P + "/forecast/getmtWeatherList.do",
    "레이더_목록": P + "/forecast/getRadarImageFileNameList.do",
    "강우반영위험도": P + "/lndsInfo/getRealTimeMapView.do",
    "피해통계": P + "/notice/getLandslideStats.do",
    "사방사업통계": P + "/notice/getEcnbsStats.do",
    "대피소": P + "/shelter/shelterList.do?searchAddress=",
    "시도": "/mhms_pub/cmmn/util/getSidoList.do",
    "특보원문": P + "/forecast/getWdrData.do",  # 기상청 특보 그대로 — 대시보드가 이미 받으니 원본만 둔다
}
BOARDS = {"LS_BBS_0000000000004": "간행물", "LS_BBS_0000000000005": "홍보자료", "LS_BBS_0000000000009": "교육영상"}


def get(path, raw=False):
    req = urllib.request.Request(HOST + path, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
            return b if raw else json.loads(b.decode("utf-8"))
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def clean(d):
    return {k: v for k, v in d.items() if v not in (None, "")}


def fetch_all(out, video):
    got, fail = {}, {}
    for name, path in ENDPOINTS.items():
        try:
            if name == "특보원문":
                (out / "특보원문.txt").write_bytes(get(path, raw=True))
                continue
            got[name] = get(path)
            (out / f"{name}.json").write_text(json.dumps(got[name], ensure_ascii=False, indent=1), "utf-8")
        except Exception as e:
            fail[name] = str(e)
    # 자료실 게시판 + 첨부
    posts = []
    files = RAW / "files"
    files.mkdir(parents=True, exist_ok=True)
    for bbs, label in BOARDS.items():
        try:
            j = get(f"{P}/notice/noticePageList.do?bbsId={bbs}&page=1&pageSize=200&searchType=&keyword=")
        except Exception as e:
            fail[label] = str(e)
            continue
        for n in j.get("noticeList") or []:
            att = get(f"{P}/notice/getAttachFileList.do?bbsId={bbs}&nttId={n['nttId']}") or []
            for a in att:
                fn = a.get("orgilFileNm") or a.get("storeFileNm")
                a["_saved"] = None
                if (a.get("fileExtNm") or "").lower() == ".mp4" and not video:
                    continue
                dst = files / fn.replace("/", "_")
                if not dst.exists():
                    dst.write_bytes(get(f"{P}/notice/getAttachFile.do?bbsId={bbs}&nttId={n['nttId']}&attchFileSeq={a['attchFileSeq']}", raw=True))
                a["_saved"] = str(dst.relative_to(ROOT)).replace("\\", "/")
            posts.append({"게시판": label, "제목": n.get("nttSj"), "nttId": n["nttId"], "첨부": [clean(a) for a in att]})
    got["자료실"] = posts
    (out / "자료실.json").write_text(json.dumps(posts, ensure_ascii=False, indent=1), "utf-8")
    return got, fail


def fm(title, summary, stamp):
    return f"---\ntags: [산사태, 산림청, 자동생성]\nsummary: {summary}\nupdated: {stamp}\n출처: \"산림청 산사태정보시스템 sansatai.forest.go.kr (공개 화면)\"\n---\n# {title}\n\n> [!info] `tools/sansatai_dump.py` 가 만든 파일 — 손으로 고치지 않는다. 받는 길은 [[산사태정보시스템]].\n\n"


def rows(items, cols):
    if not items:
        return "_지금 없음_\n"
    head = "| " + " | ".join(c for c, _ in cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(it.get(k) if it.get(k) is not None else "") for _, k in cols) + " |\n" for it in items)


def md_now(g, stamp):
    s = fm("현황", "지금 발령 중인 산사태 위기경보 · 예보 · 예측 · 실황과 분석 시각", stamp)
    s += "## 위기경보\n" + rows(g.get("위기경보"), [("단계", "lndslPhase"), ("지역", "lndslDstrtNm"), ("발령", "lndslFrcstIssueDtm")])
    s += "\n## 응급복구 위기경보\n" + rows(g.get("응급복구_위기경보"), [("단계", "erctnPhase"), ("지역", "lndslDstrtNm"), ("발령", "lndslFrcstIssueDtm")])
    s += "\n## 예보발령 (주의보 · 경보)\n" + rows((g.get("예보발령") or {}).get("list"), [("지역", "lgdngNm"), ("종류", "frcstIssuKindCd"), ("상태", "frcstStatus"), ("첫 발령", "frstFrcstIssuDtm"), ("해제", "lastFrcstRlsDtm")])
    s += "\n## 예측정보 (읍면동)\n" + rows((g.get("예측정보") or {}).get("list"), [("지역", "lgdngNm"), ("종류", "frcstIssuKindCd"), ("분석", "prctnInfoAnlssDtm")])
    s += "\n## 실황정보\n" + rows((g.get("실황정보") or {}).get("list"), [("지역", "lgdngNm"), ("종류", "frcstIssuKindCd"), ("분석", "rltmInfoAnlssDtm")])
    rv = g.get("강우반영위험도") or {}
    tk = g.get("중기예측_시각") or {}
    radar = sorted(g.get("레이더_목록") or [])
    s += "\n## 분석 시각\n| 항목 | 값 |\n|---|---|\n"
    s += f"| 강우반영 산사태위험도 분석 | {rv.get('anlssDtm', '')} |\n"
    s += f"| 중기예측(탱크모델) 강우 기준 | {tk.get('rainDt', '')} (+48시간 {tk.get('regTime48', '')}) |\n"
    s += f"| 레이더 영상 | {len(radar)}장, 마지막 {radar[-1] if radar else ''} |\n"
    s += f"| 산악기상 관측 행 | {len(g.get('산악기상') or [])} |\n"
    return s


def md_stats(g, stamp):
    s = fm("피해통계", "전국 연도별 산사태 피해면적 · 복구비 · 인명피해와 사방사업 통계(시스템 제공분)", stamp)
    st = sorted((g.get("피해통계") or {}).get("data") or [], key=lambda x: x["lndslDmgYr"], reverse=True)
    s += "## 전국 산사태 피해 (연도별)\n| 연도 | 피해면적(ha) | 복구비(백만원) | 그중 국비 | 지방비 | 인명피해(명) |\n|---|---|---|---|---|---|\n"
    for x in st:
        s += f"| {x['lndslDmgYr']} | {x['lndslDmgQntt']:,} | {x['totalRecoveryCost']:,} | {x['lndslDmgRsexpNtexpAmt']:,} | {x['lndslDmgRsexpLgvexAmt']:,} | {x['lndslDmgHmlfCnt']} |\n"
    s += "\n> [!note] 시도 · 시군별 값은 이 시스템에 없다. 경남 값은 위키 「산사태 통계 2015~2024」(연구자료 부록)를 본다.\n"
    ec = (g.get("사방사업통계") or {}).get("data") or []
    s += "\n## 사방사업 (시스템 '산사태 통계' 화면)\n| 구분 | 항목 | 값 |\n|---|---|---|\n"
    for x in ec:
        s += f"| {x['category']} | {x['label']} | {float(x['count']):g} |\n"
    s += "\n> [!warning] 평균 사업기간 단위(일로 보임)와 연도별 건수가 해마다 들쭉날쭉한 까닭은 화면에 설명이 없다 — 확인 안 함.\n"
    return s


def md_shelter(g, stamp):
    sh = (g.get("대피소") or {}).get("shelterList") or []
    s = fm("대피소", "산사태 취약지역 대피소 — 시도별 수, 경남 시군별 수와 목록", stamp)
    sido = Counter((x.get("evctnshlLotnoAddr") or x.get("evctnshlRoadNmAddr") or "?").split()[0] for x in sh)
    s += f"## 시도별 ({len(sh):,}곳)\n| 시도 | 곳 |\n|---|---|\n" + "".join(f"| {k} | {v:,} |\n" for k, v in sido.most_common())
    gn = [x for x in sh if (x.get("evctnshlLotnoAddr") or x.get("evctnshlRoadNmAddr") or "").startswith(GN)]
    # 관리기관 이름은 「경상남도 진주시」 · 「진주시」 · 국유림관리소가 섞여 있어 주소의 시군으로 센다
    sg = Counter((x.get("evctnshlLotnoAddr") or x.get("evctnshlRoadNmAddr")).split()[1] for x in gn)
    s += f"\n## 경남 시군별 ({len(gn):,}곳, 주소 기준)\n| 시군 | 곳 |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in sorted(sg.items()))
    s += "\n## 경남 목록\n| 관리 | 대피소 | 지번 주소 | 경도 | 위도 |\n|---|---|---|---|---|\n"
    for x in sorted(gn, key=lambda x: (x.get("evctnPlaceMnagnNm") or "", x.get("evctnshlLotnoAddr") or "")):
        s += f"| {x.get('evctnPlaceMnagnNm', '')} | {x.get('evctnPlaceNm', '')} | {x.get('evctnshlLotnoAddr') or x.get('evctnshlRoadNmAddr') or ''} | {x.get('evctnPlaceXcrd', '')} | {x.get('evctnPlaceYcrd', '')} |\n"
    return s


def main():
    video = "--video" in sys.argv
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = RAW / datetime.now().strftime("%Y%m%d-%H%M")
    out.mkdir(parents=True, exist_ok=True)
    g, fail = fetch_all(out, video)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "현황.md").write_text(md_now(g, stamp), "utf-8")
    if (g.get("피해통계") or {}).get("data"):
        (DOCS / "피해통계.md").write_text(md_stats(g, stamp), "utf-8")
    if (g.get("대피소") or {}).get("shelterList"):
        (DOCS / "대피소.md").write_text(md_shelter(g, stamp), "utf-8")
    print(f"원본 {out.relative_to(ROOT)} · 받음 {len(g)} · 실패 {len(fail)}")
    for k, v in fail.items():
        print(f"  실패 {k}: {v}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
