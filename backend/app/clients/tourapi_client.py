"""한국관광공사 국문 관광정보 서비스(KorService2) 클라이언트 — 지역기반 스팟 목록.

원천: GET https://apis.data.go.kr/B551011/KorService2/areaBasedList2
  - TourAPI 자체 areaCode/sigunguCode 사용(법정동 코드 아님 — region_map.py 참고).
  - contentTypeId: 12(관광지) 14(문화시설) 28(레포츠) 38(쇼핑) 39(음식점) ...

실호출로 확인된 원천 item 필드(2026-07-24):
  title, addr1, mapx(경도), mapy(위도), contenttypeid, cat1/cat2/cat3,
  contentid(원천 PK), tel, firstimage, areacode, sigungucode

응답 envelope는 혼잡도 API와 동일한 {response:{header,body}} 형태.
데이터 없음이면 body.items == "" (빈 문자열). serviceKey는 절대 로그로 출력하지 않는다.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..util.redact import redact_secrets

logger = logging.getLogger("sumeungil.tourapi")

BASE_URL = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"


class TourApiError(Exception):
    """원천 API 호출/파싱 실패."""


class TourApiQuotaError(TourApiError):
    """일일 무료 쿼터(1,000콜) 초과 — 더 호출해도 의미가 없으므로 배치는 즉시 중단해야 한다.

    data.go.kr 은 쿼터 초과 시 JSON 이 아니라 XML(OpenAPI_ServiceResponse)로
    returnReasonCode=22 / LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR 를 돌려준다.
    """


# 쿼터 초과/키 오류를 나타내는 원천 시그니처(JSON header, XML 본문 공통으로 검사)
_QUOTA_SIGNS = (
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
)


def _redact(text: str) -> str:
    """로그에 남길 응답 본문에서 혹시라도 섞인 serviceKey 를 제거한다.

    구현은 `util.redact.redact_secrets` 로 옮겼다(2026-08-18 보안 감사 A-2) — detail/festival/
    kma 클라이언트도 같은 함수를 써야 해서 한 곳으로 모았다. 이 이름은 호출부 호환용 얇은 별칭.
    """
    return redact_secrets(text)


async def fetch_area_based_page(
    area_code: str,
    sigungu_code: str,
    content_type_id: str | None = None,
    num_of_rows: int = 50,
    page_no: int = 1,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[dict], int]:
    """지역(+선택적 콘텐츠타입) 한 페이지를 (item 리스트, totalCount) 로 반환.

    content_type_id 를 생략하면 해당 시군구의 **전 콘텐츠타입**을 한 번에 받는다
    (실호출 확인 2026-07-29: 서울 종로구 totalCount=346, 한 응답에 12/14/15/25/28/32/38/39 혼재).
    타입별 5회 호출 대신 1회로 끝나므로 전국 수집 콜 예산을 크게 아낀다.

    numOfRows 는 300 까지 정상 응답을 실측 확인했다(초과 요청해도 totalCount 만큼만 반환).
    쿼터 초과 시 TourApiQuotaError. serviceKey 는 params 로만 전달하고 로그에 남기지 않는다.
    """
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "arrange": "A",  # 제목순
        "areaCode": area_code,
        "sigunguCode": sigungu_code,
        "numOfRows": str(num_of_rows),
        "pageNo": str(page_no),
    }
    if content_type_id:
        params["contentTypeId"] = content_type_id

    async def _do(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get(BASE_URL, params=params)

    try:
        if client is not None:
            resp = await _do(client)
        else:
            async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as c:
                resp = await _do(c)
    except httpx.HTTPError as exc:
        logger.warning(
            "TourAPI 호출 실패(area=%s sigungu=%s ct=%s): %s",
            area_code, sigungu_code, content_type_id, exc,
        )
        raise TourApiError(f"upstream request failed: {exc}") from exc

    if resp.status_code == 429:
        # data.go.kr 게이트웨이는 **오퍼레이션별** 일일 한도 초과 시 429 + 평문
        # "API token quota exceeded" 를 준다(2026-07-29 실호출 확인). XML resultCode=22 와
        # 다른 경로라 아래 _QUOTA_SIGNS 검사에 걸리지 않으므로 상태코드로 별도 판정한다.
        # 배치(collector)가 이걸 일반 오류로 보면 남은 수백 콜을 헛되이 태운다.
        logger.warning("TourAPI 일일 쿼터 초과(429) area=%s ct=%s", area_code, content_type_id)
        raise TourApiQuotaError("upstream daily quota exceeded (HTTP 429)")
    if resp.status_code != 200:
        logger.warning("TourAPI 비정상 상태코드 %s (area=%s ct=%s)",
                       resp.status_code, area_code, content_type_id)
        raise TourApiError(f"upstream status {resp.status_code}")

    body_text = resp.text
    for sign in _QUOTA_SIGNS:
        if sign in body_text:
            raise TourApiQuotaError(f"upstream quota/access error: {sign}")

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("TourAPI 응답 JSON 파싱 실패: %s", _redact(body_text[:200]))
        raise TourApiError("upstream returned non-JSON body") from exc

    return _parse_page(data)


async def fetch_service_page(
    service_path: str,
    extra_params: dict | None = None,
    num_of_rows: int = 1000,
    page_no: int = 1,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[dict], int]:
    """B551011 하위 임의 서비스/오퍼레이션 한 페이지 → (item 리스트, totalCount).

    2026-09-07 반려동물(`KorService2/detailPetTour2`, contentId 생략 시 전체 목록)·무장애
    (`KorWithService2/areaBasedList2`) 목록 수집용. 오류·쿼터 판정은 areaBasedList2 와 동일 규칙.
    serviceKey 는 params 로만 전달하고 로그에 남기지 않는다.
    """
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "numOfRows": str(num_of_rows),
        "pageNo": str(page_no),
        **(extra_params or {}),
    }
    url = f"https://apis.data.go.kr/B551011/{service_path}"

    async def _do(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get(url, params=params)

    try:
        if client is not None:
            resp = await _do(client)
        else:
            async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as c:
                resp = await _do(c)
    except httpx.HTTPError as exc:
        logger.warning("TourAPI 호출 실패(%s p=%d): %s", service_path, page_no, exc)
        raise TourApiError(f"upstream request failed: {exc}") from exc
    if resp.status_code == 429:
        logger.warning("TourAPI 일일 쿼터 초과(429) %s", service_path)
        raise TourApiQuotaError("upstream daily quota exceeded (HTTP 429)")
    if resp.status_code != 200:
        logger.warning("TourAPI 비정상 상태코드 %s (%s)", resp.status_code, service_path)
        raise TourApiError(f"upstream status {resp.status_code}")
    body_text = resp.text
    for sign in _QUOTA_SIGNS:
        if sign in body_text:
            raise TourApiQuotaError(f"upstream quota/access error: {sign}")
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("TourAPI 응답 JSON 파싱 실패: %s", _redact(body_text[:200]))
        raise TourApiError("upstream returned non-JSON body") from exc
    return _parse_page(data)


async def fetch_area_based_list(
    area_code: str,
    sigungu_code: str,
    content_type_id: str,
    num_of_rows: int = 50,
    page_no: int = 1,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """(하위호환) 지역+콘텐츠타입 기준 원본 item dict 리스트만 반환."""
    items, _total = await fetch_area_based_page(
        area_code, sigungu_code, content_type_id,
        num_of_rows=num_of_rows, page_no=page_no, client=client,
    )
    return items


def _parse_page(data: dict) -> tuple[list[dict], int]:
    if "response" not in data:
        code = data.get("resultCode")
        msg = str(data.get("resultMsg", ""))
        if any(s in msg for s in _QUOTA_SIGNS) or str(code) == "22":
            raise TourApiQuotaError(f"upstream quota error resultCode={code}")
        raise TourApiError(f"upstream flat error resultCode={code} msg={msg}")

    header = data["response"].get("header", {})
    code = header.get("resultCode")
    if code not in ("0000", "00"):
        msg = str(header.get("resultMsg", ""))
        if any(s in msg for s in _QUOTA_SIGNS) or str(code) == "22":
            raise TourApiQuotaError(f"upstream quota error resultCode={code}")
        raise TourApiError(f"upstream header resultCode={code} msg={msg}")

    body = data["response"].get("body", {})
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total = 0

    items = body.get("items")
    if not items:  # "" 또는 None = 데이터 없음(정상)
        return [], total

    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return [], total
    if isinstance(item, dict):
        return [item], total
    if isinstance(item, list):
        return item, total
    return [], total
