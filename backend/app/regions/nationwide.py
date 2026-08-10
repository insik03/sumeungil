"""전국 9권역 정의 (부록 Q) — 날씨 보드 / 계절 추천 / 홈 지역 다양성이 공유하는 단일 소스.

권역은 **고정 9개**다. 각 권역은
  - region_code : 그 권역의 **대표 시군구**(반드시 regions.seed.REGIONS 에 실재하는 법정동 5자리)
  - area_cd     : 혼잡도(KTO) 조회용 시도 2자리
  - course_ids  : 날씨(기상청 D18) 조회용 대표 관광코스 후보(앞에서부터 시도)
를 갖는다.

course_ids 는 **실호출 스윕으로 확정**했다(2026-07-31, backend-engineer):
  COURSE_ID 1~360 을 전수 조회해 courseAreaId(시도)·courseName·pop/th3 존재 여부를 수집한 뒤,
  권역 대표 도시에 해당하는 코스를 우선 선택했다. 344개 코스가 응답했고 9권역 전부 pop·th3 확보.
  (D18 은 관광코스 단위 조회만 제공하고 시군구 코드로는 조회할 수 없다 — kma_weather_client 참고.)

주의: D18 courseAreaId 는 2023~24 개편 **이전** 시도코드를 쓴다(강원=42, 전북=45).
      전남·광주는 원천에서 area 12("전남광주통합특별시")로 묶여 있다. 우리 region_code 는
      개편 **이후** 법정동 코드(강원 51 / 전북 52)를 그대로 쓴다 — 두 체계를 섞지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionBlock:
    key: str                    # 프론트 고정 키(변경 금지)
    label: str                  # 화면 표시용 권역명
    region_code: str            # 대표 시군구 법정동 5자리 (= seed REGIONS 의 region_id)
    area_cd: str                # KTO 혼잡도 조회용 시도 2자리 (**대표 1개** — 아래 area_cds 참고)
    course_ids: tuple[int, ...]  # 기상청 D18 대표 코스 후보(앞에서부터 폴백)
    # 2026-08-01 additive — 이 권역에 **실제로 속한 시도 전체**.
    # 광역시를 소속 도에 흡수한 9권역 정의상 한 권역이 여러 시도를 품는다(경기·서울 = 11+28+41).
    # `area_cd` 는 종전 호출부(날씨 보드·혼잡도)가 쓰는 대표값이라 의미를 바꾸지 않고 두고,
    # "권역 전체를 훑어야 하는" 화면(계절 여행 지역 선택)만 이 튜플을 쓴다.
    area_cds: tuple[str, ...] = ()


# 순서가 곧 응답 순서다(프론트 보드 배치 안정성). 9개 고정.
REGION_BLOCKS: tuple[RegionBlock, ...] = (
    RegionBlock("gyeonggi", "경기·서울", "11110", "11", (55, 53, 58), ("11", "41", "28")),
    RegionBlock("gangwon", "강원", "51150", "51", (79, 80), ("51",)),
    RegionBlock("chungbuk", "충북", "43111", "43", (6, 5, 258), ("43",)),
    RegionBlock("chungnam", "충남·대전·세종", "44150", "44", (292, 84, 9), ("44", "30", "36")),
    RegionBlock("jeonbuk", "전북", "52111", "52", (94, 95, 96), ("52",)),
    RegionBlock("jeonnam", "전남·광주", "46130", "46", (260, 106, 291), ("46", "29")),
    RegionBlock("gyeongbuk", "경북·대구", "47130", "47", (113, 121, 259), ("47", "27")),
    RegionBlock("gyeongnam", "경남·부산·울산", "26350", "26", (294, 306, 307), ("48", "26", "31")),
    RegionBlock("jeju", "제주", "50110", "50", (166, 163, 50), ("50",)),
)

BLOCK_BY_KEY: dict[str, RegionBlock] = {b.key: b for b in REGION_BLOCKS}
BLOCK_BY_REGION_CODE: dict[str, RegionBlock] = {b.region_code: b for b in REGION_BLOCKS}


def course_ids_for(region_code: str) -> tuple[int, ...]:
    """대표 시군구 코드 → D18 코스 후보. 권역 대표가 아니면 빈 튜플(지어내지 않음)."""
    block = BLOCK_BY_REGION_CODE.get((region_code or "").strip())
    return block.course_ids if block else ()
