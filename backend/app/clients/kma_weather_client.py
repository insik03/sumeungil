"""기상청 관광코스별 관광지 상세 날씨(D18) 클라이언트 — 지역 단위 강수확률(POP).

원천(실호출로 확정, 2026-07-24):
  GET http://apis.data.go.kr/1360000/TourStnInfoService1/getTourStnVilageFcst1
  파라미터: serviceKey, pageNo, numOfRows, dataType(JSON),
            CURRENT_DATE(YYYYMMDDHH), HOUR(예보 리드타임), COURSE_ID(관광코스 id)

실호출로 확인된 item 필드(EUC-KR 응답):
  tm(예보시각 "YYYY-MM-DD HH:MM"), courseId, courseAreaId(10자리 법정동 시도코드),
  courseAreaName, courseName, spotAreaName, spotName, pop(강수확률 %), sky, th3(기온), rhm(습도)

★ 실호출로 확인한 매핑 한계(지어내지 않음 — 08 Q-D18):
  - D18 은 **관광코스(COURSE_ID) 단위**로만 조회된다. 우리 region_code(시군구 법정동)로
    직접 조회하는 파라미터가 없다 → region_code → 대표 COURSE_ID 를 **핀 고정**한다.
  - courseAreaId 는 **2023~24 개편 이전(구) 시도코드**를 쓴다:
      강원=42(신 51), 전북=45(신 52). 부산=26·경북=47 은 동일.
    따라서 강릉/전주는 신코드(51/52) → 구코드(42/45) 변환이 필요하다.
  - 해상도는 **시도(province) 단위**다(courseAreaId=4700000000 = 경북 전체). 특정 시(경주 vs
    다른 경북 시)를 코드로 구분하지 못해, 그 시에 위치한 대표 코스를 골라 근사한다.
  - 4개 데모 지역(경주·강릉·전주·해운대) 모두 대표 코스가 실재해 POP 확보 가능함을 실호출로 확인.
  - 상용 일반화는 코스목록 조회 오퍼레이션으로 region→course 표를 동적 생성해야 한다(핀 고정 대체).

serviceKey 는 params 로만 전달하고 절대 로그에 남기지 않는다(httpx 로거는 main.py 에서 WARNING 억제).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import settings
from ..util.time import now_kst

logger = logging.getLogger("sumeungil.kma_weather")

BASE_URL = "http://apis.data.go.kr/1360000/TourStnInfoService1/getTourStnVilageFcst1"

# ★ 예보 커버 실측(2026-07-31, backend-engineer):
#   CURRENT_DATE=오늘 기준으로 HOUR(리드타임)를 6→240 까지 올려가며 tm(예보시각)을 확인한 결과
#   **오늘+3일**(72시간)이 한계였다. HOUR=96/120/240 은 HOUR=72 와 같은 꼬리(오늘+3일 21:00)를
#   반환한다 → 그 이상은 원천에 데이터가 없다. 중기예보(getMidLandFcst/getMidTa)와 격자
#   단기예보(VilageFcstInfoService_2.0)는 같은 키로 403(미승인)이라 대안이 없다.
#   따라서 "날씨"는 오늘~+3일만 제공하고 그 밖은 정직하게 미제공 표기한다(값 생성 금지).
FORECAST_MAX_DAYS_AHEAD = 3

# region_code(시군구 법정동) → 실호출로 검증한 대표 COURSE_ID 후보(앞에서부터 시도).
# 여러 개 두는 이유: 특정 코스가 계절/개편으로 빠져도 다음 후보로 폴백(단일 핀 취약성 완화).
# 2026-07-31 additive: COURSE_ID 1~360 전수 스윕으로 9권역 대표 코스를 확정해 5곳을 추가했다
# (regions/nationwide.py 가 단일 소스, 아래는 그 사본이 아니라 rerank 날씨용 확장이다).
REGION_COURSE_IDS: dict[str, list[int]] = {
    "26350": [294],            # 해운대(부산 26) — 부산 자연·체험 코스
    "47130": [113, 121, 259],  # 경주(경북 47)
    "51150": [79, 80],         # 강릉(강원 구 42)
    "52111": [94, 95, 96],     # 전주(전북 구 45)
    "11110": [55, 53, 58],     # 서울 종로(11) — 명동·인사동 등 자유여행코스
    "43111": [6, 5, 258],      # 청주 상당구(충북 43)
    "44150": [292, 84, 9],     # 공주(충남 44) — 공주 시티투어
    "46130": [260, 106, 291],  # 여수(전남 46, 원천 area 12)
    "50110": [166, 163, 50],   # 제주시(50) — 시티투어
    # QA 약식(2026-07-31) M-2 대응 — 플래너의 17개 시도 칩 중 8개가 코스 미매핑이라 오늘 날짜에도
    # 날씨가 영구 미제공이었다. 코스 카탈로그 1~360 전수 스윕(응답 324개)으로 각 시도 실재 코스를
    # 확인해 추가했다(오케스트레이터 직접 실측, 코스명·지점명 대조).
    "27110": [311, 312, 313],  # 대구 중구(27)
    "28185": [26, 339, 340],   # 인천 연수구(28)
    "29110": [31, 106],        # 광주 동구(29) — 원천이 '전남광주통합특별시'로 묶어 담양·목포 코스 사용
    "30110": [341],            # 대전 동구(30)
    "31110": [343, 344, 345],  # 울산 중구(31)
    "36110": [270, 346, 347],  # 세종(36)
    "41111": [13, 17, 14],     # 수원 장안구(경기 41) — 가평·양주 등 경기 코스
    "48220": [177, 178, 185],  # 통영(경남 48)
}


@dataclass(frozen=True)
class CourseWeather:
    """D18 예보 1블록 요약(같은 tm 안의 여러 스팟을 하나로 접은 값)."""

    tm: str                 # 예보시각 "YYYY-MM-DD HH:MM"
    pop: int | None         # 강수확률 % — 같은 tm 스팟들 중 **최대**(보수적)
    temp_c: float | None    # 기온 ℃ — 같은 tm 스팟들의 평균(소수 1자리)


class KmaWeatherError(Exception):
    """D18 호출/파싱 실패."""


async def fetch_course_pop(course_id: int, hour: int = 6) -> int | None:
    """대표 코스의 **근시점(가장 이른 tm) 최대 강수확률(POP)** 을 반환. 없으면 None.

    보수적으로 근시점 여러 스팟 중 최대 POP 을 취한다(한 곳이라도 비 예보면 실내 우선 판단).
    호출/파싱 실패는 KmaWeatherError. serviceKey 는 로그에 남기지 않는다.
    """
    rows = await _fetch_rows(course_id, hour, num_of_rows=30)
    return _earliest_max_pop(rows)


async def fetch_course_weather(
    course_id: int, hour: int = 6, timeout_sec: float | None = None
) -> CourseWeather | None:
    """근시점(가장 이른 tm) 블록의 POP·기온 요약. 행이 없으면 None.

    fetch_course_pop 과 같은 원천/같은 tm 선택 규칙을 쓴다(판정 일관성). 기온은 지어내지 않는다 —
    th3 가 하나도 없으면 temp_c=None 으로 둔다.
    """
    rows = await _fetch_rows(course_id, hour, num_of_rows=60, timeout_sec=timeout_sec)
    if not rows:
        return None
    tms = sorted({str(r.get("tm", "")) for r in rows if r.get("tm")})
    if not tms:
        return None
    return _summarize(rows, tms[0])


async def fetch_course_weather_for_date(
    course_id: int, date_iso: str, hour: int, timeout_sec: float | None = None
) -> CourseWeather | None:
    """특정 날짜(YYYY-MM-DD)의 예보 요약. 그 날짜 행이 없으면 None(빈 값 생성 금지).

    HOUR(리드타임)는 호출자가 계산해 넘긴다 — 원천은 HOUR 주변의 시간 윈도우를 돌려주므로
    요청한 날짜 행이 없을 수 있다. 그때 None 을 받는 쪽이 다른 HOUR 로 한 번 더 시도한다.
    """
    rows = await _fetch_rows(course_id, hour, num_of_rows=500, timeout_sec=timeout_sec)
    same_day = [r for r in rows if str(r.get("tm", "")).startswith(date_iso)]
    if not same_day:
        return None
    # 같은 날짜 안에서는 **낮 시간대(12:00 에 가장 가까운 tm)** 를 대표로 쓴다(여행 시간대 기준).
    tms = sorted({str(r.get("tm", "")) for r in same_day})
    target = min(tms, key=lambda t: abs(int(t[11:13]) - 12) if len(t) >= 13 else 99)
    return _summarize(same_day, target)


async def _fetch_rows(
    course_id: int, hour: int, num_of_rows: int, timeout_sec: float | None = None
) -> list[dict]:
    """D18 1회 호출 → item 리스트. 호출/파싱 실패는 KmaWeatherError.

    timeout_sec 를 주면 그 값을 쓴다(보드/전망처럼 캐시가 길어 '한 번 잘 받는' 게 중요한
    경로용). 미지정이면 rerank 경로와 같은 settings.weather_timeout_sec.
    """
    cur = now_kst().strftime("%Y%m%d%H")
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "pageNo": "1",
        "numOfRows": str(num_of_rows),
        "dataType": "JSON",
        "CURRENT_DATE": cur,
        "HOUR": str(hour),
        "COURSE_ID": str(course_id),
    }
    timeout = timeout_sec if timeout_sec is not None else settings.weather_timeout_sec
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(BASE_URL, params=params)
    except httpx.HTTPError as exc:
        # 타임아웃 예외는 str(exc) 가 빈 문자열이라 클래스명을 함께 남긴다(운영 진단용).
        logger.warning("D18 호출 실패(course=%s): %s %s", course_id, type(exc).__name__, exc)
        raise KmaWeatherError(f"upstream request failed: {type(exc).__name__} {exc}") from exc

    if resp.status_code != 200:
        logger.warning("D18 비정상 상태코드 %s (course=%s)", resp.status_code, course_id)
        raise KmaWeatherError(f"upstream status {resp.status_code}")

    resp.encoding = "euc-kr"  # 원천은 EUC-KR 로 응답
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("D18 응답 JSON 파싱 실패: %s", resp.text[:120])
        raise KmaWeatherError("upstream returned non-JSON body") from exc

    return _parse_items(data)


def _summarize(rows: list[dict], tm: str) -> CourseWeather:
    """같은 tm 행들을 하나로 접는다: POP=최대(보수적), 기온=평균(소수 1자리)."""
    pops: list[int] = []
    temps: list[float] = []
    for r in rows:
        if str(r.get("tm", "")) != tm:
            continue
        pop = r.get("pop")
        if pop is not None:
            try:
                pops.append(int(pop))
            except (TypeError, ValueError):
                pass
        th3 = r.get("th3")
        if th3 is not None:
            try:
                temps.append(float(th3))
            except (TypeError, ValueError):
                pass
    return CourseWeather(
        tm=tm,
        pop=max(pops) if pops else None,
        temp_c=round(sum(temps) / len(temps), 1) if temps else None,
    )


def _parse_items(data: dict) -> list[dict]:
    if "response" not in data:
        raise KmaWeatherError(f"flat error resultCode={data.get('resultCode')}")
    header = data["response"].get("header", {})
    code = header.get("resultCode")
    if code not in ("00", "0000"):
        raise KmaWeatherError(f"header resultCode={code} msg={header.get('resultMsg', '')}")
    body = data["response"].get("body", {})
    items = body.get("items")
    if not items:
        return []
    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return []
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return item
    return []


def _earliest_max_pop(rows: list[dict]) -> int | None:
    """가장 이른 예보시각(tm) 블록의 최대 POP(정수). POP 없으면 None."""
    if not rows:
        return None
    tms = [str(r.get("tm", "")) for r in rows if r.get("tm")]
    if not tms:
        return None
    earliest = min(tms)
    pops: list[int] = []
    for r in rows:
        if str(r.get("tm", "")) != earliest:
            continue
        pop = r.get("pop")
        if pop is None:
            continue
        try:
            pops.append(int(pop))
        except (TypeError, ValueError):
            continue
    if not pops:
        return None
    return max(pops)
