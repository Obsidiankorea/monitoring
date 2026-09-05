"""스방(경남 스마트 통합 방재시스템, 내부망) 호출 한 곳.

기상청과 **다른 서버·다른 관측망**이다. 경남 자체 AWS 212개소 + 기상청 53개소를
합쳐 시군 평균을 내므로, 기상청 대표지점 값과 다르다. 섞지 않고 따로 저장한다.

여기 담긴 것은 전부 옆 프로그램(`code/bangjae/bangjae.py`)에서 실측으로 배운 것이다.

⚠️ **로그인이 필요할 때가 있다(2026-08-29 부터).** 그런데 로그인 안 된 요청에 서버가
   로그인 화면이 아니라 **HTTP 200 + `[]`** 를 준다. 그래서 '빈 배열'을
   '자료 없음'으로 보면 안 되고 **로그인 신호로** 봐야 한다(그걸 놓쳐서 엉뚱한
   데서 `KeyError` 로 터진 적이 있다).
⚠️ **계정이 없다고 미리 건너뛰지 않는다.** 부르는 자리에 따라 로그인 없이도 그대로
   온다 — 상황실 내부망 PC 에서 실측(2026-09-05): `dt090/list3` 18개 시군,
   `dt096/list` 532줄이 계정 없이 왔다. 계정 유무로 앞에서 막으면 **되는 곳에서도
   안 된다.** 그래서 일단 부르고, `[]` 가 올 때만 로그인한다.
⚠️ 세션 쿠키 이름이 `JSESSIONID` 가 아니라 **`PLATFORM3_JSESSIONID`** 다.
⚠️ `dt090/list3` 하나가 붐빌 때 20초 가까이 걸린다. 타임아웃을 넉넉히 준다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from .config import KEYS, VERIFY_SSL

log = logging.getLogger("bangjae")

BASE = os.environ.get("BANGJAE_URL") or KEYS.get("BANGJAE_BASE") or "http://112.100.10.186:8080"
TIMEOUT = 60.0        # list3 가 느리다
RETRY = 1


class BangjaeError(RuntimeError):
    """스방 조회 실패. '자료 없음'과 같이 다루지 않는다."""


#: 다우지점 표기 '상동(3.0)' → ('상동', 3.0)
_DAW_RE = re.compile(r"^\s*(.+?)\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)\s*$")

#: 조회 시각을 지금보다 이만큼 뒤로 적는다. 아래 `as_of()` 설명 참고.
LAG_MINUTES = 5


#: 관제순 짧은 이름. 스방은 '거창'과 '거창군'을 섞어 준다.
_SHORT = ("창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령",
          "함안", "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천")


def _short_sigun(name) -> str:
    """'거창군'·'거창' 둘 다 '거창'으로. 관리주체마다 표기가 달라서 필요하다."""
    s = str(name or "").strip()
    if s in _SHORT:
        return s
    return s[:-1] if s[:-1] in _SHORT and s[-1:] in ("시", "군") else s


def _parse_daw(s) -> tuple[str | None, float | None]:
    m = _DAW_RE.match(str(s or ""))
    if not m:
        return None, None
    try:
        return m.group(1), float(m.group(2))
    except ValueError:
        return m.group(1), None


def as_of(now: datetime | None = None) -> tuple[datetime, int]:
    """(자료 기준시각, 조회에 쓸 toTime).

    ⚠️ 스방은 `toTime=H` 를 '**H 시까지**' 로 본다. 지금이 06:47 인데 06 으로 물으면
       06:00 에서 잘린 값이 오고, **지금 오는 비가 빠진다.**
       그래서 **다음 정시(07)** 로 물어 지금까지 쌓인 값을 받는다.
       다만 그 자료는 07시치가 아니라 **지금까지**의 값이므로, 기준시각은
       07시가 아니라 `지금 - 5분`(06:42)으로 적는다 — 없는 시각을 적지 않으려고.
       (옆 프로그램 bangjae 도 같은 규칙을 쓴다)

    23시대에는 다음 정시가 없으므로 23 으로 둔다(= 그날 끝까지, 지금 포함).
    """
    now = now or datetime.now()
    to_time = min(23, now.hour + 1)
    stamp = now - timedelta(minutes=LAG_MINUTES)
    # 자정 직후에 어제로 넘어가지 않게(같은 날 안에서만 뒤로 민다)
    floor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(stamp, floor), to_time


def _sha1(pw: str) -> str:
    """사이트의 CryptoJS.SHA1(pw) 과 같은 값 — UTF-8 SHA1 hex 소문자."""
    return hashlib.sha1(pw.encode("utf-8")).hexdigest()


def credentials() -> tuple[str, str] | None:
    """(아이디, 비밀번호). 없으면 None.

    찾는 차례 —
      ① `config/api_keys.txt` 의 `BANGJAE_ID` / `BANGJAE_PW`(또는 같은 이름 환경변수)
      ② 옆 프로그램이 **DPAPI 로 잠가 둔** 계정 파일(`bangjae/bangjae_account.json`)

    ②를 먼저 두지 않는 이유: 이 앱의 설정이 우선이어야 예상대로 움직인다.
    ②가 있으면 비밀번호를 평문으로 어디에도 안 적어도 된다(같은 PC·같은 계정에서만 풀린다).
    """
    i, p = KEYS.get("BANGJAE_ID"), KEYS.get("BANGJAE_PW")
    if i and p:
        return str(i), str(p)

    folder = Path(os.environ.get("BANGJAE_DIR",
                                 Path.home() / "code" / "bangjae"))
    f = folder / "bangjae_account.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:                       # noqa: BLE001
        log.warning("계정 파일을 읽지 못했다: %s", e)
        return None
    uid, enc, plain = d.get("id"), d.get("pw_dpapi"), d.get("pw")
    if uid and enc:
        try:
            import base64
            import win32crypt
            pw = win32crypt.CryptUnprotectData(base64.b64decode(enc), None,
                                               None, None, 0)[1].decode("utf-8")
            return str(uid), pw
        except Exception as e:                   # noqa: BLE001
            log.warning("계정 파일을 풀지 못했다(다른 PC/계정?): %s", e)
            return None
    return (str(uid), str(plain)) if uid and plain else None


def available() -> bool:
    """계정이 있는가. **수집을 막는 데 쓰지 않는다** — 위 설명 참고."""
    return credentials() is not None


class Client:
    """세션 하나를 들고 여러 번 부른다. 로그인은 필요할 때만."""

    def __init__(self) -> None:
        # 연결만 짧게 끊는다 — 내부망 밖에서 부르면 이 IP가 응답을 안 해 60초를 통째로
        # 기다린다(수집 주기가 10분인데 한 번이 2분을 먹는다).
        # verify: 내부망 장비가 인증서를 갈아 끼운다(config.DISABLE_SSL_VERIFICATION).
        self._c = httpx.AsyncClient(base_url=BASE, follow_redirects=True,
                                    verify=VERIFY_SSL,
                                    timeout=httpx.Timeout(TIMEOUT, connect=5.0))

    async def aclose(self) -> None:
        await self._c.aclose()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    @property
    def logged_in(self) -> bool:
        # 쿠키 앞가지가 바뀔 수 있으니 이름에 들어 있기만 하면 인정한다.
        return any("JSESSIONID" in c.name for c in self._c.cookies.jar)

    async def login(self) -> None:
        cred = credentials()
        if not cred:
            raise BangjaeError(
                "스방 계정이 없다. config/api_keys.txt 에 BANGJAE_ID/BANGJAE_PW 를 넣거나, "
                "같은 PC 의 bangjae 프로그램에서 [설정]으로 계정을 저장한다.")
        uid, pw = cred
        r = await self._c.post("/loginProcess",
                               json={"USER_ID": uid, "USER_PWD": _sha1(pw)})
        r.raise_for_status()
        try:
            d = r.json()
        except ValueError:
            raise BangjaeError("로그인 응답이 JSON 이 아니다 — 내부망 연결을 확인한다") from None
        if not d.get("USER_OK"):
            if str(d.get("IS_LOCK", "")).upper() == "Y":
                raise BangjaeError("로그인 실패가 쌓여 계정이 잠겼다")
            raise BangjaeError("아이디 또는 비밀번호가 맞지 않는다")

    async def get(self, path: str, **params) -> list:
        """GET 한 번. **빈 배열이면 로그인하고 한 번 다시 친다.**"""
        last: Exception | None = None
        for attempt in range(RETRY + 1):
            try:
                r = await self._c.get(path, params=params)
                r.raise_for_status()
                out = r.json()
                if out == [] and not self.logged_in:
                    await self.login()           # 빈 배열 = 로그인이 필요하다는 뜻
                    r = await self._c.get(path, params=params)
                    r.raise_for_status()
                    out = r.json()
                return out if isinstance(out, list) else []
            except BangjaeError:
                raise
            except Exception as e:               # noqa: BLE001
                last = e
                if attempt < RETRY:
                    await asyncio.sleep(0.8)
        raise BangjaeError(f"{path} 실패: {last}")

    async def sigun_rain(self, start, end, hour: int) -> dict[str, dict]:
        """시군별 **평균 강우량 + 다우지점** {시군: {mm, daw_name, daw_mm}}.

        `dt090/list3`(시·군별 강우량 현황) 한 번이면 둘 다 나온다 —
        `totalsum` 이 기간 누적 평균, `rtu_area` 가 그 시군 다우지점('상동(3.0)' 꼴).
        따로 부르면 두 값의 기준시각이 어긋날 수 있어 한 번에 받는다.

        start/end 는 'YYYYMMDD', hour 는 0~23(그 시각까지).
        """
        rows = await self.get("/dt090/list3", frDate=start, toDate=end,
                              toTime=f"{int(hour):02d}")
        out: dict[str, dict] = {}
        for o in rows:
            name = str(o.get("org_name") or "").strip()
            if not name:
                continue
            try:
                mm = float(o.get("totalsum"))
            except (TypeError, ValueError):
                continue
            daw_name, daw_mm = _parse_daw(o.get("rtu_area"))
            out[name] = {"mm": max(0.0, mm),   # 누적계 보정으로 음수가 실제로 온다
                         "daw_name": daw_name,
                         "daw_mm": None if daw_mm is None else max(0.0, daw_mm)}
        return out

    async def station_hourly(self, day: str) -> list[dict]:
        """하루치 **지점별 시간강우량**. [{stn, name, sigun, mm: [24개]}]

        화면 `보고서 > 시간강우량`(dt096). 지점마다 두 줄이 온다 —
        `gubun='시간'`(시간강우량)과 `gubun='일'`(일누적). 시간 줄만 쓴다.

        ⚠️ `timesNN` 은 시계 시각이 **아니라** toTime 기준 24시간 창이다.
           `toTime=23` 으로 부를 때만 times00=00시 … times23=23시 로 떨어진다.
           그래서 언제나 23 으로 부른다.
        ⚠️ 시각은 **스방 기준**이다 — times07 은 07:00~07:59 다.
           기상청의 07시(06:00~07:00)와 한 칸 어긋난다.

        시군 표기가 관리주체마다 다르게 온다(기상청 '거창군' / 경남 '거창').
        그대로 두면 한 시군이 둘로 갈려 평균이 깨진다. 짧은 이름으로 맞춘다.
        """
        rows = await self.get("/dt096/list", orgCode="", rtuMbdy="total",
                              toDate=str(day), toTime="23")
        out = []
        for r in rows:
            if str(r.get("gubun")) != "시간":
                continue
            stn = str(r.get("lnk_id") or "").strip()
            if not stn:
                continue

            def v(h: int):
                raw = str(r.get(f"times{h:02d}") or "").strip()
                if not raw:
                    return None            # 빈 칸은 결측이다. 0 으로 바꾸지 않는다
                try:
                    return max(0.0, float(raw))
                except ValueError:
                    return None

            out.append({"stn": stn,
                        "name": str(r.get("rtu_name") or "").strip(),
                        "sigun": _short_sigun(r.get("org_name")),
                        "mm": [v(h) for h in range(24)]})
        return out

    async def sigun_average(self, start, end, hour: int) -> dict[str, float]:
        """예전 이름 — {시군: mm} 만 필요할 때."""
        return {k: v["mm"] for k, v in (await self.sigun_rain(start, end, hour)).items()}
