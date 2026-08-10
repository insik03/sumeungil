"""스팟 사진 폴백 체인 (부록 H.3) — 대표이미지가 없는 스팟의 사진을 **정직하게만** 채운다.

전체 체인(호출부: spot_detail_service.get_photo):
    ① 시드 image_url (areaBasedList2 firstimage 를 배치가 적재 — 원천 콜 0)
    ② detailCommon2 firstimage (시드에 판정값이 없는 스팟만. 기존 24h 캐시 그대로)
    ③ detailImage2 첫 장    ← 이 모듈
    ④ 포토갤러리 제목 엄격매칭 ← 이 모듈
    ⑤ null (= 프론트 플레이스홀더)

**이 모듈의 존재 이유는 "채우는 것"이 아니라 "아무거나 채우지 않는 것"이다.**
포토갤러리 검색(gallerySearchList1)은 galTitle 뿐 아니라 galSearchKeyword 까지 훑기 때문에
"금수복국 해운대본점"으로 검색하면 해운대 지역의 풍경 사진이 딸려 온다. 그걸 그 식당 사진인 척
내보내면 사용자에게 거짓말을 하는 것이다. 그래서 아래 **3단 게이트를 전부 통과한 사진만** 채택하고,
하나라도 못 넘기면 사진 없음(null)으로 남긴다.

────────────────────────────────────────────────────────────────────────
갤러리 채택 규칙 (엄격 매칭)  — 세 게이트를 **모두** 통과해야 채택
────────────────────────────────────────────────────────────────────────
정규화 norm(s): 공백·중점·하이픈·언더바·쉼표·괄호류 제거 + 소문자.
비교 대상 q = norm(스팟명에서 괄호 내용을 제거한 문자열), t = norm(galTitle).

G1. 지역 게이트 (필수)
    스팟 주소에서 (시도, 시군구)를 뽑고, galPhotographyLocation 이
      - 시군구명을 포함하고
      - 시도명 앞 2글자를 포함
    할 때만 통과. 주소로 시군구를 못 뽑으면 **갤러리 채택 자체를 하지 않는다**.
    → 전국에 흔한 동명 지명(중앙시장·향교·수변공원…)이 다른 도시 사진으로 채워지는 걸 막는다.

G2. 제목 게이트 (필수) — 둘 중 하나
    (a) 완전일치       : t == q
    (b) 스팟명 접두확장 : q ⊂ t  AND  len(q) >= 4  AND  len(t) - len(q) <= 6
        (예: 스팟 "감천문화마을" ↔ 갤러리 "감천문화마을 전경")
    **반대 방향(t ⊂ q)은 무조건 거절한다.** 이게 오정보의 주 통로다:
      갤러리 "해운대" ⊂ 스팟 "금수복국해운대본점" → 거절. 갤러리 "청사포" ⊂ 스팟
      "청사포다릿돌전망대" → 거절(마을 사진을 전망대 사진으로 쓰지 않는다).
    q 가 4글자 미만이면 (b)를 쓰지 않는다(짧은 이름이 아무 데나 걸리는 걸 막음).

G3. 사진 URL 게이트
    galWebImageUrl 이 실제로 있어야 한다(빈 문자열이면 스킵).

동점 처리: 완전일치 우선 → galTitle 짧은 순 → galContentId 오름차순 (같은 입력 = 같은 결과).

라이선스/출처: 갤러리 응답에는 저작권 유형 필드가 없고 촬영자(galPhotographer)만 있다.
채택 시 `photo_credit = "한국관광공사 포토갤러리 / 촬영: {촬영자}"` 를 응답에 additive 로 담아
프론트가 사진 옆에 표기할 수 있게 한다(법률 검토 결과와 무관하게 출처 표기는 기본 준수).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from ..cache.base import Cache
from ..clients import tourapi_detail_client, tourapi_gallery_client
from ..config import settings
from ..util.images import gallery_credit, kto_credit, normalize_image_url

logger = logging.getLogger("sumeungil.services.photo")

# 폴백 결과 캐시(24h). **찾지 못한 결과(null)도 캐시**해 매 요청마다 원천을 재조회하지 않는다.
# 원천 호출이 실패(429/타임아웃)한 경우는 캐시하지 않아 다음에 재시도한다.
PHOTO_FALLBACK_TTL_SEC = 24 * 60 * 60

# 사진 없는 스팟이 한 화면에 수십 개 뜰 수 있다. 폴백은 스팟당 원천 콜 1~2회라
# gather 로 한꺼번에 터뜨리면 오퍼레이션 일일 한도를 순식간에 태운다(2026-07-29 실제 사고).
# 동시 실행을 좁혀 버스트를 막는다.
_FALLBACK_SEMAPHORE = asyncio.Semaphore(4)

# 갤러리 제목 게이트 상수(위 규칙 G2)
MIN_PREFIX_LEN = 4      # 접두확장 매칭에 요구하는 최소 스팟명 길이
MAX_TITLE_EXTRA = 6     # 갤러리 제목이 스팟명보다 길어도 되는 최대 글자 수

_PAREN_RE = re.compile(r"\([^)]{0,60}\)")
_NORM_STRIP_RE = re.compile(r"[\s·・\-_,\.'\"“”‘’()\[\]{}]")
_SIGUNGU_SUFFIX = ("시", "군", "구")


@dataclass(frozen=True)
class Photo:
    """스팟 1곳의 사진 결정 결과. url 이 None 이면 '무료 공공 데이터에 사진 없음'."""

    url: str | None
    credit: str | None = None
    source: str | None = None  # "seed" | "firstimage" | "detail_image" | "gallery" | None


NO_PHOTO = Photo(url=None, credit=None, source=None)


# ---------- 정규화 / 지역 추출 ----------

def norm_title(s: str | None) -> str:
    """제목 비교용 정규화: 괄호 내용 제거 → 구분문자 제거 → 소문자."""
    if not isinstance(s, str):
        return ""
    return _NORM_STRIP_RE.sub("", _PAREN_RE.sub("", s)).lower().strip()


def sido_sigungu(address: str | None) -> tuple[str | None, str | None]:
    """주소 문자열 → (시도명, 시군구명). 형식이 다르면 (None, None) — 지어내지 않는다."""
    parts = str(address or "").split()
    if len(parts) < 2:
        return None, None
    sido, sigungu = parts[0], parts[1]
    if not sigungu.endswith(_SIGUNGU_SUFFIX):
        return sido, None
    return sido, sigungu


def region_gate(gal_location: str | None, sido: str | None, sigungu: str | None) -> bool:
    """G1. 촬영지가 그 스팟의 시도·시군구와 맞는지. 판정 불가면 False(보수적 거절)."""
    if not sido or not sigungu:
        return False
    loc = norm_title(gal_location)
    if not loc:
        return False
    return norm_title(sigungu) in loc and norm_title(sido)[:2] in loc


def title_gate(spot_norm: str, gal_norm: str) -> bool:
    """G2. 갤러리 제목이 이 스팟을 가리키는가. 역포함(t ⊂ q)은 무조건 False."""
    if not spot_norm or not gal_norm:
        return False
    if spot_norm == gal_norm:
        return True
    if len(spot_norm) < MIN_PREFIX_LEN:
        return False
    if spot_norm in gal_norm and len(gal_norm) - len(spot_norm) <= MAX_TITLE_EXTRA:
        return True
    return False


def pick_gallery_item(items: list[dict], name: str, address: str | None) -> dict | None:
    """G1~G3 을 모두 통과한 갤러리 item 중 결정적으로 1건 선택. 없으면 None."""
    q = norm_title(name)
    if not q:
        return None
    sido, sigungu = sido_sigungu(address)
    if not sigungu:
        return None  # 지역 확인 불가 → 채택하지 않는다(오정보 방지가 커버리지보다 우선)

    accepted: list[tuple[int, int, int, dict]] = []
    for it in items:
        url = normalize_image_url(it.get("galWebImageUrl"))
        if not url:
            continue  # G3
        if not region_gate(it.get("galPhotographyLocation"), sido, sigungu):
            continue  # G1
        t = norm_title(it.get("galTitle"))
        if not title_gate(q, t):
            continue  # G2
        try:
            gid = int(str(it.get("galContentId", "0")).strip() or 0)
        except ValueError:
            gid = 0
        accepted.append((0 if t == q else 1, len(t), gid, it))

    if not accepted:
        return None
    accepted.sort(key=lambda x: (x[0], x[1], x[2]))
    return accepted[0][3]


# ---------- 폴백 체인 ----------

async def _from_detail_image(content_id: int) -> Photo | None:
    """③ detailImage2 첫 장. 사진 없으면 None, 원천 실패는 예외로 올려 캐시를 막는다."""
    items = await tourapi_detail_client.fetch_detail_images(content_id, num_of_rows=5)
    for it in items:
        url = normalize_image_url(it.get("originimgurl")) or normalize_image_url(
            it.get("smallimageurl")
        )
        if url:
            return Photo(url=url, credit=kto_credit(), source="detail_image")
    return None


async def _from_gallery(name: str, address: str | None) -> Photo | None:
    """④ 포토갤러리 엄격매칭. 통과 못하면 None(억지로 채우지 않는다)."""
    keyword = _PAREN_RE.sub("", name or "").strip()
    if not keyword:
        return None
    items = await tourapi_gallery_client.search_gallery(keyword, num_of_rows=20)
    if not items:
        return None
    hit = pick_gallery_item(items, name, address)
    if hit is None:
        logger.info(
            "갤러리 후보 %d건 전부 규칙 미달 → 사진 없음 유지 (spot=%r)", len(items), name
        )
        return None
    logger.info("갤러리 채택: spot=%r ← galTitle=%r", name, hit.get("galTitle"))
    return Photo(
        url=normalize_image_url(hit.get("galWebImageUrl")),
        credit=gallery_credit(hit.get("galPhotographer")),
        source="gallery",
    )


# ---------- 상세 슬라이드용 추가 사진 목록 (부록 P.1, 2026-07-31) ----------

# detailImage2 결과는 사실상 불변이라 **7일** 캐시한다. detailCommon2 가 429 로 통째로 소진된
# 2026-07-29 사고의 교훈: 상세용 오퍼레이션은 "캐시로 콜을 죽이고, 상세 진입 시에만 부른다".
# (목록/홈에서 선호출하지 않는다 — 호출부는 spot detail / festival detail 두 곳뿐.)
DETAIL_IMAGES_TTL_SEC = 7 * 24 * 60 * 60
# 원천 실패(429/타임아웃)를 7일간 "사진 없음"으로 굳히지 않되 폭주도 막는 짧은 음성 캐시.
DETAIL_IMAGES_FAIL_TTL_SEC = 10 * 60
DETAIL_IMAGES_MAX = 8


async def detail_image_urls(
    content_id: int, cache: Cache, limit: int = DETAIL_IMAGES_MAX
) -> list[str]:
    """detailImage2 추가 사진 URL 목록(https 승격·중복 제거·최대 limit). 실패/없음 → [].

    - 어떤 예외도 밖으로 던지지 않는다(사진 때문에 상세 화면이 깨지지 않게).
    - 429 등 원천 실패는 [] 를 주고 **10분만** 캐시 → 호출부는 대표사진 1장으로 graceful.
    - PHOTO_FALLBACK_ENABLED=false 면 원천 콜 0(빈 리스트). 계약은 동일, 사진이 줄 뿐이다.
    """
    if not settings.photo_fallback_enabled:
        return []

    key = f"spot_images:{content_id}"
    cached = await cache.get(key)
    if cached is not None:
        return list(cached.get("urls") or [])[:limit]

    async with _FALLBACK_SEMAPHORE:
        cached = await cache.get(key)  # 대기 중 다른 태스크가 채웠을 수 있다(중복 콜 방지)
        if cached is not None:
            return list(cached.get("urls") or [])[:limit]

        try:
            items = await tourapi_detail_client.fetch_detail_images(
                content_id, num_of_rows=DETAIL_IMAGES_MAX
            )
        except Exception as exc:  # noqa: BLE001 — 429/타임아웃 포함
            logger.info("detailImage2 목록 스킵(content_id=%s): %s", content_id, exc)
            await cache.set(key, {"urls": []}, DETAIL_IMAGES_FAIL_TTL_SEC)
            return []

        urls: list[str] = []
        for it in items:
            url = normalize_image_url(it.get("originimgurl")) or normalize_image_url(
                it.get("smallimageurl")
            )
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= DETAIL_IMAGES_MAX:
                break

        await cache.set(key, {"urls": urls}, DETAIL_IMAGES_TTL_SEC)
        return urls[:limit]


def build_image_list(
    primary_url: str | None, primary_credit: str | None, extra_urls: list[str], max_items: int
) -> list[tuple[str, str | None]]:
    """(대표사진 + 추가사진) → (url, credit) 목록. 중복 URL 제거, 최대 max_items.

    대표사진이 항상 첫 번째다(없으면 추가사진만). 추가사진 credit 은 TourAPI 고정 문구.
    반환은 스키마 비의존 튜플 — SpotDetail/축제 상세 양쪽이 각자 모델로 감싼다.
    """
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    if primary_url:
        out.append((primary_url, primary_credit))
        seen.add(primary_url)
    for url in extra_urls:
        if len(out) >= max_items:
            break
        if url in seen:
            continue
        seen.add(url)
        out.append((url, kto_credit()))
    return out[:max_items]


async def fallback_photo(
    content_id: int, name: str | None, address: str | None, cache: Cache
) -> Photo:
    """대표이미지가 없는 스팟의 ③④ 폴백. 못 찾으면 NO_PHOTO(정직한 null).

    - 24h 캐시(못 찾음도 캐시). 원천 호출 실패는 캐시하지 않아 다음에 재시도.
    - 어떤 예외도 밖으로 던지지 않는다(사진 하나 때문에 화면이 깨지지 않게).
    """
    if not settings.photo_fallback_enabled:
        return NO_PHOTO

    key = f"spot_photo_fb:{content_id}"
    cached = await cache.get(key)
    if cached is not None:
        return Photo(
            url=cached.get("url"), credit=cached.get("credit"), source=cached.get("source")
        )

    async with _FALLBACK_SEMAPHORE:
        # 세마포어 대기 중 다른 태스크가 채웠을 수 있다 → 재확인(중복 원천 콜 방지)
        cached = await cache.get(key)
        if cached is not None:
            return Photo(
                url=cached.get("url"), credit=cached.get("credit"), source=cached.get("source")
            )

        upstream_failed = False
        found: Photo | None = None
        try:
            found = await _from_detail_image(content_id)
        except Exception as exc:  # noqa: BLE001 — 사진 1장 때문에 화면이 깨지지 않게
            upstream_failed = True
            logger.info("detailImage2 폴백 스킵(content_id=%s): %s", content_id, exc)

        if found is None and name:
            try:
                found = await _from_gallery(name, address)
            except Exception as exc:  # noqa: BLE001
                upstream_failed = True
                logger.info("갤러리 폴백 스킵(content_id=%s): %s", content_id, exc)

        result = found or NO_PHOTO
        # 원천이 실패했는데 '사진 없음'으로 확정해 24h 굳히면 오판이다 → 실패 시 캐시하지 않는다.
        if found is not None or not upstream_failed:
            await cache.set(
                key,
                {"url": result.url, "credit": result.credit, "source": result.source},
                PHOTO_FALLBACK_TTL_SEC,
            )
        return result
