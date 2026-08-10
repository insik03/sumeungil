"""한국관광공사 국문 관광정보 서비스(KorService2) 공통정보 클라이언트 — 소개글(overview)+대표이미지.

원천: GET http://apis.data.go.kr/B551011/KorService2/detailCommon2
  - contentId 로 스팟 1건의 공통정보(제목·주소·overview·대표이미지 등)를 조회.
  - 소개글은 응답 item 의 `overview` 필드에 담긴다.
  - 대표이미지는 응답 item 의 `firstimage` 필드(URL)에 담긴다. 별도 이미지 API 아님(같은 키·같은 호출).
    실호출 확정(2026-07-24): firstimage 는 `http://tong.visitkorea.or.kr/cms/resource/...jpg` 형태로
    오며, 이미지 없는 스팟은 빈 문자열("")로 온다(→ 상위에서 image_url:null 처리). 반환 item 은
    원본 키를 그대로 담고, firstimage 소비/정규화(http→https)는 상위(service)가 판정한다.

실호출로 확정(2026-07-24, backend-engineer):
  - 파라미터는 serviceKey/MobileOS/MobileApp/_type/contentId 만 받는다.
    구(舊) KorService1 의 overviewYN·defaultYN·contentTypeId 를 넘기면
    resultCode=10 INVALID_REQUEST_PARAMETER_ERROR 로 거절된다(추측 금지, 실호출 확인).
  - contentId 만으로 overview 포함 전체 공통정보가 내려온다.
  - 응답 envelope 는 areaBasedList2/혼잡도 API 와 동일한 {response:{header,body}} 형태.
  - 데이터 없음(잘못된 id 등)이면 body.items == "" → 빈 결과.

serviceKey 는 params 로만 전달하고 로그에 남기지 않는다(main.py 에서 httpx/httpcore
로거를 WARNING 이상으로 억제해 정상 호출 URL=시크릿 누출을 막는다).
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.tourapi.detail")

BASE_URL = "http://apis.data.go.kr/B551011/KorService2/detailCommon2"


class TourApiDetailError(Exception):
    """원천 API 호출/파싱 실패."""


async def fetch_detail_common(content_id: int) -> dict | None:
    """contentId 로 공통정보 item dict 1건을 반환. 데이터 없으면 None.

    호출/파싱 실패 시 TourApiDetailError. 반환 item 은 원본 키(overview/title/addr1 등)를
    그대로 담는다. overview 유무는 상위(service)에서 판정한다.
    """
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "contentId": str(content_id),
    }

    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(BASE_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("detailCommon2 호출 실패(contentId=%s): %s", content_id, exc)
        raise TourApiDetailError(f"upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        logger.warning("detailCommon2 비정상 상태코드 %s (contentId=%s)", resp.status_code, content_id)
        raise TourApiDetailError(f"upstream status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("detailCommon2 응답 JSON 파싱 실패(contentId=%s): %s", content_id, resp.text[:200])
        raise TourApiDetailError("upstream returned non-JSON body") from exc

    return _parse_item(data, content_id)


IMAGE_BASE_URL = "http://apis.data.go.kr/B551011/KorService2/detailImage2"


async def fetch_detail_images(content_id: int, num_of_rows: int = 5) -> list[dict]:
    """contentId 의 추가 이미지 목록(detailImage2). 없으면 빈 리스트.

    실호출 확정(2026-07-29):
      - 필수 파라미터는 contentId + imageYN=Y. 응답 item 필드는
        contentid / originimgurl(원본) / imgname / smallimageurl / cpyrhtDivCd / serialnum.
      - **firstimage 가 비어 있어도 여기엔 사진이 있는 스팟이 존재한다**(예: 일부 관광지).
        반대로 둘 다 없는 스팟도 많다(작은 식당·카페) → 그건 정직하게 사진 없음.
      - 데이터 없음이면 body.items == "" (정상, 빈 리스트).
    호출/파싱 실패 시 TourApiDetailError(상위에서 graceful None 처리).
    """
    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "contentId": str(content_id),
        "imageYN": "Y",
        "numOfRows": str(num_of_rows),
        "pageNo": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(IMAGE_BASE_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("detailImage2 호출 실패(contentId=%s): %s", content_id, exc)
        raise TourApiDetailError(f"upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        # 429 = 그 오퍼레이션의 일일 한도 초과. 상위는 캐시하지 않고 다음 날 재시도한다.
        logger.warning("detailImage2 비정상 상태코드 %s (contentId=%s)", resp.status_code, content_id)
        raise TourApiDetailError(f"upstream status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise TourApiDetailError("upstream returned non-JSON body") from exc

    if "response" not in data:
        raise TourApiDetailError(f"upstream flat error resultCode={data.get('resultCode')}")
    header = data["response"].get("header", {})
    if header.get("resultCode") not in ("0000", "00"):
        raise TourApiDetailError(f"upstream header resultCode={header.get('resultCode')}")

    items = data["response"].get("body", {}).get("items")
    if not items:
        return []
    item = items.get("item") if isinstance(items, dict) else None
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return [i for i in item if isinstance(i, dict)]
    return []


def _parse_item(data: dict, content_id: int) -> dict | None:
    # flat 에러 형태(파라미터 오류 등)
    if "response" not in data:
        code = data.get("resultCode")
        msg = data.get("resultMsg", "")
        raise TourApiDetailError(f"upstream flat error resultCode={code} msg={msg}")

    header = data["response"].get("header", {})
    code = header.get("resultCode")
    if code not in ("0000", "00"):
        msg = header.get("resultMsg", "")
        raise TourApiDetailError(f"upstream header resultCode={code} msg={msg}")

    body = data["response"].get("body", {})
    items = body.get("items")
    if not items:  # "" 또는 None = 데이터 없음(정상)
        return None

    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return None
    if isinstance(item, list):
        return item[0] if item else None
    if isinstance(item, dict):
        return item
    return None
