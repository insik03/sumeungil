"""스팟 이름 검색 (부록 L) — 코스 빌더가 "가게를 검색해서 코스에 넣는" 화면에서 쓴다.

로컬 스팟 스토어(spots_seed, 21k건) **이름 부분일치**만 한다. 원천 API·혼잡도·LLM 호출이
전혀 없어 타이핑마다 불러도 무해하다(순수 인메모리).

설계 결정(문서화 대상):
  - 정규화: recommend_service._norm 을 그대로 재사용(공백 제거 + 소문자화). 혼잡도 이름매칭과
    같은 규칙을 써야 "반송 187" / "반송187" 같은 표기 차이가 같은 결과를 낸다.
  - region_code 는 **필터가 아니라 우선순위**다. 그 지역 매치를 먼저 주고, 부족하면 전국 매치를
    이어 붙인다. 필터로 만들면 "부산에서 검색했는데 경주 스팟을 못 넣는" 제약이 생기는데,
    arrange 는 이미 여러 지역 혼합 코스를 지원하므로(부록 I.7) 막을 이유가 없다.
  - 정렬 키(전부 결정적): (1) 요청 지역 여부 → (2) 접두 일치 여부 → (3) 이름 길이(짧을수록 정확)
    → (4) id. 점수를 지어내지 않고 관측 가능한 값만 쓴다.
  - 인덱스: 프로세스당 1회(첫 검색 시) 정규화 이름 튜플을 만들어 lru_cache 에 보관한다.
    스팟 스토어는 프로세스 수명 동안 불변이라 무효화 로직이 필요 없다.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.places import PlaceSearchItem, PlaceSearchResponse
from . import recommend_service, spot_detail_service

logger = logging.getLogger("sumeungil.services.search")

MAX_QUERY_CHARS = 50   # API 레이어가 Query(max_length) 로도 막는다(이중 방어).
DEFAULT_LIMIT = 8
MAX_LIMIT = 20


@lru_cache(maxsize=2)
def _name_index(repo: SpotRepository) -> tuple[tuple[str, SpotRecord], ...]:
    """(정규화 이름, 스팟) 튜플 인덱스. repo 싱글턴당 1회만 구축된다."""
    index = tuple((recommend_service._norm(s.name), s) for s in repo.all_spots())
    logger.info("스팟 이름 검색 인덱스 구축 완료: %d건", len(index))
    return index


def _to_item(spot: SpotRecord, region_names: dict[str, str | None]) -> PlaceSearchItem:
    if spot.region_code not in region_names:
        region_names[spot.region_code] = spot_detail_service._region_name(spot.region_code)
    return PlaceSearchItem(
        id=spot.id,
        name=spot.name,
        category=spot.category,  # type: ignore[arg-type]
        region_code=spot.region_code,
        region_name=region_names[spot.region_code],
        address=spot.address,
        is_hidden_gem=spot.is_hidden_gem,
        image_url=spot.image_url,
    )


def build_search_response(
    q: str,
    region_code: str | None,
    limit: int,
    spot_repo: SpotRepository,
) -> PlaceSearchResponse:
    """이름 부분일치 검색. 매치가 없으면 items:[] (에러가 아니다)."""
    query = recommend_service._norm(q or "")[:MAX_QUERY_CHARS]
    if not query:
        return PlaceSearchResponse(items=[])

    limit = max(1, min(int(limit), MAX_LIMIT))
    rc = (region_code or "").strip()

    # (지역우선, 접두일치, 이름길이, id) 로 정렬 — 전부 관측값이라 결과가 결정적이다.
    matches: list[tuple[int, int, int, int, SpotRecord]] = []
    for name_norm, spot in _name_index(spot_repo):
        pos = name_norm.find(query)
        if pos < 0:
            continue
        matches.append((
            0 if (rc and spot.region_code == rc) else 1,
            0 if pos == 0 else 1,
            len(name_norm),
            spot.id,
            spot,
        ))

    matches.sort(key=lambda m: m[:4])
    region_names: dict[str, str | None] = {}
    items = [_to_item(m[4], region_names) for m in matches[:limit]]
    logger.info(
        "places/search q_len=%d region=%s 매치=%d 반환=%d",
        len(query), rc or "-", len(matches), len(items),
    )
    return PlaceSearchResponse(items=items)
