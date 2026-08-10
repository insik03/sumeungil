"""전국 17개 시도 혼잡도 보드 (부록 U, 2026-08-01) — "지금 전국 어디가 붐비나" 한 화면.

대표 지시(2026-08-01): 서울 전용 앱 시안처럼 **전국 지도** 위에 혼잡도를 얹고 싶다.

## 왜 시도 단위인가 (원천 제약 실측)
혼잡도 원천(KTO tatsCnctrRatedList)은 `signguCd`(시군구)가 **필수**다. 시도만으로는 조회가
거부된다(실측: `NO_MANDATORY_REQUEST_PARAMETERS_ERROR2(signguCd)`). 따라서
  - 시군구 250곳 전부  → 요청 250건 → 일일 쿼터 소진(2026-07-29 실사고와 같은 경로)
  - **시도 17곳**      → 요청 17건 → 12시간 캐시로 하루 ~34건. 감당 가능.
그래서 시도당 **대표 시군구 1곳**으로 산출한다.

## 정직성 (이 모듈의 핵심)
"서울 = 종로구 기준"이라는 사실을 숨기면 거짓말이 된다. 응답의 각 항목이
`basis_region_name`(예: "서울특별시 종로구")을 반드시 담고, 프론트는 이를 화면에 표기한다.
- 값은 그 지역 board 관광지들의 **집중률 중앙값**이다(평균·최대값이 아니다 — 한 곳이 튀어서
  시도 전체가 빨개지는 걸 막는다). 몇 곳을 근거로 삼았는지 `sample_count` 로 함께 준다.
- 원천 실패/데이터 없음은 지어내지 않고 `available=false` 로 내려보낸다(회색 처리).
- **대기시간 같은 파생 수치는 만들지 않는다.** 원천에 없다(시안에 있던 "예상 대기 20분"은
  우리가 낼 수 없는 값이다).
"""

from __future__ import annotations

import asyncio
import logging
import statistics

from ..cache.base import Cache
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.nationwide import (
    NationwideCongestionItem,
    NationwideCongestionResponse,
)
from ..util.time import now_kst, to_iso_kst
from . import featured_service
from .congestion_service import classify_level

logger = logging.getLogger("sumeungil.services.nationwide_congestion")

# 시도별 대표 시군구 — 프론트 `components/regions/constants.ts` 의 SIDO_REGIONS 와 **1:1**이어야
# 한다(양쪽이 어긋나면 지도 색과 클릭 후 화면이 다른 지역을 가리킨다).
# (응답 키, KTO area_cd, 표시명, 대표 시군구 코드)
SIDO_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("11", "11", "서울", "11110"),
    ("26", "26", "부산", "26350"),
    ("27", "27", "대구", "27110"),
    ("28", "28", "인천", "28185"),
    ("29", "29", "광주", "29110"),
    ("30", "30", "대전", "30110"),
    ("31", "31", "울산", "31110"),
    ("36", "36", "세종", "36110"),
    ("41", "41", "경기", "41111"),
    ("43", "43", "충북", "43111"),
    ("44", "44", "충남", "44150"),
    ("46", "46", "전남", "46130"),
    ("47", "47", "경북", "47130"),
    ("48", "48", "경남", "48220"),
    ("50", "50", "제주", "50110"),
    ("51", "51", "강원", "51150"),
    ("52", "52", "전북", "52111"),
    # 2026-08-01(대표 지시) — 울릉도는 경북 안에 있지만 **본토와 완전히 분리된 섬**이라
    # 경주(경북 대표) 혼잡도로 대신 말할 수 없다. 별도 항목으로 둔다(울릉군 47940, 스팟 54곳).
    # sido_code 는 지도 path 와 겹치지 않게 "47940" 을 그대로 키로 쓴다(시도 코드가 아님).
    ("47940", "47", "울릉도", "47940"),
)

CACHE_KEY = "nationwide_congestion:v1"
CACHE_TTL_SEC = 12 * 60 * 60


def _region_label(region_code: str) -> str | None:
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _pick_region_photo(records, spots) -> tuple[str, str] | None:
    """그 지역 board 상위 관광지 중 **시드에 사진이 있는 첫 곳**의 (이름, 사진URL).

    2026-08-01(대표 요청 "그 지역의 진짜 배경 사진"): 랜드마크 이름으로 시드를 검색하는 방식은
    폐기했다 — 시드가 전수가 아니라 첨성대·남산서울타워 같은 대표 명소가 아예 없고, 이름만
    비슷한 엉뚱한 곳(법주사→법주사(군위), 설악산→설악산책)이 걸린다. **지어낸 사진**이 되는 셈이다.
    대신 이미 받아 둔 board(그 지역에서 지금 방문 집중률이 높은 관광지 목록)를 시드와 이름
    매칭해 사진을 고른다 — 원천 호출이 늘지 않고, 그 지역에서 실제로 사람이 많이 가는 곳이라
    대표성도 있다. 사진과 함께 **그 스팟의 실제 이름을 같이 반환**해 화면이 무엇을 보여주는지
    정확히 밝힌다(랜드마크 그림과 사진이 다른 곳일 수 있으므로).
    """
    # 이름 매칭은 featured_service._match_store 를 그대로 쓴다(정확일치 → 부분일치).
    # 단순 정규화 exact 조회로는 board 이름과 시드 이름의 표기 차이 때문에 거의 매칭되지 않아
    # 폴백(가나다순 첫 스팟)만 나왔다 — 실측: 서울 '가회민화박물관', 대구 '2·28민주운동기념회관'.
    # 대표성이 없는 사진이라 지역 소개용으로 못 쓴다.
    # **집중률 높은 순으로 본다.** 원본 records 순서는 가나다순이라 그대로 돌면 '가회민화박물관',
    # '2·28민주운동기념회관' 같은 첫 글자 스팟이 뽑혀 지역 대표 사진이 되지 못한다(실측).
    ordered = sorted(
        records, key=lambda r: r.congestion_rate if r.congestion_rate is not None else -1.0,
        reverse=True,
    )
    for rec in ordered:
        if not rec.spot_name:
            continue
        hit = featured_service._match_store(rec.spot_name, spots)  # noqa: SLF001
        if hit is not None and hit.image_url:
            return hit.name, hit.image_url
    # board 매칭이 하나도 없으면 그 지역 스팟 중 사진 있는 첫 곳으로 폴백
    for s in spots:
        if s.image_url:
            return s.name, s.image_url
    return None


async def _one_sido(
    key: str,
    area_cd: str,
    short_name: str,
    region_code: str,
    congestion_repo: CongestionRepository,
    spot_repo=None,
) -> NationwideCongestionItem:
    basis = _region_label(region_code)
    try:
        result = await congestion_repo.get_board(area_cd, region_code)
    except Exception as exc:  # noqa: BLE001 — 한 시도 실패가 전국 보드를 막지 않는다
        logger.info("전국 혼잡도: %s(%s) 조회 실패 — available=false: %s", short_name, region_code, exc)
        return NationwideCongestionItem(
            sido_code=key, short_name=short_name, region_code=region_code,
            basis_region_name=basis, available=False,
        )

    rates = [
        r.congestion_rate
        for r in (result.records or [])
        if r.congestion_rate is not None
    ]
    if not rates:
        return NationwideCongestionItem(
            sido_code=key, short_name=short_name, region_code=region_code,
            basis_region_name=basis, available=False,
        )

    # 대표값은 **중앙값**이다(평균·최대값이 아니다).
    # - 최대값: 한 곳이 튀면 시도 전체가 빨개진다.
    # - 상위 N 평균: 실측(2026-08-01) 결과 17개 시도 중 13곳이 high 로 붙어 지도가 온통 빨개졌다.
    #   board 레코드가 지역당 12~34건뿐이라 "상위 10곳"이 사실상 전체 상위권을 긁는다.
    # - 중앙값: 그 지역의 **보통 관광지**가 얼마나 붐비는지를 나타내고 이상치에 강하다.
    #   실측 서울 69.9 / 경기 64.5 / 제주 77.0 — 시도 간 차이가 실제로 드러난다.
    photo = None
    if spot_repo is not None:
        try:
            photo = _pick_region_photo(result.records or [], spot_repo.by_region(region_code, None))
        except Exception as exc:  # noqa: BLE001 — 사진은 부가정보다. 실패해도 혼잡도는 준다.
            logger.info("전국 혼잡도: %s 사진 선정 실패(무시): %s", short_name, exc)

    index = round(statistics.median(rates), 2)
    return NationwideCongestionItem(
        sido_code=key,
        short_name=short_name,
        region_code=region_code,
        basis_region_name=basis,
        available=True,
        index=index,
        level=classify_level(index),
        sample_count=len(rates),
        photo_spot_name=photo[0] if photo else None,
        photo_url=photo[1] if photo else None,
    )


async def build_nationwide_congestion(
    congestion_repo: CongestionRepository, cache: Cache, spot_repo=None
) -> NationwideCongestionResponse:
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return NationwideCongestionResponse(**cached)

    items = await asyncio.gather(
        *[_one_sido(k, a, n, rc, congestion_repo, spot_repo) for k, a, n, rc in SIDO_TARGETS]
    )
    resp = NationwideCongestionResponse(
        items=list(items),
        fetched_at=to_iso_kst(now_kst()),
        notice=(
            "각 시·도의 대표 시·군·구 한 곳을 기준으로 계산한 값이에요. "
            "그 지역 관광지들의 예상 집중률 중앙값이며, 실시간 실측이 아니에요."
        ),
    )
    # 전부 실패했으면 캐시하지 않는다(원천 복구 시 즉시 반영) — 기존 정책과 동일.
    if any(i.available for i in resp.items):
        await cache.set(CACHE_KEY, resp.model_dump(), CACHE_TTL_SEC)
    return resp
