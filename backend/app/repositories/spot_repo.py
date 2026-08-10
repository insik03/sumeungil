"""스팟 데이터 리포지토리.

경계 목적: 추천 읽기 경로가 '스팟을 어디서 얻는지'를 감춘다.
  - MVP-4: JsonSpotRepository — collector가 만든 spots_seed.json 을 프로세스 시작 시 로드
  - 상용:  DbSpotRepository / PostGIS — 배치가 채운 테이블 read
둘 다 동일한 by_region() 시그니처를 반환하므로 엔드포인트·응답 계약은 불변.

스팟 태그벡터(36차원 이진)는 collector가 저장한 tag_values[(axis,value)]로부터
tag_registry 순서에 맞춰 조립한다(registry 단일 소스, 하드코딩 금지).
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..ai import tag_registry
from ..spots.collector import SEED_PATH

logger = logging.getLogger("sumeungil.repo.spot")


@dataclass
class SpotRecord:
    """로컬 스토어 스팟 1건 (혼잡도·스코어 결합 전)."""

    id: int
    name: str
    category: str
    region_code: str
    address: str | None
    lat: float
    lng: float
    themes: dict[str, bool | None]
    is_hidden_gem: bool
    tag_vector: list[float] = field(default_factory=list)  # 36차원 이진 (registry 순서)
    # 부록 G(SpotDetail) 소비용 원본 메타. 기존 추천 경로는 이 필드를 읽지 않는다(불변).
    content_type_id: str | None = None  # TourAPI contentTypeId (detailCommon2/카테고리 참고)
    tags: list[tuple[str, str]] = field(default_factory=list)  # registry 검증된 (axis, value)
    # 대표이미지(areaBasedList2 firstimage). 배치가 시드에 적재해 둔 값이라 **런타임 원천 콜 0**.
    #   str  = 사진 있음 / None = 원천에 사진 없음이 확인됨 / 필드 자체 없음(image_resolved=False)
    #   = 아직 배치가 훑지 않은 스팟 → 런타임이 detailCommon2 로 확인한다.
    image_url: str | None = None
    image_resolved: bool = False        # 시드에 image_url 판정값이 실려 있는가
    cpyrht_div_cd: str | None = None    # 원천 저작권 구분 코드 원본(Type1/Type3…). 해석하지 않음


def _valid_tags(tag_values: list) -> list[tuple[str, str]]:
    """[[axis, value], ...] → registry 검증 통과한 (axis, value) 튜플 목록(순서 보존)."""
    out: list[tuple[str, str]] = []
    for pair in tag_values:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        axis, value = str(pair[0]), str(pair[1])
        if tag_registry.is_valid(axis, value):
            out.append((axis, value))
    return out


def _build_vector(tags: list[tuple[str, str]]) -> list[float]:
    """검증된 (axis, value) 목록 → 36차원 이진 벡터 (registry 인덱스 기준)."""
    vec = [0.0] * tag_registry.VECTOR_DIM
    for axis, value in tags:
        idx = tag_registry.vector_index(axis, value)
        if idx is not None:
            vec[idx] = 1.0
    return vec


class SpotRepository(ABC):
    @abstractmethod
    def by_region(self, region_code: str, category: str | None = None) -> list[SpotRecord]:
        raise NotImplementedError

    @abstractmethod
    def by_id(self, content_id: int) -> SpotRecord | None:
        """content_id(=TourAPI contentId, 로컬 PK)로 스팟 1건 조회. 없으면 None."""
        raise NotImplementedError

    @abstractmethod
    def all_spots(self) -> list[SpotRecord]:
        """전 지역 스팟 전량(로드 순서 보존). 이름 검색 인덱스 구축용(부록 L).

        DB 전환 시에는 이 메서드 대신 인덱스 검색으로 대체하면 된다(계약 불변) —
        지금은 인메모리 21k건이라 프로세스당 1회 스캔으로 충분하다.
        """
        raise NotImplementedError

    @abstractmethod
    def region_counts(self) -> dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    def total(self) -> int:
        raise NotImplementedError


class JsonSpotRepository(SpotRepository):
    """spots_seed.json 기반 인메모리 리포지토리. 프로세스 수명 동안 불변."""

    def __init__(self, seed_path: Path | None = None) -> None:
        path = seed_path or SEED_PATH
        self._by_region: dict[str, list[SpotRecord]] = {}
        self._by_id: dict[int, SpotRecord] = {}
        self._all: list[SpotRecord] = []
        self._region_counts: dict[str, int] = {}
        self._total = 0
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning(
                "스팟 시드 파일 없음: %s — 추천 목록이 빈다. "
                "`python -m app.spots.collector` 로 먼저 수집하세요.", path,
            )
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.error("스팟 시드 로드 실패 %s: %s", path, exc)
            return

        for raw in data.get("spots", []):
            try:
                tags = _valid_tags(raw.get("tag_values", []))
                ctid = raw.get("content_type_id")
                rec = SpotRecord(
                    id=int(raw["id"]),
                    name=str(raw["name"]),
                    category=str(raw["category"]),
                    region_code=str(raw["region_code"]),
                    address=raw.get("address"),
                    lat=float(raw["lat"]),
                    lng=float(raw["lng"]),
                    themes=raw.get("themes") or {"pet_allowed": None, "barrier_free": None, "wellness": None},
                    is_hidden_gem=bool(raw.get("is_hidden_gem", False)),
                    tag_vector=_build_vector(tags),
                    content_type_id=str(ctid) if ctid is not None else None,
                    tags=tags,
                    image_url=raw.get("image_url") or None,
                    image_resolved="image_url" in raw,
                    cpyrht_div_cd=raw.get("cpyrht_div_cd") or None,
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("스팟 레코드 스킵(파싱 오류): %s", exc)
                continue
            self._by_region.setdefault(rec.region_code, []).append(rec)
            self._by_id.setdefault(rec.id, rec)  # 첫 등장 우선(중복 id 방어)
            self._all.append(rec)
            self._total += 1

        self._region_counts = {rc: len(v) for rc, v in self._by_region.items()}
        logger.info("스팟 시드 로드 완료: 총 %d개, 지역 %d곳", self._total, len(self._by_region))

    def by_region(self, region_code: str, category: str | None = None) -> list[SpotRecord]:
        spots = self._by_region.get(region_code.strip(), [])
        if category:
            return [s for s in spots if s.category == category]
        return list(spots)

    def by_id(self, content_id: int) -> SpotRecord | None:
        return self._by_id.get(content_id)

    def all_spots(self) -> list[SpotRecord]:
        return list(self._all)

    def region_counts(self) -> dict[str, int]:
        return dict(self._region_counts)

    def total(self) -> int:
        return self._total
