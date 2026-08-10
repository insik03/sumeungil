"""홈 축제 배너 실연동 서비스 (부록 K) — **2원 소스 실호출 조립**.

소스 1. TourAPI searchFestival2 (KTO)          — 이미지 있음(firstimage), 법정동 코드 있음
소스 2. 전국문화축제표준데이터 (행안부, data.go.kr) — 이미지 없음, 주소만 → 주소로 지역 매칭

왜 2원인가 (2026-07-29 실호출 근거):
  - TourAPI 는 areaCode 를 넘기면 최신 축제가 전 지역 0건이다. 레코드의 `areacode` 필드가
    비고 법정동 코드(lDongRegnCd/lDongSignguCd)로 이관됐기 때문(클라이언트 docstring 참고).
    → areaCode 를 빼고 전국 스윕 후 법정동 코드로 메모리 필터하면 198건이 살아난다.
  - 표준데이터는 전국 1300건으로 커버리지가 넓지만 이미지가 없고 주소만 준다.
  - 둘을 합치면 "이미지 있는 축제 + 지자체 소규모 축제" 를 모두 채울 수 있다.

조립 규칙:
  - 기간창(기본): end_date >= 기준일(오늘) AND start_date <= 기준일+90일 → "진행중 + 90일 내 예정".
    축제 전용 페이지용으로 `window_days`(최대 365) / `month=YYYY-MM` 로 넓힐 수 있다(2026-07-29 확장).
    전국 스윕 캐시는 365일치를 보관하고, 요청별 기간 필터는 전부 메모리에서만 한다.
  - 지역: TourAPI 는 lDong 코드(=우리 region_code) 그대로, 표준데이터는 주소 파싱
    (festival_region_match). 매칭 실패분은 region_code 필터 요청에서는 빠지고
    전국 요청(region_code 생략)에서만 노출된다.
  - 중복 제거: 정규화 축제명(공백/회차/연도/기호 제거)이 같고 기간이 겹치면 동일 축제로 보고
    **TourAPI 쪽을 우선**(이미지·contentid 보유). 남는 쪽은 버린다.
  - 날짜/장소/제목은 원천값 그대로. 없는 값은 null 로 두고 지어내지 않는다.

성능/예산:
  - 전국 스윕 1회 결과(두 소스 병합본)를 6h 캐시. 지역 필터는 **메모리에서만** 수행하므로
    지역이 몇 개든 원천 호출 횟수는 고정이다(하루 4회 × 소스당 2~7페이지).
  - 스윕 기준일은 **항상 실제 오늘**이다. `as_of` 파라미터는 캐시된 전국 목록에 대한
    메모리 필터로만 동작한다 — 그래야 as_of 를 바꿔가며 부르는 요청이 원천 스윕을
    무한정 유발하지 못한다(캐시 키 폭발/원천 쿼터 소진 방지).
    대신 as_of 가 과거이거나 오늘+90일을 넘으면 스윕 범위 밖이라 결과가 부분적일 수 있다
    (원천이 "이미 끝난 축제"를 애초에 주지 않기 때문). as_of 는 데모/테스트용 knob 이다.
  - 동시 요청이 동시에 스윕하지 않도록 asyncio.Lock + 이중검사.
  - 한쪽 소스만 실패하면 성공분으로 응답하되 TTL 을 10분으로 줄여 곧 재시도한다.
    둘 다 실패면 캐시하지 않고 festivals: [] (graceful — 홈은 정적 폴백 유지 가능).

응답 스키마(부록 K: id/title/start_date/end_date/address/image_url/ongoing)는 **불변**.
FestivalsResponse 최상위에 `total`(필터 통과 전체 수, limit 절삭 전)만 additive 로 추가됐다.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import zlib
from datetime import date, timedelta

from ..cache.base import Cache
from ..clients import stddata_festival_client, tourapi_festival_client
from ..clients.stddata_festival_client import StdDataFestivalError
from ..clients.tourapi_festival_client import TourApiFestivalError
from ..regions.seed import REGIONS
from ..schemas.places import Festival, FestivalsResponse, RecommendRegion
from ..services.festival_region_match import (
    is_known_region,
    legal_dong_code,
    match_region_code,
    pick_address,
)
from ..services.spot_detail_service import _normalize_image_url  # http→https 승격 재사용
from ..spots.region_map import get_tourapi_region

logger = logging.getLogger("sumeungil.services.festival")

LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1, 200, 10   # 상한 30→200 (축제 전용 페이지. 기본값은 유지)
HORIZON_DAYS = 90            # 진행중 + 이 일수 내 시작하는 예정 축제까지 (요청 기본 윈도우)
WINDOW_MIN, WINDOW_MAX = 1, 365      # window_days 클램프 범위
SWEEP_HORIZON_DAYS = WINDOW_MAX      # 전국 스윕 캐시가 보유하는 최대 미래 범위(=365일)
CACHE_TTL_SEC = 6 * 60 * 60  # 6h — 축제 일정은 자주 안 바뀐다.
PARTIAL_TTL_SEC = 10 * 60    # 한쪽 소스 실패 시 짧은 TTL 로 조기 재시도

# 표준데이터에는 고유 숫자 ID 가 없다(Festival.id 는 int 계약). 축제명+기간+주소의 CRC32 를
# 900,000,000~989,999,999 구간에 매핑해 **결정적**으로 생성한다. TourAPI contentid 실측 최대가
# 4,091,713(7자리)이므로 이 구간과 충돌하지 않는다. 원천이 같으면 항상 같은 id 가 나온다.
_SYNTH_ID_BASE = 900_000_000
_SYNTH_ID_SPAN = 90_000_000

_sweep_lock = asyncio.Lock()

_RE_ROUND = re.compile(r"제?\s*\d+\s*회")          # "제14회", "14회"
_RE_YEAR = re.compile(r"(19|20)\d{2}\s*년?")        # "2026", "2026년"
_RE_NONWORD = re.compile(r"[^0-9A-Za-z가-힣]")


def _clamp_limit(limit: int) -> int:
    return max(LIMIT_MIN, min(LIMIT_MAX, limit))


def _clamp_window(window_days: int | None) -> int:
    """window_days 클램프(1~365). None 이면 기본 90일 — 홈 하위호환."""
    if window_days is None:
        return HORIZON_DAYS
    return max(WINDOW_MIN, min(WINDOW_MAX, window_days))


def month_bounds(month: str) -> tuple[str, str]:
    """'YYYY-MM' → ('YYYY-MM-01', 'YYYY-MM-<말일>'). 형식/범위 위반이면 ValueError.

    API 레이어가 이 함수로 400 판정을 한다(조용히 무시하지 않는다 — 오타가 잘못된 결과로
    이어지지 않게).
    """
    s = (month or "").strip()
    if len(s) != 7 or s[4] != "-" or not (s[:4].isdigit() and s[5:].isdigit()):
        raise ValueError("month must be 'YYYY-MM'")
    year, mon = int(s[:4]), int(s[5:])
    if not (1 <= mon <= 12) or not (2000 <= year <= 2100):
        raise ValueError("month out of range")
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _fmt_date_compact(raw) -> str | None:
    """YYYYMMDD(8자리 숫자) → 'YYYY-MM-DD'. 형식이 아니면 None(지어내지 않음)."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _fmt_date_iso(raw) -> str | None:
    """'YYYY-MM-DD' 검증 통과분만 반환(표준데이터는 이미 하이픈 포맷). 아니면 None."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    if not (s[:4].isdigit() and s[5:7].isdigit() and s[8:].isdigit()):
        return None
    return s


def _synth_id(*parts: str) -> int:
    digest = zlib.crc32("|".join(parts).encode("utf-8")) & 0xFFFFFFFF
    return _SYNTH_ID_BASE + (digest % _SYNTH_ID_SPAN)


def _norm_title(title: str) -> str:
    """중복 판정용 정규화 — 공백/회차/연도/기호 제거 후 소문자화."""
    s = _RE_ROUND.sub("", title)
    s = _RE_YEAR.sub("", s)
    s = _RE_NONWORD.sub("", s)
    return s.lower()


class _Entry:
    """지역코드가 붙은 축제 1건 (캐시 직렬화 단위).

    `description` 은 **표준데이터 원천 필드(`fstvlCo` 축제내용) 원문**만 담는다(부록 P.2).
    TourAPI 출신은 여기서 항상 None 이고, 상세 조회 때 detailCommon2 overview 로 채운다
    (목록 스윕에서 축제 198건의 상세를 부르면 오퍼레이션 한도를 태우기 때문).
    목록 응답(FestivalsResponse)에는 노출되지 않는다 — 부록 K 7필드 불변.
    """

    __slots__ = ("festival", "region_code", "source", "description")

    def __init__(
        self,
        festival: Festival,
        region_code: str | None,
        source: str,
        description: str | None = None,
    ) -> None:
        self.festival = festival
        self.region_code = region_code
        self.source = source
        self.description = description

    def to_dict(self) -> dict:
        return {
            "region_code": self.region_code,
            "source": self.source,
            "description": self.description,
            "festival": self.festival.model_dump(),
        }

    @staticmethod
    def from_dict(d: dict) -> "_Entry":
        return _Entry(
            Festival(**d["festival"]),
            d.get("region_code"),
            d.get("source", ""),
            d.get("description"),
        )


# ---------- 소스별 매핑 ----------

def _tour_entry(item: dict, today: date, horizon: str) -> _Entry | None:
    """TourAPI item → _Entry. 필수값 없거나 기간창 밖이면 None."""
    cid = item.get("contentid")
    title = item.get("title")
    start = _fmt_date_compact(item.get("eventstartdate"))
    end = _fmt_date_compact(item.get("eventenddate"))
    if not cid or not str(cid).strip().isdigit() or not title or not start or not end:
        return None

    today_s = today.isoformat()
    if end < today_s or start > horizon:
        return None

    addr = item.get("addr1")
    address = addr.strip() if isinstance(addr, str) and addr.strip() else None

    festival = Festival(
        id=int(str(cid).strip()),
        title=str(title).strip(),
        start_date=start,
        end_date=end,
        address=address,
        image_url=_normalize_image_url(item.get("firstimage")),
        ongoing=start <= today_s <= end,
    )

    # 1순위: 원천 법정동 코드. 다만 KTO 가 2026 광역 개편 코드(예: 12xxx '전남광주통합특별시')를
    # 쓰기 시작해 우리 사전에 없는 값이 섞인다(198건 중 17건, 2026-07-29 실측).
    # 그런 건은 주소로 재매칭한다 — 코드를 임의 변환해 지어내지 않는다.
    region = legal_dong_code(item)
    if not is_known_region(region):
        region = match_region_code(address) or region
    return _Entry(festival, region, "tourapi")


def _std_entry(item: dict, today: date, horizon: str) -> _Entry | None:
    """표준데이터 item → _Entry. 필수값 없거나 기간창 밖이면 None. image_url 은 항상 null."""
    title = item.get("fstvlNm")
    start = _fmt_date_iso(item.get("fstvlStartDate"))
    end = _fmt_date_iso(item.get("fstvlEndDate"))
    if not isinstance(title, str) or not title.strip() or not start or not end:
        return None
    if end < start:  # 원천 오류 레코드 — 고치지 않고 버린다
        return None

    today_s = today.isoformat()
    if end < today_s or start > horizon:
        return None

    address = pick_address(item)

    festival = Festival(
        id=_synth_id(title.strip(), start, end, address or ""),
        title=title.strip(),
        start_date=start,
        end_date=end,
        address=address,
        image_url=None,  # 표준데이터에 이미지 필드 없음 → 프론트 플레이스홀더
        ongoing=start <= today_s <= end,
    )
    # fstvlCo(축제내용) = 표준데이터의 유일한 설명 필드. 없거나 공백이면 None(지어내지 않음).
    raw_desc = item.get("fstvlCo")
    description = raw_desc.strip() if isinstance(raw_desc, str) and raw_desc.strip() else None
    return _Entry(festival, match_region_code(address), "stddata", description)


# ---------- 병합/정렬 ----------

def _dedupe(entries: list[_Entry]) -> list[_Entry]:
    """정규화 축제명이 같고 기간이 겹치면 동일 축제로 보고 앞선 것(=TourAPI)을 남긴다.

    버리는 쪽이 **우리 사전에 있는 region_code** 를 갖고 남는 쪽이 없으면 그 지역코드만
    넘겨받는다(예: TourAPI 가 미지의 12xxx 를 준 광주 축제를 표준데이터 주소매칭 29xxx 로 구제).
    제목·날짜·주소·이미지는 남는 쪽 원천값 그대로 둔다.

    **description 은 넘겨받지 않는다** — 동명·기간겹침으로 묶인 두 레코드가 실제로 다른 축제일
    가능성이 있어(회차·분관) 남의 설명문을 붙이면 오정보가 된다. TourAPI 쪽은 상세 조회 때
    자기 원천(detailCommon2 overview)에서 직접 가져온다(부록 P.2).
    """
    kept: list[_Entry] = []
    by_title: dict[str, list[_Entry]] = {}
    for e in entries:
        key = _norm_title(e.festival.title)
        if not key:
            kept.append(e)
            continue
        bucket = by_title.setdefault(key, [])
        twin = next(
            (
                k for k in bucket
                if e.festival.start_date <= k.festival.end_date
                and k.festival.start_date <= e.festival.end_date
            ),
            None,
        )
        if twin is not None:
            if not is_known_region(twin.region_code) and is_known_region(e.region_code):
                twin.region_code = e.region_code
            continue
        bucket.append(e)
        kept.append(e)
    return kept


def _sort_key(f: Festival):
    """정렬 규칙(2026-07-29 개정 — 상설공연 상단 독점 방지).

    ① 진행중(ongoing) 그룹 먼저, 그다음 예정 그룹.
    ② 진행중 그룹 안에서는 **종료일 빠른 순**(=종료 임박 순). 상설 전시·장기 공연은
       종료일이 멀어 자연히 뒤로 밀린다 → 곧 끝나는 축제가 위로 온다.
    ③ 예정 그룹 안에서는 **시작일 빠른 순**(가장 먼저 열리는 축제부터).
    ④ 동일 날짜면 이미지 있는 것 먼저 → 보조 날짜 → 제목(안정 정렬. 같은 입력 = 같은 순서).
    """
    img = 0 if f.image_url else 1
    if f.ongoing:
        return (0, f.end_date, img, f.start_date, f.title)
    return (1, f.start_date, img, f.end_date, f.title)


# ---------- 전국 스윕(캐시) ----------

async def _fetch_tour(today: date, horizon: str) -> list[_Entry]:
    items = await tourapi_festival_client.fetch_all_festivals(
        event_start_date=today.strftime("%Y%m%d")
    )
    return [e for e in (_tour_entry(i, today, horizon) for i in items) if e is not None]


async def _fetch_std(today: date, horizon: str) -> list[_Entry]:
    items = await stddata_festival_client.fetch_all_festivals()
    return [e for e in (_std_entry(i, today, horizon) for i in items) if e is not None]


async def _load_nationwide(cache: Cache) -> list[_Entry]:
    """**실제 오늘** 기준 전국 축제(2원 병합)를 캐시에서 얻거나 원천 스윕으로 채운다.

    캐시 키는 실제 날짜 하나뿐이다(as_of 로 키가 늘어나지 않는다) → 원천 호출 예산이 고정된다.
    """
    today = date.today()
    # v3: 스윕 보관 범위를 90일 → 365일로 확대(month/window_days 확장 지원). 원천 호출 횟수는
    # 그대로다 — 두 소스 모두 어차피 전량 페이지네이션이고, 늘어난 건 메모리에 남기는 범위뿐이다.
    # v4(2026-07-31): _Entry 에 description(표준데이터 fstvlCo) 보존 추가. 구 캐시에는 그 필드가
    # 없어 그대로 쓰면 6h 동안 description 이 null 로 굳는다 → 키 버전을 올려 재스윕시킨다.
    cache_key = f"festivals:all:v4:{today.isoformat()}"

    cached = await cache.get(cache_key)
    if cached is not None:
        return [_Entry.from_dict(d) for d in cached]

    async with _sweep_lock:
        # 대기 중에 다른 요청이 채웠을 수 있다(이중검사) — 원천 중복 호출 방지.
        cached = await cache.get(cache_key)
        if cached is not None:
            return [_Entry.from_dict(d) for d in cached]

        horizon = (today + timedelta(days=SWEEP_HORIZON_DAYS)).isoformat()
        tour_res, std_res = await asyncio.gather(
            _fetch_tour(today, horizon),
            _fetch_std(today, horizon),
            return_exceptions=True,
        )

        entries: list[_Entry] = []
        failed = 0

        if isinstance(tour_res, list):
            entries.extend(tour_res)
        else:
            failed += 1
            if not isinstance(tour_res, TourApiFestivalError):
                logger.warning("TourAPI 축제 스윕 예외: %r", tour_res)
            else:
                logger.info("TourAPI 축제 스윕 실패(스킵): %s", tour_res)

        if isinstance(std_res, list):
            entries.extend(std_res)
        else:
            failed += 1
            if not isinstance(std_res, StdDataFestivalError):
                logger.warning("표준축제데이터 스윕 예외: %r", std_res)
            else:
                logger.info("표준축제데이터 스윕 실패(스킵): %s", std_res)

        if failed == 2:
            # 전부 실패 → 캐시하지 않는다(다음 요청에서 재시도).
            return []

        # TourAPI 우선(이미지 보유) → 표준데이터 순으로 중복 제거.
        entries.sort(key=lambda e: (0 if e.source == "tourapi" else 1,
                                    e.festival.start_date, e.festival.title))
        entries = _dedupe(entries)
        entries = _reassign_id_collisions(entries)

        ttl = PARTIAL_TTL_SEC if failed else CACHE_TTL_SEC
        await cache.set(cache_key, [e.to_dict() for e in entries], ttl)
        logger.info(
            "축제 전국 병합 %d건 캐시(ttl=%ds, 실패소스=%d, 지역매칭=%d)",
            len(entries), ttl, failed, sum(1 for e in entries if e.region_code),
        )
        return entries


def _reassign_id_collisions(entries: list["_Entry"]) -> list["_Entry"]:
    """QA Major-1(2026-07-31): 합성 id(CRC32 % 90M) 충돌 해소 — 결정적 선형 프로빙.

    충돌을 방치하면 find_entry(첫 매치)가 카드 A 클릭에 축제 B 상세를 돌려준다(실측 충돌
    확률 N=4000 기준 약 5%). 정렬된 entries 순서대로 훑으며 이미 쓰인 id 를 만나면
    +1 씩 밀어(900M~990M 구간 wrap) 첫 빈 자리에 재할당한다 — 같은 입력이면 항상 같은
    결과라(정렬이 결정적) 캐시 TTL 안에서 상세 링크가 흔들리지 않는다.
    TourAPI 실 contentid(<900M)는 원천 고유값이므로 건드리지 않는다(충돌 시 표준데이터
    쪽만 밀린다 — 어차피 합성 id 라 의미가 없다).
    """
    seen: set[int] = set()
    out: list[_Entry] = []
    for e in entries:
        fid = e.festival.id
        if fid in seen and is_synthetic_id(fid):
            new_id = fid
            while new_id in seen:
                new_id += 1
                if new_id >= _SYNTH_ID_BASE + _SYNTH_ID_SPAN:
                    new_id = _SYNTH_ID_BASE
            logger.warning("합성 축제 id 충돌 재할당: %d → %d (%s)", fid, new_id, e.festival.title[:30])
            e = _Entry(e.festival.model_copy(update={"id": new_id}),
                       e.region_code, e.source, e.description)
            fid = new_id
        seen.add(fid)
        out.append(e)
    return out


def is_synthetic_id(festival_id: int) -> bool:
    """표준데이터 출신(원천 이미지 없음) 축제 id 인가. TourAPI contentid 와 구간이 겹치지 않는다."""
    return festival_id >= _SYNTH_ID_BASE


async def find_entry(festival_id: int, cache: Cache) -> _Entry | None:
    """축제 1건을 **전국 스윕 캐시에서만** 찾는다(원천 재호출 금지 — 부록 P.2).

    없으면 None → API 레이어가 404 FESTIVAL_NOT_FOUND. 캐시가 비어 있으면(원천 2소스 모두 실패)
    같은 스윕 경로를 타므로 목록과 동일한 데이터에서 조회된다(목록에 보이는 id 는 반드시 찾힌다).
    """
    entries = await _load_nationwide(cache)
    return next((e for e in entries if e.festival.id == festival_id), None)


async def build_festivals_response(
    region_code: str | None,
    limit: int,
    cache: Cache,
    today: date | None = None,
    month: str | None = None,
    window_days: int | None = None,
    area_cd: str | None = None,
) -> FestivalsResponse:
    """region_code 지역의 진행중/예정 축제를 조립. 원천 실패/데이터없음이면 festivals=[] + region.

    region_code 를 생략하면 전국 목록을 준다(지역 매칭 실패분도 여기서만 노출).
    `area_cd`(부록 Y, 2026-08-11)는 그 **중간 단계**다 — 시도 전체 축제. region_code 가 함께
    오면 무시된다(더 좁은 지정이 이긴다) → 기존 호출부 동작 불변. 원천 호출은 늘지 않는다
    (전국 스윕 캐시에 대한 메모리 필터일 뿐이다 — region_code 필터와 같은 자리).
    today 는 테스트/`as_of` 주입용(기본 실제 오늘) — 캐시된 전국 목록에 대한 메모리 필터로만 쓴다.

    기간 필터(둘 중 하나만 적용된다):
      - `month='YYYY-MM'` 지정 시: 그 달에 **기간이 걸치는** 축제(start <= 월말 AND end >= 월초).
        month 가 오면 window_days 는 무시된다(월 선택이 더 명시적인 의도이므로).
        형식 위반은 API 레이어가 400 으로 막는다(여기선 ValueError 전파).
      - 미지정 시: 기존 규칙 그대로 `start_date <= as_of + window_days`(기본 90일, 최대 365일).
    두 경우 모두 **이미 끝난 축제(`end_date < as_of`)는 제외**한다 — 불변.

    스윕 캐시가 보유하는 미래 범위는 as_of + 365일까지다. 그보다 먼 month 를 요청하면
    결과가 비거나 부분적일 수 있다(원천을 추가로 부르지 않는다 = 쿼터 방어).
    """
    as_of = today or date.today()
    limit = _clamp_limit(limit)
    window = _clamp_window(window_days)
    bounds = month_bounds(month) if month else None
    rc = (region_code or "").strip()
    ac = (area_cd or "").strip()

    region: RecommendRegion | None = None
    if rc:
        region = RecommendRegion(region_code=rc, region_name=_region_name(rc))

    entries = await _load_nationwide(cache)
    if rc:
        entries = [e for e in entries if e.region_code == rc]
    elif ac:
        # 시도 필터 = 법정동 5자리의 앞 2자리. 우리 사전(REGIONS)에 없는 시군구의 축제도
        # 살리려면 코드 앞자리로 보는 게 맞다(사전은 "스팟이 수집된 지역"이라 더 좁다).
        entries = [
            e for e in entries
            if e.region_code and len(e.region_code) == 5 and e.region_code[:2] == ac
        ]

    as_of_s = as_of.isoformat()
    horizon = (as_of + timedelta(days=window)).isoformat()

    selected: list[Festival] = []
    for e in entries:
        f = e.festival
        if f.end_date < as_of_s:
            continue
        if bounds is not None:
            if f.start_date > bounds[1] or f.end_date < bounds[0]:
                continue
        elif f.start_date > horizon:
            continue
        ongoing = f.start_date <= as_of_s <= f.end_date
        # 캐시에는 스윕 시점(=실제 오늘) 기준 ongoing 이 들어 있다. as_of 기준으로 다시 계산.
        selected.append(f if f.ongoing == ongoing else f.model_copy(update={"ongoing": ongoing}))

    selected.sort(key=_sort_key)
    # total = 필터를 통과한 전체 수(limit 절삭 전). 프론트 "전체 N건" 표기용.
    return FestivalsResponse(region=region, festivals=selected[:limit], total=len(selected))
