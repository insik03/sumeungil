"""이미지 URL 정규화 + 출처 표기(photo_credit) 조립 — 단일 소스.

여기 두는 이유: 같은 규칙을 **배치(collector)와 런타임(service) 양쪽**이 쓴다.
service 를 배치가 import 하는 건 계층 역전이라, 순수 함수만 util 로 내린다.
`spot_detail_service._normalize_image_url` 은 이 함수를 그대로 가리킨다(정의는 한 곳).

원천 실호출로 확인한 사실(2026-07-29):
  - areaBasedList2 / detailCommon2 / detailImage2 / gallerySearchList1 의 이미지 URL 은 전부
    `tong.visitkorea.or.kr` CDN 이며 http 로 온다. 이 CDN 은 https 도 200 을 주므로 프론트
    mixed-content 방지를 위해 https 로 승격해 내려준다.
  - areaBasedList2 / detailCommon2 / detailImage2 응답에는 `cpyrhtDivCd` 저작권 구분 코드가
    함께 온다(관측값: "Type1", "Type3", 이미지 없는 건은 ""). **코드의 법적 의미(공공누리 몇
    유형인지)는 API 응답만으로 확정할 수 없으므로 이 모듈은 해석하지 않는다** — 원본 코드를
    그대로 보존해 두고(시드/캐시), 화면 표기는 아래의 보수적 출처 문구로 통일한다.
  - PhotoGalleryService1 응답에는 저작권 유형 필드가 아예 없고 촬영자(galPhotographer)만 있다.
    → 촬영자를 표기에 포함한다(저작권 표기는 라이선스 판정과 무관하게 기본 준수).
"""

from __future__ import annotations

_IMG_HOST_HTTP = "http://tong.visitkorea.or.kr"
_IMG_HOST_HTTPS = "https://tong.visitkorea.or.kr"

# 화면에 노출할 출처 문구(고정 문자열 — 외부 입력을 그대로 쓰지 않는다).
CREDIT_KTO = "한국관광공사"
CREDIT_GALLERY = "한국관광공사 포토갤러리"

# 촬영자명(외부 문자열)을 표기에 넣을 때의 방어적 상한/필터.
_PHOTOGRAPHER_MAX = 40


def normalize_image_url(raw) -> str | None:
    """이미지 URL 문자열 → 정규화된 https URL. 빈값/비문자열이면 None(지어내지 않음)."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url:
        return None
    if url.startswith(_IMG_HOST_HTTP):
        url = _IMG_HOST_HTTPS + url[len(_IMG_HOST_HTTP):]
    return url


def kto_credit() -> str:
    """TourAPI(관광공사) 제공 이미지의 출처 표기. cpyrhtDivCd 는 해석하지 않는다."""
    return CREDIT_KTO


def gallery_credit(photographer) -> str:
    """포토갤러리 이미지 출처 표기. 촬영자가 있으면 함께 표기한다.

    촬영자명은 원천 외부 문자열이므로 개행/제어문자를 제거하고 길이를 제한한다
    (표시 문자열이라 태그를 만들지는 않지만, 표면을 좁혀 둔다).
    """
    name = photographer if isinstance(photographer, str) else ""
    name = " ".join(name.split())[:_PHOTOGRAPHER_MAX].strip()
    if not name:
        return CREDIT_GALLERY
    return f"{CREDIT_GALLERY} / 촬영: {name}"
