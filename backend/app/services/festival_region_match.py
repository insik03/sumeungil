"""주소 문자열 → region_code(법정동 5자리) 매칭 (축제 표준데이터 전용).

전국문화축제표준데이터는 지역 코드를 주지 않고 주소(rdnmadr 도로명 / lnmadr 지번)만 준다.
그래서 주소 앞머리의 "시도 + 시군구"를 잘라 `regions/seed.py` 의 REGIONS 라벨과 맞춘다.

매칭 규칙(문서화된 계약 — 부록 K):
  1. rdnmadr 우선, 비어 있으면 lnmadr 사용(둘 다 비면 매칭 실패).
  2. 첫 토큰을 시도명으로 보고 area_cd(2자리)로 변환. 표준데이터에 실제로 등장하는 표기
     변형(강원도/서울시/충남 등)도 별칭표로 흡수한다.
  3. 남은 토큰에서 시군구를 찾는다. "전주시 완산구"처럼 2단계(시+구)를 먼저 시도하고,
     실패하면 1토큰("보령시")으로 시도한다.
  4. 세종특별자치시처럼 라벨이 시도 1토큰뿐인 단층 지자체는 시도만 맞으면 매칭한다.
  5. 첫 토큰이 우리가 아는 시도가 아니면(예: "울릉군 ...", 또는 TourAPI 가 쓰기 시작한
     "전남광주통합특별시" 같은 미지의 광역 표기) 앞 두 토큰 범위에서 **전국 유일한** 시군구
     이름을 찾을 때만 매칭한다. 이름이 겹치는 "동구/서구/북구" 류는 매칭하지 않는다.
  6. 어느 규칙에도 안 걸리면 None → 그 축제는 **지역 필터 요청에서는 제외**되고
     region_code 없는 전국 요청에서만 노출된다(주소를 추측해 지역을 지어내지 않는다).

REGIONS 는 데모 수기 지역 + spots_seed.json region_meta 기반 전국 시군구(2026-07-29 기준 253곳)다.
따라서 스팟이 수집되지 않은 시군구의 축제는 매칭 실패로 남을 수 있다(의도된 보수적 동작).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from ..regions.seed import REGIONS

logger = logging.getLogger("sumeungil.services.festival_region")

# 표준데이터 주소에 실제로 등장하는(2026-07-29 실측) 시도 표기 변형 → 법정동 area_cd.
# 정식 라벨(서울특별시/부산광역시 ...)은 REGIONS 라벨에서 자동 수집하므로 여기엔 변형만 둔다.
_SIDO_ALIASES: dict[str, str] = {
    "서울": "11", "서울시": "11",
    "부산": "26", "부산시": "26",
    "대구": "27", "대구시": "27",
    "인천": "28", "인천시": "28",
    "광주": "29", "광주광역시": "29",
    "대전": "30", "대전시": "30",
    "울산": "31", "울산시": "31",
    "세종": "36", "세종시": "36",
    "경기": "41",
    "충북": "43", "충청북도": "43",
    "충남": "44", "충청남도": "44",
    "전남": "46", "전라남도": "46",
    "경북": "47", "경상북도": "47",
    "경남": "48", "경상남도": "48",
    "제주": "50", "제주도": "50", "제주특별자치도": "50",
    "강원": "51", "강원도": "51", "강원특별자치도": "51",
    "전북": "52", "전라북도": "52", "전북특별자치도": "52",
}


class _Index:
    """REGIONS 로부터 만든 매칭 인덱스 (프로세스 1회 구축)."""

    def __init__(self) -> None:
        self.sido: dict[str, str] = {}                 # 시도 표기 → area_cd
        self.by_sigungu: dict[tuple[str, str], str] = {}  # (area_cd, 시군구표기) → region_id
        self.single_tier: dict[str, str] = {}          # area_cd → region_id (세종형 단층)
        self.unique_name: dict[str, str] = {}          # 전국 유일 시군구명 → region_id

        name_hits: dict[str, set[str]] = {}

        for r in REGIONS:
            tokens = r.label.split()
            if not tokens:
                continue
            self.sido.setdefault(tokens[0], r.area_cd)

            rest = tokens[1:]
            if not rest:
                # 세종특별자치시처럼 라벨이 시도 1토큰뿐 = 단층 지자체
                self.single_tier.setdefault(r.area_cd, r.region_id)
                continue

            keys = {" ".join(rest)}      # "전주시 완산구"
            if len(rest) >= 1:
                keys.add(rest[0])        # "전주시" / "해운대구"
            for k in keys:
                self.by_sigungu.setdefault((r.area_cd, k), r.region_id)
                name_hits.setdefault(k, set()).add(r.region_id)

        # 전국에서 이름이 유일한 시군구만 시도 없이도 매칭 허용
        self.unique_name = {n: next(iter(ids)) for n, ids in name_hits.items() if len(ids) == 1}

        # 별칭은 라벨에서 온 정식 표기를 덮어쓰지 않는다.
        for alias, area in _SIDO_ALIASES.items():
            self.sido.setdefault(alias, area)


@lru_cache(maxsize=1)
def _index() -> _Index:
    idx = _Index()
    logger.info(
        "축제 지역매칭 인덱스 구축: 시도 %d, 시군구 %d, 단층 %d, 유일명 %d",
        len(idx.sido), len(idx.by_sigungu), len(idx.single_tier), len(idx.unique_name),
    )
    return idx


@lru_cache(maxsize=1)
def _known_ids() -> frozenset[str]:
    return frozenset(r.region_id for r in REGIONS)


def is_known_region(code: str | None) -> bool:
    """우리 REGIONS 사전에 존재하는 region_code 인지. 미지의 광역 개편 코드 판별용."""
    return bool(code) and code in _known_ids()


def pick_address(item: dict) -> str | None:
    """표준데이터 item 에서 주소 원문을 고른다(도로명 우선, 없으면 지번). 없으면 None."""
    for key in ("rdnmadr", "lnmadr"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def match_region_code(address: str | None) -> str | None:
    """주소 문자열 → region_code(법정동 5자리). 매칭 실패면 None(지어내지 않음)."""
    if not address:
        return None
    tokens = address.replace("　", " ").split()
    if not tokens:
        return None

    idx = _index()
    area = idx.sido.get(tokens[0])

    if area is None:
        # 시도 없이 시군구로 시작("울릉군 ..."), 또는 미지의 광역 표기가 앞에 붙은 경우
        # ("전남광주통합특별시 여수시 ..."). 이름이 전국 유일한 시군구일 때만 채택한다.
        cands = [" ".join(tokens[:2]), tokens[0]]
        if len(tokens) >= 3:
            cands.append(" ".join(tokens[1:3]))
        if len(tokens) >= 2:
            cands.append(tokens[1])
        for cand in cands:
            hit = idx.unique_name.get(cand)
            if hit:
                return hit
        return None

    rest = tokens[1:]
    # "전주시 완산구" 같은 2단계 우선 → "보령시" 1단계
    if len(rest) >= 2:
        hit = idx.by_sigungu.get((area, f"{rest[0]} {rest[1]}"))
        if hit:
            return hit
    if rest:
        hit = idx.by_sigungu.get((area, rest[0]))
        if hit:
            return hit

    # 세종특별자치시 등 단층 지자체
    return idx.single_tier.get(area)


def legal_dong_code(item: dict) -> str | None:
    """TourAPI item 의 lDongRegnCd(2)+lDongSignguCd(3) → 법정동 5자리. 없으면 None.

    spots/collector._legal_dong_code 와 동일 규칙(세종형 5자리 완성코드 분기 포함).
    collector 를 import 하면 스팟 스토어 로딩까지 딸려오므로 여기서 최소 구현을 유지한다.
    """
    regn = str(item.get("lDongRegnCd", "") or "").strip()
    sig = str(item.get("lDongSignguCd", "") or "").strip()
    if not regn.isdigit():
        return None
    if len(regn) == 5:          # 세종형: 이미 완성된 법정동 5자리
        return regn
    if not sig.isdigit():
        return None
    code = f"{int(regn):02d}{int(sig):03d}"
    return code if len(code) == 5 else None
