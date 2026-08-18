"""한국관광공사 관광지별 방문자 집중률(예측) API 클라이언트.

원천: GET https://apis.data.go.kr/B551011/TatsCnctrRateService/tatsCnctrRatedList

응답 형태 두 가지를 모두 방어 파싱한다.
  1) 정상 envelope:
     {"response":{"header":{"resultCode":"0000","resultMsg":"OK"},
                  "body":{"items":{"item":[...]}, "totalCount":N, ...}}}
     - 데이터 없음: body.items == "" (빈 문자열)
     - item 이 1건이면 dict, 여러 건이면 list 로 올 수 있음 → 항상 list 로 정규화
  2) flat 에러 (파라미터 누락 등):
     {"responseTime":"...","resultCode":"11","resultMsg":"...ERROR..."}

실호출로 확인된 원천 필드:
  baseYmd(YYYYMMDD), areaCd, areaNm, signguCd, signguNm, tAtsNm(관광지명), cnctrRate(집중률 문자열)

원천 날짜 커버리지 실측 (2026-07-29, backend-engineer):
  - 한 지역 응답 = **관광지 × 미래 날짜(baseYmd) 곱집합**. 날짜는 **오늘 포함 17일치**
    (예: 20260729~20260814). 5주(35일)가 아니다.
  - `baseYmd` 를 요청 파라미터로 주면 `resultCode=10 INVALID_REQUEST_PARAMETER_ERROR(baseYmd)`
    → **날짜 범위 지정 불가**. 전체를 받아 서버가 잘라 쓴다.
  - 행 정렬은 **관광지 → 날짜** 순이라 numOfRows 로 자르면 뒤쪽 '관광지'가 통째로 잘린다
    (날짜가 잘리는 게 아니다). 실측 totalCount: 해운대 323 / 전주 595 / 경주 1173 /
    서울 종로 1921 / 강릉 1632 / 제주시 4148.
  - numOfRows 는 3000까지 정상 응답(제주 4148건은 2페이지 필요). pageNo 페이징 동작 확인.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..util.redact import redact_secrets

logger = logging.getLogger("sumeungil.kto")


class KtoUpstreamError(Exception):
    """원천 API 호출/파싱 실패."""


async def fetch_congestion_raw(
    area_cd: str,
    sigungu_cd: str,
    num_of_rows: int = 1000,
    page_no: int = 1,
) -> list[dict]:
    """원천 API를 호출해 원본 item dict 리스트를 반환.

    데이터가 없으면 빈 리스트를 반환한다(정상). 호출/파싱 실패 시 KtoUpstreamError.
    반환 item 은 원본 키(baseYmd/tAtsNm/cnctrRate 등)를 그대로 담는다.
    """
    items, _total = await _fetch_page(area_cd, sigungu_cd, num_of_rows, page_no)
    return items


# --- 예보(forecast)용 전량 수집 ---
# 전광판(board)은 '오늘 1일치'만 쓰므로 1페이지 1000행으로 충분했지만, 예보는 관광지 전체의
# 17일치가 필요하다. 행이 관광지 순으로 정렬돼 있어 자르면 관광지가 통째로 사라지므로
# totalCount 를 보고 페이징한다. (board 호출 파라미터는 건드리지 않는다 → 전광판 무회귀)
FORECAST_PAGE_ROWS = 3000
FORECAST_MAX_PAGES = 3  # 최대 9000행(≈529 관광지 × 17일). 제주시(4148행)도 2페이지면 충분.


async def fetch_congestion_forecast_raw(
    area_cd: str,
    sigungu_cd: str,
) -> list[dict]:
    """예보용: 해당 지역의 모든 (관광지 × baseYmd) 행을 페이징으로 모아 반환.

    데이터 없음 → 빈 리스트(정상). 1페이지 호출 실패 → KtoUpstreamError.
    2페이지 이후 실패는 **모은 만큼 반환**한다(부분 데이터가 전무보다 낫고, 상위 레이어가
    이미 stale/degraded 폴백을 갖고 있다).
    """
    collected: list[dict] = []
    total = 0
    for page in range(1, FORECAST_MAX_PAGES + 1):
        if page == 1:
            items, total = await _fetch_page(area_cd, sigungu_cd, FORECAST_PAGE_ROWS, page)
        else:
            try:
                items, _ = await _fetch_page(area_cd, sigungu_cd, FORECAST_PAGE_ROWS, page)
            except KtoUpstreamError as exc:
                logger.warning(
                    "forecast %d페이지 실패, 수집분(%d행)으로 진행: %s", page, len(collected), exc
                )
                break
        collected.extend(items)
        if not items or len(collected) >= total:
            break
    if total and len(collected) < total:
        logger.info(
            "forecast 부분수집 area=%s sigungu=%s %d/%d행(페이지 상한)",
            area_cd, sigungu_cd, len(collected), total,
        )
    return collected


async def _fetch_page(
    area_cd: str,
    sigungu_cd: str,
    num_of_rows: int,
    page_no: int,
) -> tuple[list[dict], int]:
    """원천 1페이지 호출 → (item 리스트, totalCount)."""
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그로 출력하지 않는다
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "areaCd": area_cd,
        "signguCd": sigungu_cd,
        "numOfRows": str(num_of_rows),
        "pageNo": str(page_no),
        "_type": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(settings.kto_base_url, params=params)
    except httpx.HTTPError as exc:
        logger.warning("KTO 호출 실패(area=%s sigungu=%s): %s", area_cd, sigungu_cd, exc)
        raise KtoUpstreamError(f"upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        logger.warning("KTO 비정상 상태코드 %s (area=%s)", resp.status_code, area_cd)
        raise KtoUpstreamError(f"upstream status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        # 공공데이터는 키 오류 시 XML 을 반환하기도 한다 — 그 XML 에는 우리가 보낸
        # serviceKey 가 그대로 들어 있다(2026-08-18 보안 M-1). 반드시 마스킹 후 로그.
        snippet = redact_secrets(resp.text)[:200]
        logger.warning("KTO 응답 JSON 파싱 실패: %s", snippet)
        raise KtoUpstreamError("upstream returned non-JSON body") from exc

    return _parse_body(data)


def _parse_items(data: dict) -> list[dict]:
    """(하위호환) item 리스트만 필요할 때. 판정 로직은 _parse_body 단일 소스."""
    return _parse_body(data)[0]


def _parse_body(data: dict) -> tuple[list[dict], int]:
    """원천 응답 → (item 리스트, totalCount). 에러 봉투는 KtoUpstreamError."""
    # (2) flat 에러 형태
    if "response" not in data:
        code = data.get("resultCode")
        msg = data.get("resultMsg", "")
        raise KtoUpstreamError(f"upstream error resultCode={code} msg={msg}")

    header = data["response"].get("header", {})
    code = header.get("resultCode")
    if code != "0000":
        msg = header.get("resultMsg", "")
        raise KtoUpstreamError(f"upstream header resultCode={code} msg={msg}")

    body = data["response"].get("body", {})
    items = body.get("items")
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total = 0

    # 데이터 없음: items == "" 또는 None
    if not items:
        return [], total

    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return [], total

    # 단건이면 dict → list 로 정규화
    if isinstance(item, dict):
        return [item], total
    if isinstance(item, list):
        return item, total
    return [], total
