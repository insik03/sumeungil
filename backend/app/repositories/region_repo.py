"""지역 사전 리포지토리.

경계 목적: 검색 경로가 '지역 코드를 어디서 얻는지'를 감춘다.
  - MVP-2: StaticRegionRepository — 코드 상수(regions/seed.py) 기반
  - 상용:  DbRegionRepository     — 공식 법정동 코드셋 테이블 read
둘 다 동일한 search() 시그니처를 반환하므로 엔드포인트·응답 계약은 불변.

매칭 규칙(단순, 계약 A.1):
  - q 를 트림·소문자·공백제거 정규화
  - label 또는 alias 의 정규화형에 q 가 substring 이면 후보
  - 랭킹: (1) alias/label 이 q 로 시작(prefix) > (2) 그냥 포함, 동점이면 seed 순서
  - 매칭 0건이면 빈 리스트(엔드포인트가 items:[] + 200 으로 응답)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..regions.seed import REGIONS, RegionSeed


def _norm(s: str) -> str:
    return s.replace(" ", "").lower().strip()


class RegionRepository(ABC):
    @abstractmethod
    def search(self, q: str, limit: int) -> list[RegionSeed]:
        raise NotImplementedError


class StaticRegionRepository(RegionRepository):
    """seed.py 상수 기반 인메모리 검색. 프로세스 수명 동안 불변."""

    def __init__(self, regions: list[RegionSeed] | None = None) -> None:
        self._regions = regions if regions is not None else REGIONS
        # (region, [정규화된 검색 대상 문자열들]) 사전 계산
        self._index: list[tuple[RegionSeed, list[str]]] = [
            (r, [_norm(r.label), *(_norm(a) for a in r.aliases)])
            for r in self._regions
        ]

    def search(self, q: str, limit: int) -> list[RegionSeed]:
        nq = _norm(q)
        if not nq:
            return []

        scored: list[tuple[int, int, RegionSeed]] = []
        for order, (region, targets) in enumerate(self._index):
            best = None  # 0 = prefix match, 1 = substring match
            for t in targets:
                if t.startswith(nq):
                    best = 0
                    break
                if nq in t:
                    best = 1 if best is None else best
            if best is not None:
                scored.append((best, order, region))

        scored.sort(key=lambda x: (x[0], x[1]))
        return [region for _, _, region in scored[:limit]]
