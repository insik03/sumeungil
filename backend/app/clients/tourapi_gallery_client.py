"""한국관광공사 포토갤러리(PhotoGalleryService1) 클라이언트 — 키워드 사진 검색.

원천: GET https://apis.data.go.kr/B551011/PhotoGalleryService1/gallerySearchList1

실호출로 확정(2026-07-29, backend-engineer):
  - **예전엔 403 이었으나 현재 200 으로 열려 있다**(활용신청 승인 반영).
  - 파라미터: serviceKey / MobileOS / MobileApp / _type / keyword / numOfRows / pageNo / arrange.
  - 응답 item 필드(전량 관측):
      galContentId, galContentTypeId(="17"), galTitle, galWebImageUrl,
      galCreatedtime, galModifiedtime, galPhotographyMonth,
      galPhotographyLocation(예: "부산광역시 해운대구 중동"), galPhotographer(촬영자),
      galSearchKeyword(콤마 구분 키워드 나열)
    → **라이선스 유형 필드는 없다**. 촬영자만 있으므로 출처 표기는 촬영자+제공기관으로 만든다.
  - 전체 규모 totalCount=6,118 (galleryList1 arrange=A 기준). 사진기자단이 찍은 **관광지 사진**
    중심이라 작은 식당·카페는 사실상 없다(금수복국 keyword → totalCount 0 실측).
  - 데이터 없음이면 body.items == "" (정상).
  - galleryDetailList1 은 title 이 필수이고 추가 라이선스 필드를 주지 않는다(확인함).
  - galleryMetaList1 은 404(미제공).

serviceKey 는 params 로만 전달하고 로그에 남기지 않는다.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.tourapi.gallery")

BASE_URL = "https://apis.data.go.kr/B551011/PhotoGalleryService1/gallerySearchList1"


class TourApiGalleryError(Exception):
    """포토갤러리 원천 호출/파싱 실패."""


async def search_gallery(keyword: str, num_of_rows: int = 20) -> list[dict]:
    """키워드로 갤러리 사진 목록을 검색. 결과 없으면 빈 리스트.

    반환 item 은 원본 키를 그대로 담는다 — **어떤 사진을 채택할지는 상위(photo_service)의
    엄격 매칭 규칙이 판정한다**(여기서 고르지 않는다: 키워드 검색은 galSearchKeyword 까지
    훑어서 "해운대" 로 검색하면 해운대 지역의 온갖 사진이 딸려 오기 때문).
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    params = {
        "serviceKey": settings.public_data_api_key,  # 로그 금지
        "MobileOS": "ETC",
        "MobileApp": "Sumeungil",
        "_type": "json",
        "keyword": kw,
        "numOfRows": str(num_of_rows),
        "pageNo": "1",
        "arrange": "A",  # 제목순 — 같은 입력에 같은 결과(결정적)
    }

    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(BASE_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("포토갤러리 호출 실패: %s", exc)
        raise TourApiGalleryError(f"upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        # 429(오퍼레이션 일일 한도) 포함. 상위는 캐시하지 않고 graceful null.
        logger.warning("포토갤러리 비정상 상태코드 %s", resp.status_code)
        raise TourApiGalleryError(f"upstream status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise TourApiGalleryError("upstream returned non-JSON body") from exc

    if "response" not in data:
        raise TourApiGalleryError(f"upstream flat error resultCode={data.get('resultCode')}")
    header = data["response"].get("header", {})
    if header.get("resultCode") not in ("0000", "00"):
        raise TourApiGalleryError(f"upstream header resultCode={header.get('resultCode')}")

    items = data["response"].get("body", {}).get("items")
    if not items:  # "" 또는 None = 검색 결과 없음(정상)
        return []
    item = items.get("item") if isinstance(items, dict) else None
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return [i for i in item if isinstance(i, dict)]
    return []
