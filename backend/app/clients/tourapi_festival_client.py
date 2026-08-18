"""한국관광공사 국문 관광정보 서비스(KorService2) 축제/공연/행사 클라이언트 — searchFestival2.

원천: GET https://apis.data.go.kr/B551011/KorService2/searchFestival2
  - areaCode(+선택 sigunguCode) 지역의 축제 목록을 조회한다(콘텐츠타입 15=행사/공연/축제).
  - eventStartDate(YYYYMMDD) 파라미터는 "그 날짜 이후로도 진행/예정인" 축제를 준다.
    실호출로 확정(2026-07-25, backend-engineer): 필터는 **eventEndDate >= eventStartDate 파라미터**다.
    (예: eventStartDate=20260210 → eventenddate=20260222 인 축제는 나오고, 20260201 에 끝난 축제는 빠짐.
     eventstartdate 가 파라미터보다 과거여도 종료일이 파라미터 이후면 나온다 → 진행중 축제 포함.)
    따라서 eventStartDate=오늘 을 넘기면 "진행중 + 예정" 축제만 온다(이미 끝난 축제는 절대 안 옴).

접근성(실호출 확정, 2026-07-25):
  - **기존 PUBLIC_DATA_API_KEY 로 접근 가능**(resultCode=0000, 새 키·유료전환 불필요).
  - 응답은 detailCommon2/areaBasedList2 와 동일한 {response:{header,body}} envelope. UTF-8.
  - 데이터 없음(해당 조건 축제 0건)이면 body.items == "" → 빈 리스트(정상).
  - 실호출 예: areaCode=6(부산) eventStartDate=20260101 →
    "광복로 겨울빛 트리축제" eventstartdate=20251205 eventenddate=20260222 firstimage(http://tong...) 등 4건.

**areaCode 필터 사망 (2026-07-29 실호출 확인, backend-engineer)**:
  eventStartDate=20260729 기준으로 areaCode 를 넘기면 전 지역 totalCount=0 인데,
  areaCode 를 빼면 totalCount=198 이 나온다. 수집한 198건의 `areacode` 필드를 보면
  197건이 **빈 문자열**이고, 대신 `lDongRegnCd`(2자리 시도) + `lDongSignguCd`(3자리 시군구)
  법정동 코드가 198건 전부 채워져 있다. 즉 KTO 가 축제 레코드의 지역 표기를 법정동 코드로
  이관하면서 areaCode 색인이 비어버린 것 → areaCode 로 거르면 최신 축제가 통째로 사라진다.
  (홈 축제 섹션이 "정보 없음" 이던 진짜 원인. 스냅샷 노후화가 아니었다.)
  → 대응: `fetch_all_festivals()` 로 **전국 1회 스윕**한 뒤 lDong 코드로 메모리 필터한다.
     법정동 5자리(=우리 region_code)와 정확히 같은 체계라 매칭이 1:1이다.

serviceKey 는 params 로만 전달하고 로그에 남기지 않는다(main.py 에서 httpx/httpcore 로거를
WARNING 이상으로 억제해 정상 호출 URL=시크릿 누출을 막는다). KTO/detail 클라이언트와 동일 정책.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..util.redact import redact_secrets

logger = logging.getLogger("sumeungil.tourapi.festival")

BASE_URL = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"


class TourApiFestivalError(Exception):
    """원천 API 호출/파싱 실패."""


async def fetch_festivals(
    area_code: str,
    event_start_date: str,
    sigungu_code: str | None = None,
    num_of_rows: int = 30,
    page_no: int = 1,
) -> list[dict]:
    """searchFestival2 를 호출해 원본 축제 item dict 리스트를 반환.

    데이터가 없으면 빈 리스트(정상). 호출/파싱 실패 시 TourApiFestivalError.
    반환 item 은 원본 키(title/eventstartdate/eventenddate/addr1/firstimage 등)를 그대로 담는다 —
    날짜/장소 가공은 상위(service)가 한다(지어내지 않음).
    """
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "arrange": "A",
        "eventStartDate": event_start_date,
        "areaCode": area_code,
        "numOfRows": str(num_of_rows),
        "pageNo": str(page_no),
    }
    if sigungu_code:
        params["sigunguCode"] = sigungu_code

    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(BASE_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("searchFestival2 호출 실패(area=%s sig=%s): %s", area_code, sigungu_code, exc)
        raise TourApiFestivalError(f"upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        logger.warning("searchFestival2 비정상 상태코드 %s (area=%s)", resp.status_code, area_code)
        raise TourApiFestivalError(f"upstream status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("searchFestival2 응답 JSON 파싱 실패: %s", redact_secrets(resp.text)[:200])
        raise TourApiFestivalError("upstream returned non-JSON body") from exc

    return _parse_items(data)


async def fetch_all_festivals(
    event_start_date: str,
    page_rows: int = 100,
    max_pages: int = 10,
) -> list[dict]:
    """areaCode 없이 **전국** 축제를 페이지네이션으로 전량 조회.

    areaCode 필터가 최신 레코드에서 동작하지 않으므로(모듈 docstring 참고) 전국을 한 번
    쓸어담고 상위(service)가 lDongRegnCd/lDongSignguCd 로 메모리 필터한다.
    eventStartDate 필터(= eventEndDate >= 이 날짜)는 원천이 그대로 적용하므로
    "이미 끝난 축제"는 애초에 오지 않는다.

    실패 시 TourApiFestivalError. 데이터 없음이면 빈 리스트(정상).
    """
    out: list[dict] = []
    total: int | None = None

    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        for page in range(1, max_pages + 1):
            params = {
                "serviceKey": settings.public_data_api_key,  # 로그 금지
                "MobileOS": "ETC",
                "MobileApp": "Sumeungil",
                "_type": "json",
                "arrange": "A",
                "eventStartDate": event_start_date,
                "numOfRows": str(page_rows),
                "pageNo": str(page),
            }
            try:
                resp = await client.get(BASE_URL, params=params)
            except httpx.HTTPError as exc:
                logger.warning("searchFestival2 전국 스윕 실패(page=%s): %s", page, exc)
                raise TourApiFestivalError(f"upstream request failed: {exc}") from exc

            if resp.status_code != 200:
                logger.warning("searchFestival2 비정상 상태코드 %s (page=%s)", resp.status_code, page)
                raise TourApiFestivalError(f"upstream status {resp.status_code}")

            try:
                data = resp.json()
            except ValueError as exc:
                logger.warning("searchFestival2 JSON 파싱 실패: %s", redact_secrets(resp.text)[:200])
                raise TourApiFestivalError("upstream returned non-JSON body") from exc

            items = _parse_items(data)
            if total is None:
                total = _parse_total(data)
            if not items:
                break
            out.extend(items)
            if total is not None and len(out) >= total:
                break

    logger.info("searchFestival2 전국 %d건 수집(원천 totalCount=%s)", len(out), total)
    return out


def _parse_total(data: dict) -> int | None:
    try:
        return int(data["response"]["body"]["totalCount"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_items(data: dict) -> list[dict]:
    # flat 에러 형태(파라미터 오류 등)
    if "response" not in data:
        code = data.get("resultCode")
        msg = data.get("resultMsg", "")
        raise TourApiFestivalError(f"upstream flat error resultCode={code} msg={msg}")

    header = data["response"].get("header", {})
    code = header.get("resultCode")
    if code not in ("0000", "00"):
        msg = header.get("resultMsg", "")
        raise TourApiFestivalError(f"upstream header resultCode={code} msg={msg}")

    body = data["response"].get("body", {})
    items = body.get("items")
    if not items:  # "" 또는 None = 데이터 없음(정상)
        return []

    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return []
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return item
    return []
