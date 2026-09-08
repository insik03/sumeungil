"""배치 수집기 — TourAPI 실호출 → 로컬 스토어(JSON 시드) 적재.

실행:  python -m app.spots.collector                 (기본: 전국 확장 additive 수집)
       python -m app.spots.collector --budget 400    (KorService2 콜 예산 상한 지정)
       python -m app.spots.collector --demo-only      (데모 4지역만 재수집 — 기존 동작)

원칙(부록 C.1): 읽기 경로(추천 엔드포인트)는 원천 API를 요청마다 때리지 않는다.
이 스크립트가 스팟을 미리 수집해 spots_seed.json 에 적재하고, 런타임 리포지토리는
그 파일만 읽는다(쿼터·속도 방어, 무료 1,000회/일 제약 준수).

전국 풀 재수집(2026-07-29):
  - region_map.collection_targets() 의 전국 시군구를 **전 콘텐츠타입 스윕**으로 수집한다.
    contentTypeId 를 생략하면 한 응답에 전 타입이 섞여 오므로(실호출 확인), 지역당
    타입 5회가 아니라 보통 1회(대도시 2~5회)로 끝난다 — 콜은 줄고 타입 커버리지는 넓어진다.
  - `--resume` 로 이미 스윕한 시군구(seed.swept_pairs)를 건너뛰어 여러 날에 나눠 실행 가능.
  - **법정동 코드는 item 의 lDongRegnCd(2)+lDongSignguCd(3) 에서 도출**한다(추측 금지).
  - **additive**: 기존 spots_seed.json 을 로드해 기존 스팟/지역을 그대로 보존하고,
    이미 존재하는 법정동 region_code 는 재수집·덮어쓰기하지 않는다(데모 4지역 불변).
  - **콜 예산 가드**: KorService2 호출 수가 budget 을 넘으면 중단하고 실제 커버리지를
    정직히 로그로 남긴다(지어내지 않는다).

수집 대상 contentTypeId: 12(관광지) 14(문화시설) 28(레포츠) 38(쇼핑) 39(음식점).
축제(15)·여행코스(25)·숙박(32)은 '장소 카드'로 부적합해 제외(category_map).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from ..clients.tourapi_client import (
    fetch_service_page,
    TourApiError,
    TourApiQuotaError,
    fetch_area_based_list,
    fetch_area_based_page,
)
from ..config import settings
from ..util.images import normalize_image_url
from ..util.time import KST, to_iso_kst
from . import category_map
from .region_map import (
    TOURAPI_REGIONS,
    CollectionTarget,
    all_regions,
    collection_targets,
)

logger = logging.getLogger("sumeungil.spots.collector")

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_PATH = DATA_DIR / "spots_seed.json"
# 법정동 code→이름 맵(ldongCode2 표준 regn 실호출). spillover(타깃 시군구가 인접 법정동
# 스팟을 반환)로 라벨이 틀어지는 것을 실코드 기준으로 교정한다. 없는 code 는 타깃명 fallback.
NAME_MAP_PATH = DATA_DIR / "ldong_name_map.json"


def _load_name_map() -> dict:
    if not NAME_MAP_PATH.exists():
        return {}
    try:
        return json.loads(NAME_MAP_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}

# 수집할 콘텐츠 타입 (장소성 있는 것만) — 전 타입 스윕에서는 응답을 로컬 필터링한다.
CONTENT_TYPES = ["12", "14", "28", "38", "39"]
LITE_CONTENT_TYPES = ["12"]  # (구) LITE 대표 1개 — collect_demo_only 하위호환용 잔존
LITE_NUM_OF_ROWS = 30        # (구) LITE 캡 — collect_demo_only 하위호환용 잔존

# ── 전국 풀 재수집(2026-07-29) ────────────────────────────────────────────
# 직전 전국확장은 LITE 175지역을 관광지(12) 1종·최대 30개만 수집해 중앙값 30·
# 43지역이 ≤10개에 머물렀다(대표 지적: "다른 지역도 스팟이 거의 안 뜬다").
#
# 이번 방식(실호출로 검증한 두 가지 사실에 기반):
#   (1) numOfRows 는 300 까지 정상 응답 — 100 캡이 불필요했다.
#   (2) contentTypeId 를 **생략**하면 그 시군구의 전 콘텐츠타입이 한 응답에 섞여 온다
#       (서울 종로구 totalCount=346, 12/14/15/25/28/32/38/39 혼재 확인).
# → 지역당 "타입 5회 × 100건" 대신 "전 타입 1~N회 × 300건" 스윕으로 바꾼다.
#   콜은 줄고(지역당 보통 1콜) 커버리지는 5개 타입 전부로 넓어진다.
# 제외 타입(15 축제·25 여행코스·32 숙박)은 _map_item 에서 로컬 필터링한다.
NUM_OF_ROWS = 300        # 페이지 크기(실측 상한 확인)
MAX_PAGES_PER_TARGET = 5  # 지역당 최대 5페이지(=1,500건) — 초대형 시군구 방어
DEFAULT_BUDGET = 900     # KorService2 호출 상한(무료 1,000/일 한도 내 안전 여유)


def _to_float(v) -> float | None:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f != 0.0 else None


def _legal_dong_code(raw: dict) -> str | None:
    """item 의 lDongRegnCd(2)+lDongSignguCd(3) → 표준 법정동 5자리. 없으면 None.

    세종특별자치시 등 '단층 시'는 TourAPI 가 lDongRegnCd 에 5자리 완성 법정동 코드
    (세종=36110)를 그대로 담고 lDongSignguCd 에도 같은 값을 넣는다. 이 경우 regn 을
    그대로 5자리 코드로 사용한다(2+3 조립이 아님). 이 분기가 없으면 세종 스팟이 전부
    스킵되어 0건이 된다(2026-07-24 세종 보강에서 원인 확인).
    """
    regn = str(raw.get("lDongRegnCd", "")).strip()
    sig = str(raw.get("lDongSignguCd", "")).strip()
    if not regn.isdigit():
        return None
    if len(regn) == 5:  # 세종형: 이미 완성된 법정동 5자리
        return regn
    if not sig.isdigit():
        return None
    code = f"{int(regn):02d}{int(sig):03d}"
    return code if len(code) == 5 else None


# 대한민국 영토 대략 bbox(제주·울릉·마라도 포함 여유). 원천 좌표 오류 방어용.
KR_BBOX = (33.0, 38.7, 124.5, 132.0)  # lat_min, lat_max, lng_min, lng_max


def in_kr_bbox(lat: float, lng: float) -> bool:
    lat_min, lat_max, lng_min, lng_max = KR_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


def _map_item(raw: dict) -> dict | None:
    """원천 item → 로컬 스토어 스팟 레코드(dict).

    region_code 는 item 의 법정동 코드에서 도출한다(추측 금지).
    좌표/제목/법정동코드 없으면 None(스킵).
    """
    ct = str(raw.get("contenttypeid", "")).strip()
    if ct in category_map.EXCLUDED_CONTENT_TYPES:
        return None

    name = str(raw.get("title", "")).strip()
    lng = _to_float(raw.get("mapx"))
    lat = _to_float(raw.get("mapy"))
    contentid = str(raw.get("contentid", "")).strip()
    region_code = _legal_dong_code(raw)
    if not name or lat is None or lng is None or not contentid.isdigit() or not region_code:
        return None
    if not in_kr_bbox(lat, lng):
        # 원천에 실제로 존재하는 좌표 오류(예: 19.694/117.993 placeholder 를 그대로 담은 item).
        # 거리 계산·지도 표시를 망가뜨리므로 적재하지 않는다(값을 임의로 고치지도 않는다).
        return None

    cat1 = str(raw.get("cat1", "")).strip()
    cat2 = str(raw.get("cat2", "")).strip()
    cat3 = str(raw.get("cat3", "")).strip()
    category = category_map.classify_category(ct, cat1, cat2, cat3)

    image_url = normalize_image_url(raw.get("firstimage"))
    has_image = image_url is not None
    tag_values = category_map.spot_tag_values(category)

    return {
        "id": int(contentid),
        "name": name,
        "category": category,
        "region_code": region_code,
        "address": str(raw.get("addr1", "")).strip() or None,
        "lat": lat,
        "lng": lng,
        "tag_values": tag_values,  # [[axis, value], ...]
        "themes": {"pet_allowed": None, "barrier_free": None, "wellness": None},
        "is_hidden_gem": category_map.is_hidden_gem(category, has_image),
        "content_type_id": ct,
        # 대표이미지는 이 목록 응답에 이미 들어 있다(firstimage). 예전에는 has_image 판정에만
        # 쓰고 버렸는데, 그 탓에 런타임이 스팟 1건마다 detailCommon2 를 1콜씩 때려야 했다
        # (= 오퍼레이션 일일 한도를 태우는 구조. 2026-07-29 실제로 429 로 전면 소진됨).
        # 여기서 적재해 두면 런타임 대표이미지 조회 원천 콜이 0 이 된다.
        "image_url": image_url,
        "cpyrht_div_cd": str(raw.get("cpyrhtDivCd", "")).strip() or None,
    }


_SIGUNGU_SUFFIX = ("시", "군", "구")


def _names_from_address(address: str | None) -> tuple[str | None, str | None]:
    """원천 주소 문자열 → (시도명, 시군구명). 판별 불가면 (None, None).

    ldong_name_map 에 없는 신설/개편 법정동 코드의 라벨을 원천 데이터로 채우기 위한 것.
    예: "전남광주통합특별시 여수시 돌산읍 무술목길 142-1" → ("전남광주통합특별시", "여수시")
    주소 형식이 다르면 이름을 지어내지 않고 None 을 돌려준다.
    """
    parts = str(address or "").split()
    if len(parts) < 2:
        return None, None
    sido, sigungu = parts[0], parts[1]
    if not sigungu.endswith(_SIGUNGU_SUFFIX):
        return sido, None
    return sido, sigungu


def _tour_area_names() -> dict[str, str]:
    """tourapi_area_index → {areaCode: 시도 약칭}. 예: {"5": "광주", "38": "전남"}"""
    try:
        idx = json.loads(
            (DATA_DIR / "tourapi_area_index.json").read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return {}
    return {str(k): str(v.get("sido_name", "")) for k, v in idx.items()}


def canonicalize_region_codes(store: dict) -> int:
    """표준 법정동 맵에 없는 신설 코드를 **같은 시군구의 기존 표준 코드**로 합친다(콜 0회).

    2026 개편으로 TourAPI 일부 item 이 '전남광주통합특별시'(lDongRegnCd=12) 코드를 담아
    오면서, 같은 여수시가 46130(기존)과 12130(신설)으로 쪼개져 지역 검색에 중복으로
    노출되는 문제가 생겼다. 아래 두 근거 중 하나로만 합치고, 둘 다 아니면 손대지 않는다.
      (1) 뒤 3자리와 시군구명이 동시에 일치하는 표준 코드가 있다 (12130 여수시 → 46130 여수시)
      (2) 그 지역을 수집할 때 쓴 TourAPI area 의 시도 약칭으로 후보가 하나로 좁혀진다
          (12270 남구 ← area=5"광주" → 광주광역시 남구 29155)
    """
    name_map = _load_name_map()
    if not name_map:
        return 0
    meta: dict[str, dict] = store.get("region_meta") or {}
    area_names = _tour_area_names()

    by_sigungu: dict[str, list[str]] = {}
    for code, v in name_map.items():
        by_sigungu.setdefault(str(v.get("sigungu_name", "")), []).append(code)

    remap: dict[str, str] = {}
    for code, m in meta.items():
        if code in name_map:
            continue  # 이미 표준 코드
        sigungu = str(m.get("sigungu_name", "")).strip()
        cands = by_sigungu.get(sigungu, [])
        target = None
        exact = [c for c in cands if c[2:] == code[2:]]
        if len(exact) == 1:
            target = exact[0]
        else:
            area_short = area_names.get(str(m.get("tour_area_code", "")), "")
            narrowed = [
                c for c in cands
                if area_short and str(name_map[c].get("sido_name", "")).startswith(area_short)
            ]
            if len(narrowed) == 1:
                target = narrowed[0]
        if target and target != code:
            remap[code] = target

    if not remap:
        return 0

    for s in store.get("spots", []):
        code = str(s.get("region_code"))
        if code in remap:
            s["region_code"] = remap[code]

    counts: dict[str, int] = {}
    for s in store.get("spots", []):
        code = str(s["region_code"])
        counts[code] = counts.get(code, 0) + 1
    store["region_counts"] = counts

    for code in remap:
        meta.pop(code, None)
    for code, c in counts.items():
        if code in meta:
            meta[code]["count"] = c
    stats = store.get("collection_stats")
    if isinstance(stats, dict):  # 통합 후 총계가 어긋나지 않게 갱신
        stats["total_regions"] = len(counts)
        stats["total_spots"] = sum(counts.values())

    logger.info("신설 코드 %d곳을 기존 표준 코드로 통합: %s", len(remap),
                ", ".join(f"{k}→{v}" for k, v in sorted(remap.items())))
    return len(remap)


def repair_region_labels(store: dict) -> int:
    """region_meta 중 라벨이 빈 지역을 해당 지역 스팟들의 주소에서 채운다(콜 0회).

    가장 흔한 (시도, 시군구) 조합을 채택한다. 주소가 없으면 그대로 둔다(지어내지 않음).
    """
    meta = store.get("region_meta") or {}
    by_code: dict[str, list[str]] = {}
    for s in store.get("spots", []):
        code = str(s.get("region_code"))
        m = meta.get(code)
        if not m or str(m.get("label", "")).strip():
            continue
        addr = s.get("address")
        if addr:
            by_code.setdefault(code, []).append(addr)

    fixed = 0
    for code, addrs in by_code.items():
        pairs = [_names_from_address(a) for a in addrs]
        pairs = [p for p in pairs if p[0] and p[1]]
        if not pairs:
            continue
        best = max(set(pairs), key=pairs.count)
        sido, sigungu = best
        meta[code]["sido_name"] = sido
        meta[code]["sigungu_name"] = sigungu
        meta[code]["label"] = f"{sido} {sigungu}".strip()
        fixed += 1
    if fixed:
        logger.info("라벨 없는 지역 %d곳을 원천 주소로 보정.", fixed)
    return fixed


def _load_existing() -> dict:
    if not SEED_PATH.exists():
        return {}
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("기존 시드 로드 실패(무시하고 새로 생성): %s", exc)
        return {}


class _Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def can_spend(self, n: int) -> bool:
        return self.used + n <= self.limit

    def spend(self, n: int = 1) -> None:
        self.used += n


async def _collect_targets(
    targets: list[CollectionTarget],
    existing_codes: set[str],
    existing_ids: set[int],
    demo_codes: set[str],
    budget: _Budget,
    client: httpx.AsyncClient,
) -> tuple[list[dict], dict[str, dict], dict[str, int], list[str]]:
    """전국 타깃 전 타입 스윕. (신규 스팟, 신규 region_meta, 신규 지역별 카운트, 완료 pair) 반환.

    - 타깃 시군구마다 contentTypeId 없이 300건 페이지를 totalCount 만큼 받아온다
      (지역당 보통 1콜, 대도시는 2~5콜). 우리가 쓰는 5개 타입만 _map_item 이 남긴다.
    - 기존 스팟은 id dedupe 로 보존(additive). 데모 4지역(demo_codes)은 spillover 로
      들어와도 스킵한다(계약 불변).
    - 콜 예산 소진 또는 원천 쿼터 초과(TourApiQuotaError) 시 즉시 중단하고, 어디까지
      수집했는지 정직히 로그로 남긴다(지어내지 않는다).
    """
    new_spots: list[dict] = []
    region_meta: dict[str, dict] = {}
    new_counts: dict[str, int] = {}
    swept: list[str] = []
    seen_ids = set(existing_ids)
    name_map = _load_name_map()
    stopped = False
    stop_reason = ""
    last_done_target = ""

    def _ingest(raw_items: list[dict], tgt: CollectionTarget) -> int:
        added = 0
        for raw in raw_items:
            rec = _map_item(raw)
            if rec is None:
                continue
            code = rec["region_code"]
            if code in demo_codes:        # 데모 4지역 보존(계약 불변)
                continue
            if rec["id"] in seen_ids:     # 기존/이번 중복 제거(additive)
                continue
            seen_ids.add(rec["id"])
            new_spots.append(rec)
            new_counts[code] = new_counts.get(code, 0) + 1
            added += 1
            if code not in existing_codes and code not in region_meta:
                nm = name_map.get(code)
                if nm:
                    sido, sigungu = nm["sido_name"], nm["sigungu_name"]
                else:
                    # name_map 에 없는 신설/개편 코드(예: 2026 전남광주통합특별시 12xxx)는
                    # **원천 item 의 주소**에서 이름을 취한다(추측이 아니라 원천 데이터).
                    sido, sigungu = _names_from_address(rec.get("address"))
                region_meta[code] = {
                    "region_code": code,
                    "area_cd": code[:2],
                    "label": f"{sido or ''} {sigungu or ''}".strip(),
                    "sido_name": sido,
                    "sigungu_name": sigungu,
                    # 다음 보강 때 커버리지 판단 근거가 되도록 원천 pair 를 기록한다.
                    "tour_area_code": tgt.tour_area_code,
                    "tour_sigungu_code": tgt.tour_sigungu_code,
                }
        return added

    for tgt in targets:
        if not budget.can_spend(1):
            logger.info("콜 예산 도달(%d/%d) — %s %s 부터 미수집(정직 보고).",
                        budget.used, budget.limit, tgt.tour_area_name, tgt.tour_sigungu_name)
            stopped = True
            stop_reason = "budget"
            break

        tgt_added = 0
        fetched = 0
        total = None
        page = 1
        failed = False
        while page <= MAX_PAGES_PER_TARGET:
            if not budget.can_spend(1):
                stopped = True
                stop_reason = "budget"
                break
            budget.spend(1)
            try:
                raw_items, total_count = await fetch_area_based_page(
                    tgt.tour_area_code, tgt.tour_sigungu_code, None,
                    num_of_rows=NUM_OF_ROWS, page_no=page, client=client,
                )
            except TourApiQuotaError as exc:
                logger.warning("원천 일일 쿼터 초과 — 즉시 중단(%s): %s",
                               f"{tgt.tour_area_name} {tgt.tour_sigungu_name}", exc)
                stopped = True
                stop_reason = "quota"
                failed = True
                break
            except TourApiError as exc:
                logger.warning("수집 실패 area=%s sig=%s p=%d: %s",
                               tgt.tour_area_code, tgt.tour_sigungu_code, page, exc)
                failed = True
                break
            total = total_count if total is None else total
            tgt_added += _ingest(raw_items, tgt)
            fetched += len(raw_items)
            if not raw_items or len(raw_items) < NUM_OF_ROWS or fetched >= total_count:
                break  # 원천 소진(지어내지 않음)
            page += 1

        if stopped and stop_reason == "quota":
            break

        if not failed:
            swept.append(f"{tgt.tour_area_code}:{tgt.tour_sigungu_code}")
            last_done_target = f"{tgt.tour_area_name} {tgt.tour_sigungu_name}"
        logger.info("[%s] %s(%s) 원천 %s건 → +%d스팟(신규), 콜 %d/%d",
                    tgt.tour_area_name, tgt.tour_sigungu_name, tgt.tour_sigungu_code,
                    "?" if total is None else total, tgt_added, budget.used, budget.limit)
        if stopped:
            break

    for code, cnt in new_counts.items():
        if code in region_meta:
            region_meta[code]["count"] = cnt
    if stopped:
        logger.info("조기 종료(%s): 마지막 완료 타깃=%s, 처리 %d/%d 타깃 (이후 미수집).",
                    stop_reason, last_done_target, len(swept), len(targets))
    else:
        logger.info("전 타깃 처리 완료(%d곳). 콜 %d/%d 사용.",
                    len(swept), budget.used, budget.limit)
    return new_spots, region_meta, new_counts, swept


async def collect_demo_only() -> dict:
    """기존 동작(데모 4지역 재수집). --demo-only 로만 사용."""
    spots: list[dict] = []
    seen_ids: set[int] = set()
    region_counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        for region in all_regions():
            count = 0
            for ct in CONTENT_TYPES:
                try:
                    raw_items = await fetch_area_based_list(
                        region.tour_area_code, region.tour_sigungu_code, ct,
                        num_of_rows=NUM_OF_ROWS, client=client,
                    )
                except TourApiError as exc:
                    logger.warning("수집 실패 region=%s ct=%s: %s", region.region_code, ct, exc)
                    continue
                for raw in raw_items:
                    rec = _map_item(raw)
                    if rec is None or rec["id"] in seen_ids:
                        continue
                    # 데모 재수집은 매핑 고정 region_code 를 신뢰(전주 완산/덕진 병합 유지)
                    rec["region_code"] = region.region_code
                    seen_ids.add(rec["id"])
                    spots.append(rec)
                    count += 1
            region_counts[region.region_code] = count
            logger.info("수집 완료 region=%s(%s) count=%d",
                        region.region_name, region.region_code, count)
    return {
        "generated_at": to_iso_kst(datetime.now(KST)),
        "source": "tourapi_local_store",
        "vector_version": 1,
        "region_counts": region_counts,
        "spots": spots,
    }


def _demo_codes() -> set[str]:
    """데모 4지역 법정동 코드(spillover 로 들어와도 보존 — 계약 불변)."""
    return set(TOURAPI_REGIONS.keys())


def _merge_counts(existing: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    """지역별 카운트 additive 병합(기존 지역에 신규 스팟이 더해질 수 있음)."""
    out = dict(existing)
    for code, c in new.items():
        out[code] = out.get(code, 0) + c
    return out


async def _run_sweep(targets: list[CollectionTarget], budget_limit: int,
                     resume: bool, scope: str) -> dict:
    """공통 수집 실행부: 기존 시드 로드 → 타깃 스윕 → additive 병합된 새 스토어 반환."""
    existing = _load_existing()
    existing_spots: list[dict] = list(existing.get("spots", []))
    existing_codes: set[str] = {str(s.get("region_code")) for s in existing_spots}
    existing_ids: set[int] = {
        int(s["id"]) for s in existing_spots if str(s.get("id", "")).lstrip("-").isdigit()
    }
    existing_counts: dict[str, int] = dict(existing.get("region_counts", {}))
    existing_meta: dict[str, dict] = dict(existing.get("region_meta", {}))
    prev_swept: list[str] = list(existing.get("swept_pairs", []))

    if resume and prev_swept:
        done = set(prev_swept)
        before = len(targets)
        targets = [t for t in targets
                   if f"{t.tour_area_code}:{t.tour_sigungu_code}" not in done]
        logger.info("--resume: 이미 스윕한 %d곳 제외 → 남은 타깃 %d/%d",
                    before - len(targets), len(targets), before)

    budget = _Budget(budget_limit)
    logger.info("전 타입 스윕 시작(scope=%s): 타깃 %d곳(FULL우선 %d), 기존 지역 %d곳, 예산 %d콜",
                scope, len(targets), sum(1 for t in targets if t.tier == "full"),
                len(existing_counts), budget_limit)

    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        new_spots, new_meta, new_counts, swept = await _collect_targets(
            targets, existing_codes, existing_ids, _demo_codes(), budget, client,
        )

    all_spots = existing_spots + new_spots
    all_counts = _merge_counts(existing_counts, new_counts)
    all_meta = {**existing_meta, **new_meta}
    for code, c in all_counts.items():
        if code in all_meta:
            all_meta[code]["count"] = c

    store = {
        "generated_at": to_iso_kst(datetime.now(KST)),
        "source": "tourapi_local_store",
        "vector_version": 1,
        "region_counts": all_counts,
        "region_meta": all_meta,
        "swept_pairs": sorted(set(prev_swept) | set(swept)),
        "spots": all_spots,
        "collection_stats": {
            "budget": budget_limit,
            "calls_used": budget.used,
            "targets_planned": len(targets),
            "targets_swept": len(swept),
            "new_regions": len(new_counts),
            "new_spots": len(new_spots),
            "total_regions": len(all_counts),
            "total_spots": len(all_spots),
            "scope": scope,
        },
    }
    canonicalize_region_codes(store)  # 신설 코드 → 기존 표준 코드 통합(콜 0회)
    repair_region_labels(store)       # 그래도 라벨이 빈 지역은 원천 주소로 보정(콜 0회)
    return store


async def collect_nationwide(budget_limit: int, resume: bool = False) -> dict:
    """전국 전 타입 스윕(additive). 기존 spots_seed.json 은 전부 보존하고 신규만 더한다."""
    return await _run_sweep(collection_targets(), budget_limit, resume, "nationwide")


async def collect_demo_boost(budget_limit: int) -> dict:
    """데모 4지역(해운대·경주·강릉·전주)을 전 타입 스윕으로 **추가** 수집(additive).

    전국 스윕은 데모 4지역을 계약 보존 목적으로 제외하는데, 이 4곳은 직전 수집에서
    타입당 50건 캡에 걸려 있었다. 여기서는 기존 스팟/ID 를 하나도 지우지 않고,
    원천에만 있고 우리에게 없던 것을 더한다. region_code 는 데모 고정 매핑을 그대로
    쓴다(전주 완산/덕진 병합 유지 — 기존 계약 불변).
    """
    existing = _load_existing()
    existing_spots: list[dict] = list(existing.get("spots", []))
    existing_ids: set[int] = {
        int(s["id"]) for s in existing_spots if str(s.get("id", "")).lstrip("-").isdigit()
    }
    existing_counts: dict[str, int] = dict(existing.get("region_counts", {}))
    budget = _Budget(budget_limit)
    new_spots: list[dict] = []
    new_counts: dict[str, int] = {}

    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        for region in all_regions():
            added, fetched, page, total = 0, 0, 1, 0
            while page <= MAX_PAGES_PER_TARGET and budget.can_spend(1):
                budget.spend(1)
                try:
                    raw_items, total = await fetch_area_based_page(
                        region.tour_area_code, region.tour_sigungu_code, None,
                        num_of_rows=NUM_OF_ROWS, page_no=page, client=client,
                    )
                except TourApiQuotaError as exc:
                    logger.warning("원천 쿼터 초과 — 데모 보강 중단: %s", exc)
                    raw_items = []
                    break
                except TourApiError as exc:
                    logger.warning("데모 보강 실패 region=%s p=%d: %s",
                                   region.region_code, page, exc)
                    break
                for raw in raw_items:
                    rec = _map_item(raw)
                    if rec is None or rec["id"] in existing_ids:
                        continue
                    rec["region_code"] = region.region_code  # 데모 고정 매핑 유지
                    existing_ids.add(rec["id"])
                    new_spots.append(rec)
                    new_counts[region.region_code] = new_counts.get(region.region_code, 0) + 1
                    added += 1
                fetched += len(raw_items)
                if not raw_items or len(raw_items) < NUM_OF_ROWS or fetched >= total:
                    break
                page += 1
            logger.info("[데모] %s 원천 %d건 → +%d스팟(신규), 콜 %d/%d",
                        region.region_name, total, added, budget.used, budget.limit)

    all_counts = _merge_counts(existing_counts, new_counts)
    store = {
        "generated_at": to_iso_kst(datetime.now(KST)),
        "source": "tourapi_local_store",
        "vector_version": 1,
        "region_counts": all_counts,
        "region_meta": dict(existing.get("region_meta", {})),
        "swept_pairs": list(existing.get("swept_pairs", [])),
        "spots": existing_spots + new_spots,
        "collection_stats": {
            "budget": budget_limit,
            "calls_used": budget.used,
            "targets_planned": len(all_regions()),
            "targets_swept": len(all_regions()),
            "new_regions": 0,
            "new_spots": len(new_spots),
            "total_regions": len(all_counts),
            "total_spots": len(existing_spots) + len(new_spots),
            "scope": "demo_boost",
        },
    }
    for code, c in all_counts.items():
        if code in store["region_meta"]:
            store["region_meta"][code]["count"] = c
    return store


async def backfill_images(budget_limit: int, resume: bool = True) -> dict:
    """기존 시드 스팟들의 `image_url`/`cpyrht_div_cd` 를 areaBasedList2 로 **일괄 보강**한다.

    왜 필요한가 (2026-07-29 실측):
      런타임 대표이미지 조회가 스팟 1건당 detailCommon2 1콜이었다. 홈 한 지역만 열어도 수십 콜,
      17개 지역 감사에서는 500콜을 넘겨 **detailCommon2 오퍼레이션 일일 한도가 429 로 소진**됐고
      그 시점부터 전 지역 사진이 통째로 null 이 됐다(= 표면 커버리지 0%). areaBasedList2 는
      한 콜에 300건 × firstimage 를 주므로, 21k 스팟 전량을 수백 콜로 채울 수 있다.

    보장(무회귀):
      - 스팟을 추가/삭제하지 않는다. 기존 레코드의 **id 매칭분에만** 두 필드를 채운다.
      - name/category/region_code/좌표/태그 등 기존 필드는 건드리지 않는다.
      - 원천에 사진이 없으면 image_url=None 을 그대로 기록한다(지어내지 않음).
    resume=True 면 이미 보강한 pair(`image_backfill_pairs`)를 건너뛴다 — 쿼터 분할 실행용.
    """
    store = _load_existing()
    spots: list[dict] = store.get("spots", [])
    by_id: dict[int, dict] = {}
    for s in spots:
        try:
            by_id[int(s["id"])] = s
        except (KeyError, TypeError, ValueError):
            continue

    # 전국 타깃 + **데모 4지역**. collection_targets() 는 데모 지역을 '이미 수집됨'으로 제외하지만,
    # 이미지 보강은 스팟을 추가하는 게 아니라 기존 스팟의 필드를 채우는 것이므로 데모도 훑어야 한다
    # (안 훑으면 정작 데모 화면인 해운대·경주·강릉·전주가 사진 미판정으로 남는다).
    targets = list(collection_targets()) + [
        CollectionTarget(r.tour_area_code, r.tour_sigungu_code, r.region_name, "", "full")
        for r in all_regions()
    ]
    done_pairs: set[str] = set(store.get("image_backfill_pairs", [])) if resume else set()
    if done_pairs:
        before = len(targets)
        targets = [t for t in targets
                   if f"{t.tour_area_code}:{t.tour_sigungu_code}" not in done_pairs]
        logger.info("--resume: 이미 보강한 %d곳 제외 → 남은 타깃 %d/%d",
                    before - len(targets), len(targets), before)

    budget = _Budget(budget_limit)
    filled = 0        # 이번 실행에서 사진 URL 을 새로 채운 스팟 수
    marked_none = 0   # 원천에 사진이 없어 None 으로 확정한 스팟 수
    matched = 0       # 원천 item 이 시드 스팟과 id 매칭된 수
    swept: list[str] = []
    stopped_reason = ""

    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        for tgt in targets:
            fetched, page, total = 0, 1, 0
            ok = True
            while page <= MAX_PAGES_PER_TARGET:
                if not budget.can_spend(1):
                    stopped_reason = "budget"
                    ok = False
                    break
                budget.spend(1)
                try:
                    raw_items, total = await fetch_area_based_page(
                        tgt.tour_area_code, tgt.tour_sigungu_code, None,
                        num_of_rows=NUM_OF_ROWS, page_no=page, client=client,
                    )
                except TourApiQuotaError as exc:
                    logger.warning("원천 일일 쿼터 초과 — 이미지 보강 중단: %s", exc)
                    stopped_reason = "quota"
                    ok = False
                    break
                except TourApiError as exc:
                    logger.warning("이미지 보강 실패 area=%s sig=%s p=%d: %s",
                                   tgt.tour_area_code, tgt.tour_sigungu_code, page, exc)
                    ok = False
                    break
                for raw in raw_items:
                    cid = str(raw.get("contentid", "")).strip()
                    if not cid.isdigit():
                        continue
                    spot = by_id.get(int(cid))
                    if spot is None:
                        continue  # 시드에 없는 스팟은 여기서 새로 만들지 않는다(스코프 밖)
                    matched += 1
                    url = normalize_image_url(raw.get("firstimage"))
                    spot["cpyrht_div_cd"] = str(raw.get("cpyrhtDivCd", "")).strip() or None
                    if url:
                        if not spot.get("image_url"):
                            filled += 1
                        spot["image_url"] = url
                    else:
                        if "image_url" not in spot:
                            marked_none += 1
                        spot["image_url"] = None
                fetched += len(raw_items)
                if not raw_items or len(raw_items) < NUM_OF_ROWS or fetched >= total:
                    break
                page += 1
            if ok:
                swept.append(f"{tgt.tour_area_code}:{tgt.tour_sigungu_code}")
            if stopped_reason:
                break

    store["image_backfill_pairs"] = sorted(done_pairs | set(swept))
    with_img = sum(1 for s in spots if s.get("image_url"))
    known = sum(1 for s in spots if "image_url" in s)
    store["image_backfill_stats"] = {
        "ran_at": to_iso_kst(datetime.now(KST)),
        "calls_used": budget.used,
        "budget": budget_limit,
        "pairs_done": len(store["image_backfill_pairs"]),
        "pairs_total": len(collection_targets()),
        "matched_items": matched,
        "filled_urls": filled,
        "confirmed_no_image": marked_none,
        "spots_with_image": with_img,
        "spots_resolved": known,
        "spots_total": len(spots),
        "stopped_reason": stopped_reason or "completed",
    }
    logger.info(
        "이미지 보강: 콜 %d, 매칭 %d건 → 사진 확보 %d / 사진없음 확정 %d. "
        "전체 시드 %d곳 중 판정완료 %d곳, 사진보유 %d곳(%.1f%%). 종료사유=%s",
        budget.used, matched, filled, marked_none, len(spots), known, with_img,
        100.0 * with_img / len(spots) if spots else 0.0, stopped_reason or "completed",
    )
    return store


# 반려동물·무장애 목록은 전국 1만 건 안팎이라 페이지 크기를 크게 잡아 콜 수를 아낀다(실측: 각 ~9.7k 건).
ACCESS_NUM_OF_ROWS = 1000
ACCESS_MAX_PAGES = 30
PET_NOTE_MAX = 80


def _pet_note(raw: dict) -> str | None:
    """detailPetTour2 한 건 → 코스 선택기/화면용 한 줄 ("전구역 동반가능 · 전 견종 · 목줄 착용")."""
    parts = [str(raw.get(k, "")).strip() for k in ("acmpyTypeCd", "acmpyPsblCpam", "acmpyNeedMtr")]
    note = " · ".join(p for p in parts if p)
    return note[:PET_NOTE_MAX] or None


async def _fetch_all(service_path: str, extra: dict, budget: "_Budget", client: httpx.AsyncClient) -> list[dict]:
    """목록 오퍼레이션 전 페이지 수집. 쿼터/예산 소진 시 그때까지 모은 것만 반환(부분 보강 허용)."""
    out: list[dict] = []
    page = 1
    while page <= ACCESS_MAX_PAGES and budget.can_spend(1):
        budget.spend(1)
        items, total = await fetch_service_page(
            service_path, extra, num_of_rows=ACCESS_NUM_OF_ROWS, page_no=page, client=client,
        )
        out.extend(items)
        if not items or len(out) >= total:
            break
        page += 1
    return out


async def enrich_access(budget_limit: int) -> dict:
    """기존 시드의 `themes.pet_allowed` / `themes.barrier_free` 를 관광공사 데이터로 채운다 (2026-09-07).

    대표 지적: 두 필드가 시드 21k 전부 null 이라 "반려동물 동반"·"휠체어" 태그 필터가 아무것도
    못 걸렀다. 원천:
      - 반려동물: `KorService2/detailPetTour2` (contentId 없이 호출하면 반려동물 동반 가능 관광지
        전체 목록, 실측 9,691건) → 매칭된 스팟 pet_allowed=True + pet_note(동반 유형·견종·준비물)
      - 무장애: `KorWithService2/areaBasedList2` (열린관광지 목록, 실측 9,664건) → barrier_free=True
    목록에 없는 스팟은 **None 그대로**(불가로 단정하지 않는다 — 원천이 "없음"을 주지 않으므로).
    스팟 추가/삭제 없음, 다른 필드 불변. 콜 수는 페이지 1000건 기준 각 ~10회.
    """
    store = _load_existing()
    spots: list[dict] = store.get("spots", [])
    by_id: dict[int, dict] = {}
    for s in spots:
        try:
            by_id[int(s["id"])] = s
        except (KeyError, TypeError, ValueError):
            continue

    budget = _Budget(budget_limit)
    stopped_reason = ""
    pet_items: list[dict] = []
    with_items: list[dict] = []
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
        try:
            pet_items = await _fetch_all("KorService2/detailPetTour2", {}, budget, client)
            with_items = await _fetch_all("KorWithService2/areaBasedList2", {"arrange": "A"}, budget, client)
        except TourApiQuotaError as exc:
            logger.warning("원천 일일 쿼터 초과 — 접근성 보강 부분 중단: %s", exc)
            stopped_reason = "quota"
        except TourApiError as exc:
            logger.warning("접근성 보강 원천 오류 — 부분 중단: %s", exc)
            stopped_reason = "error"

    pet_filled = with_filled = 0
    for raw in pet_items:
        cid = str(raw.get("contentid", "")).strip()
        spot = by_id.get(int(cid)) if cid.isdigit() else None
        if spot is None:
            continue
        themes = spot.setdefault("themes", {"pet_allowed": None, "barrier_free": None, "wellness": None})
        if themes.get("pet_allowed") is not True:
            pet_filled += 1
        themes["pet_allowed"] = True
        note = _pet_note(raw)
        if note:
            spot["pet_note"] = note
    for raw in with_items:
        cid = str(raw.get("contentid", "")).strip()
        spot = by_id.get(int(cid)) if cid.isdigit() else None
        if spot is None:
            continue
        themes = spot.setdefault("themes", {"pet_allowed": None, "barrier_free": None, "wellness": None})
        if themes.get("barrier_free") is not True:
            with_filled += 1
        themes["barrier_free"] = True

    pet_total = sum(1 for s in spots if (s.get("themes") or {}).get("pet_allowed") is True)
    with_total = sum(1 for s in spots if (s.get("themes") or {}).get("barrier_free") is True)
    store["access_enrich_stats"] = {
        "ran_at": to_iso_kst(datetime.now(KST)),
        "calls_used": budget.used,
        "pet_source_items": len(pet_items),
        "with_source_items": len(with_items),
        "pet_filled_now": pet_filled,
        "barrier_free_filled_now": with_filled,
        "spots_pet_allowed": pet_total,
        "spots_barrier_free": with_total,
        "spots_total": len(spots),
        "stopped_reason": stopped_reason or "completed",
    }
    logger.info(
        "접근성 보강: 콜 %d, 원천 반려동물 %d건·무장애 %d건 → 시드 매칭 반려동물 %d곳(신규 %d)·무장애 %d곳(신규 %d) / 전체 %d. 종료사유=%s",
        budget.used, len(pet_items), len(with_items), pet_total, pet_filled, with_total, with_filled,
        len(spots), stopped_reason or "completed",
    )
    return store


async def collect_area(area_code: str, budget_limit: int, resume: bool = False) -> dict:
    """특정 TourAPI area 만 additive 스윕(세종 보강 등). 기존 시드/지역 전부 보존."""
    code = str(area_code).strip()
    targets = [t for t in collection_targets() if t.tour_area_code == code]
    return await _run_sweep(targets, budget_limit, resume, f"area={code}")


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # serviceKey 노출 방지
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="TourAPI 스팟 수집기")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help=f"KorService2 콜 상한 (기본 {DEFAULT_BUDGET})")
    parser.add_argument("--demo-only", action="store_true",
                        help="데모 4지역만 재수집(기존 동작)")
    parser.add_argument("--area", type=str, default=None,
                        help="특정 TourAPI area 코드만 additive 보강 수집(예: 8=세종)")
    parser.add_argument("--resume", action="store_true",
                        help="이전 실행에서 이미 스윕한 시군구(swept_pairs)는 건너뛴다(쿼터 분할 실행용)")
    parser.add_argument("--demo-boost", action="store_true",
                        help="데모 4지역을 전 타입 스윕으로 additive 보강(기존 스팟·매핑 보존)")
    parser.add_argument("--repair-labels", action="store_true",
                        help="API 호출 없이 라벨 빈 지역을 기존 스팟 주소로 보정만 하고 저장")
    parser.add_argument("--canonicalize", action="store_true",
                        help="API 호출 없이 신설 법정동 코드(예: 12xxx)를 기존 표준 코드로 통합")
    parser.add_argument("--backfill-images", action="store_true",
                        help="기존 시드 스팟의 대표이미지(image_url)를 areaBasedList2 로 일괄 보강"
                             " — 스팟 추가/삭제 없음. --no-resume 로 전체 재보강")
    parser.add_argument("--no-resume", action="store_true",
                        help="--backfill-images 에서 이미 보강한 지역도 다시 훑는다")
    parser.add_argument("--enrich-access", action="store_true",
                        help="기존 시드의 반려동물(pet_allowed)·무장애(barrier_free) 를 관광공사 목록으로 채운다"
                             " — 스팟 추가/삭제 없음, 콜 ~20회")
    parser.add_argument("--prune-bad-geo", action="store_true",
                        help="API 호출 없이 한국 bbox 밖 좌표 스팟(원천 좌표 오류)을 시드에서 제거")
    args = parser.parse_args()

    _configure_logging()

    if args.enrich_access:
        store = asyncio.run(enrich_access(args.budget))
    elif args.backfill_images:
        store = asyncio.run(backfill_images(args.budget, resume=not args.no_resume))
    elif args.canonicalize:
        store = _load_existing()
        merged = canonicalize_region_codes(store)
        repair_region_labels(store)
        print(f"[collector] 신설 코드 {merged}곳 통합 (API 호출 0회)")
    elif args.prune_bad_geo:
        store = _load_existing()
        before = len(store.get("spots", []))
        kept = [s for s in store.get("spots", []) if in_kr_bbox(s["lat"], s["lng"])]
        store["spots"] = kept
        counts: dict[str, int] = {}
        for s in kept:
            code = str(s["region_code"])
            counts[code] = counts.get(code, 0) + 1
        store["region_counts"] = counts
        for code, c in counts.items():
            if code in store.get("region_meta", {}):
                store["region_meta"][code]["count"] = c
        print(f"[collector] 좌표 오류 스팟 {before - len(kept)}개 제거 (API 호출 0회)")
    elif args.repair_labels:
        store = _load_existing()
        fixed = repair_region_labels(store)
        print(f"[collector] 라벨 보정 {fixed}곳 (API 호출 0회)")
    elif args.demo_boost:
        store = asyncio.run(collect_demo_boost(args.budget))
    elif args.demo_only:
        store = asyncio.run(collect_demo_only())
    elif args.area:
        store = asyncio.run(collect_area(args.area, args.budget, args.resume))
    else:
        store = asyncio.run(collect_nationwide(args.budget, args.resume))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")

    total = len(store["spots"])
    print(f"[collector] 총 {total}개 스팟 적재 → {SEED_PATH}")
    if args.enrich_access:
        es = store.get("access_enrich_stats", {})
        print(f"  접근성 보강: 콜 {es.get('calls_used')}, 반려동물 {es.get('spots_pet_allowed')}곳"
              f"(신규 {es.get('pet_filled_now')}), 무장애 {es.get('spots_barrier_free')}곳"
              f"(신규 {es.get('barrier_free_filled_now')}) / {es.get('spots_total')} / {es.get('stopped_reason')}")
    if args.backfill_images:
        bs = store.get("image_backfill_stats", {})
        print(f"  이미지 보강: 콜 {bs.get('calls_used')}/{bs.get('budget')}, "
              f"지역 {bs.get('pairs_done')}/{bs.get('pairs_total')}, "
              f"사진보유 {bs.get('spots_with_image')}/{bs.get('spots_total')} "
              f"(판정완료 {bs.get('spots_resolved')}), 종료={bs.get('stopped_reason')}")
        return
    stats = store.get("collection_stats")
    if stats:
        print(f"  콜 사용 {stats['calls_used']}/{stats['budget']}, "
              f"스윕 {stats.get('targets_swept')}/{stats.get('targets_planned')}곳, "
              f"신규 +{stats['new_spots']}스팟, 전체 {stats['total_regions']}지역")


if __name__ == "__main__":
    main()
