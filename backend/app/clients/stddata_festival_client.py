"""행정안전부 전국문화축제표준데이터 클라이언트 (data.go.kr 표준데이터).

원천: GET https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api
  - 전국 지자체가 등록한 문화축제 표준 데이터셋. 지역/기간 필터 파라미터가 없으므로
    **전량 스윕 후 메모리에서 필터**한다(상위 서비스가 6h 캐시).

실호출 확정 (2026-07-29, backend-engineer, 기존 PUBLIC_DATA_API_KEY 사용):
  - 호스트는 반드시 `api.data.go.kr` (apis.data.go.kr → 500, api.odcloud.kr → 404).
    http:// 는 301 리다이렉트만 주므로 https 로 직접 호출한다.
  - 파라미터: serviceKey, pageNo, numOfRows, type=json  (TourAPI 의 `_type` 이 아니라 `type`)
  - 응답 envelope: {"response":{"header":{"resultCode","resultMsg","type"},
                                "body":{"items":[...], "totalCount", "numOfRows", "pageNo"}}}
    * 정상 resultCode = "00" / resultMsg = "NORMAL_SERVICE"  (TourAPI 의 "0000" 과 다름)
    * body.items 는 **평평한 리스트** (TourAPI 처럼 {"item": [...]} 로 감싸지 않음)
    * 미승인 키는 header 만 오고 resultCode="30" (SERVICE KEY IS NOT REGISTERED ERROR)
  - totalCount = 1300 (2026-07-29 기준).
  - **응답시간이 numOfRows 에 초선형**(실측): 200행 1.5s / 500행 5s / 1000행 20s.
    큰 페이지 하나로 받으면 UPSTREAM_TIMEOUT_SEC(기본 8s)에 걸려 통째로 실패한다.
    → 200행 페이지로 쪼개고, 1페이지로 totalCount 를 안 뒤 나머지 페이지를 **동시 요청**한다.
      (전량 1300건 = 7페이지, 실측 총 3초 내외. 이 스윕은 6h 캐시라 하루 몇 회뿐이다.)
  - item 필드(18개, 실측):
      fstvlNm(축제명) opar(개최장소) fstvlStartDate/fstvlEndDate("YYYY-MM-DD")
      fstvlCo(축제내용) mnnstNm(주관기관) auspcInsttNm(주최기관) suprtInsttNm(후원기관)
      phoneNumber homepageUrl relateInfo rdnmadr(도로명주소) lnmadr(지번주소)
      latitude longitude referenceDate insttCode insttNm
    * **이미지 필드 없음** → Festival.image_url 은 null (프론트 플레이스홀더가 처리).
    * rdnmadr / lnmadr 은 둘 중 하나만 채워진 경우가 많다(주소 없음 0건).
    * 날짜는 이미 "YYYY-MM-DD" 하이픈 포맷 (TourAPI 의 YYYYMMDD 와 다름).

serviceKey 는 params 로만 전달하고 로그에 남기지 않는다(main.py 가 httpx/httpcore 로거를
WARNING 이상으로 억제). TourAPI 클라이언트와 동일 정책.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import settings
from ..util.redact import redact_secrets

logger = logging.getLogger("sumeungil.stddata.festival")

BASE_URL = "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api"

PAGE_ROWS = 200       # 실측 1.5s/페이지. 더 키우면 초선형으로 느려져 타임아웃난다.
MAX_PAGES = 15        # 예산 상한(최대 3000건). 현재 원천 1300건 → 7페이지.
MIN_TIMEOUT_SEC = 15.0  # 벌크 스윕 전용 하한. 페이지당 1.5s 지만 원천 지연 여유를 둔다.


class StdDataFestivalError(Exception):
    """원천 API 호출/파싱 실패."""


async def fetch_all_festivals(
    page_rows: int = PAGE_ROWS,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """전국문화축제표준데이터를 전량(페이지네이션) 조회해 원본 item dict 리스트를 반환.

    지역/기간 필터는 상위(service)가 메모리에서 수행한다 — 원천에 필터 파라미터가 없다.
    호출/파싱 실패 시 StdDataFestivalError. 데이터 0건이면 빈 리스트(정상).
    반환 item 은 원본 키(fstvlNm/fstvlStartDate/rdnmadr ...)를 그대로 담는다(가공 금지).
    """
    timeout = max(settings.upstream_timeout_sec, MIN_TIMEOUT_SEC)
    limits = httpx.Limits(max_connections=8)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        first_items, total = _parse_page(await _get_page(client, 1, page_rows))
        out = list(first_items)

        if total is None or len(out) >= total or not first_items:
            logger.info("표준축제데이터 %d건 수집(원천 totalCount=%s)", len(out), total)
            return out

        last_page = min(max_pages, -(-total // page_rows))  # ceil
        pages = range(2, last_page + 1)
        if pages:
            results = await asyncio.gather(*(_get_page(client, p, page_rows) for p in pages))
            for data in results:
                items, _ = _parse_page(data)
                out.extend(items)

    logger.info("표준축제데이터 %d건 수집(원천 totalCount=%s, %d페이지)", len(out), total, last_page)
    return out


async def _get_page(client: httpx.AsyncClient, page: int, page_rows: int) -> dict:
    """한 페이지를 호출해 JSON dict 반환. 실패 시 StdDataFestivalError."""
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "pageNo": str(page),
        "numOfRows": str(page_rows),
        "type": "json",
    }
    try:
        resp = await client.get(BASE_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("표준축제데이터 호출 실패(page=%s): %r", page, exc)
        raise StdDataFestivalError(f"upstream request failed: {exc!r}") from exc

    if resp.status_code != 200:
        logger.warning("표준축제데이터 비정상 상태코드 %s (page=%s)", resp.status_code, page)
        raise StdDataFestivalError(f"upstream status {resp.status_code}")

    try:
        return resp.json()
    except ValueError as exc:
        # 원천 오류 본문은 요청 쿼리(=serviceKey)를 되비춘다(2026-08-18 보안 M-1).
        logger.warning("표준축제데이터 JSON 파싱 실패: %s", redact_secrets(resp.text)[:200])
        raise StdDataFestivalError("upstream returned non-JSON body") from exc


def _parse_page(data: dict) -> tuple[list[dict], int | None]:
    """응답 dict → (item 리스트, totalCount). 헤더 오류면 StdDataFestivalError."""
    if "response" not in data:
        raise StdDataFestivalError(
            f"upstream flat error resultCode={data.get('resultCode')} msg={data.get('resultMsg', '')}"
        )

    header = data["response"].get("header", {})
    code = str(header.get("resultCode", ""))
    if code not in ("00", "0000"):
        # 30 = SERVICE KEY IS NOT REGISTERED (활용신청 미승인/전파 지연)
        raise StdDataFestivalError(
            f"upstream header resultCode={code} msg={header.get('resultMsg', '')}"
        )

    body = data["response"].get("body") or {}
    raw_items = body.get("items")
    items = [it for it in raw_items if isinstance(it, dict)] if isinstance(raw_items, list) else []

    total = body.get("totalCount")
    try:
        total_i = int(total) if total is not None else None
    except (TypeError, ValueError):
        total_i = None

    return items, total_i
