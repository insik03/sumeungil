"""사용자 작성 텍스트(닉네임·리뷰·코스 제목) 정제 — 부록 R 전용 단일 소스.

## 기존 util/text.py 와 뭐가 다른가
`util/text.py` 는 **공공데이터 원천 텍스트**(TourAPI overview 등)를 표시용 평문으로 만드는
유틸이다. 이 모듈은 **사용자가 직접 쓴 텍스트**를 다룬다 — 신뢰 수준이 한 단계 더 낮다:
악의적 사용자가 의도적으로 조작한 문자열이 들어온다고 가정한다.

## 파이프라인 (순서가 계약이다)
  1. `injection_guard.sanitize_free_text` — NFKC 정규화 + 유니코드 format(Cf, 제로폭) 제거
     + C0/C1 제어문자 제거 + 반복 padding 축약 + 공백 정규화 + 300자 하드 절단.
  2. `util.text.strip_html_to_plain`      — HTML 엔티티 복원 후 태그 제거(`&lt;b&gt;` → `<b>` → 삭제).
  3. 호출부가 지정한 길이로 절단.
1을 먼저 하는 이유: `<scr\\x00ipt>` 처럼 제어문자를 끼워 태그 정규식을 피하는 수법을 먼저
평탄화해야 2의 태그 제거가 유효하다. 반대 순서면 우회가 생긴다.

## 한계 (정직하게)
서버 정제는 **XSS 방어의 유일한 방어선이 아니다.** 프론트는 이 값들을 반드시 텍스트 노드로만
렌더해야 한다(`dangerouslySetInnerHTML` 금지). 서버 정제는 "저장되는 값을 평문으로 유지"하는
것이 목적이고, 최종 렌더 안전은 프론트가 보증한다(계약 부록 R 에 명시).

## LLM 불변식 (절대 위반 금지)
이 모듈을 거친 텍스트라도 **어떤 LLM 프롬프트에도 넣지 않는다.** 정제는 인젝션 문구를
제거하지 못한다(패러프레이즈는 무한하다). 현재 LLM 에 들어가는 데이터 블록은 공공데이터
문자열뿐이며, 그 불변식을 깨는 순간 사용자 리뷰가 곧 프롬프트 인젝션 통로가 된다.
"""

from __future__ import annotations

import re

from ..ai.injection_guard import sanitize_free_text
from .text import strip_html_to_plain

# 기기 식별자(X-Device-Id) 허용 형식. UUID v4(36자, 하이픈 포함)를 상정하되 다른 랜덤
# 문자열도 받아들일 수 있게 넉넉히 잡았다. 길이·문자셋을 강제하는 이유는 인증이 아니라
# **저장소 오염 방지**다(임의 길이 문자열이 인덱스 키로 들어오지 않게).
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# target_id: 스팟 id(정수 문자열) / 축제 contentid. 그 외 문자는 받지 않는다.
_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def clean_user_text(raw, *, max_chars: int) -> str:
    """사용자 텍스트 → 저장 가능한 한 줄 평문. 결과가 빈 문자열일 수 있다(호출부가 판단).

    **타입을 강제하지 않고 "문자열이 아니면 빈 값"으로 수렴시킨다** (2026-08-18 QA Critical-1).
    호출부 대부분은 pydantic 이 `str` 을 보장하지만, `course_payload` 는 **검증 전의 임의
    JSON**(`{"slot_label": 123}` · `{"blurb": {...}}`)을 다룬다. 그때 여기서 TypeError 가
    나면 쓰기는 500 이 되고, 저장된 값이라면 **읽을 때마다 영구 500** 이 된다 — 정제 함수가
    정제 대상에게 당하는 구조라 방어를 이 한 곳에 둔다(호출부마다 isinstance 를 흩뿌리면
    언젠가 한 곳이 빠진다).
    """
    if not isinstance(raw, str) or not raw:
        return ""
    cleaned = strip_html_to_plain(sanitize_free_text(raw))
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned.strip()


# --- 운영자 사칭 차단 (2026-08-09) --------------------------------------------------
# 발견 경위: 운영 점검 중 `nickname="숨은길 운영팀"` 으로 리뷰가 **실제로 등록됐다**(201).
# clean_user_text 는 XSS·제어문자만 정제하고 "누구인 척하는가"는 보지 않기 때문이다.
# 사칭 후기는 서비스 신뢰를 직접 깎고, 심사 중에 올라오면 그대로 노출된다.
#
# 이 판별은 **일반 사용자 입력에만** 적용한다. 관리자 본인의 표시 이름은 서명된 세션에서
# 나오므로 이 경로를 타지 않는다 — 사용자가 스스로 주장하는 이름만 검사 대상이다.

# 라틴 유사글자 되돌리기. "аdmin"(첫 글자 키릴 а)처럼 눈으로는 같아 보이는 글자로 토큰 검사를
# 피하는 수법을 막는다. NFKC 는 이들을 같은 글자로 보지 않으므로 별도 매핑이 필요하다.
#
# 2026-08-09 보안 점검 지적(M-1): 처음엔 키릴 9자만 넣었는데, 그리스·아르메니아 유사글자가
# 남아 있었다. 더 나쁜 건 아래 _NON_WORD_RE 가 **모르는 글자를 삭제**한다는 점이었다 —
# `admiո`(아르메니아 ո) 이 `admi` 로 줄어들어 오히려 토큰 일치를 피해갔다. 삭제가 우회를
# 도와주는 구조였다. 그래서 유사글자를 "지우기 전에" 라틴으로 되돌린다.
_CONFUSABLES = str.maketrans(
    # 키릴
    "аеорсхіјԁмнѕԛуก"
    # 그리스
    "οαερνττυΐ"
    # 아르메니아
    "ոսցօ",
    "aeopcxijdmhsqyn"
    "oaepvttyi"
    "nugo",
)

# 닉네임에서 공백·기호를 걷어낸 뒤 비교한다("관 리 자", "a-d-m-i-n" 우회 차단).
# 한자(CJK)를 허용 범위에 넣은 이유: `運營팀`·`管理者` 처럼 한자로 쓴 사칭을 잡으려면
# 한자가 살아남아야 한다. 예전엔 삭제돼서 `팀` 만 남아 통과했다.
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣㐀-䶿一-鿿]+")

# 역할을 사칭하는 낱말 — **부분 일치**로 막는다. 이 목록에 있으면 어디에 끼어 있어도 걸린다.
_STAFF_TOKENS: tuple[str, ...] = (
    # 한국어
    "관리자", "관리인", "관리팀", "관리봇", "운영자", "운영팀", "운영진", "운영국", "운영봇",
    "매니저", "모더레이터", "고객센터", "고객센타", "고객지원", "지원팀", "서비스팀",
    "사무국", "시스템", "공지사항",
    # 외래어 음차 — 한국 서비스에서 실제로 이렇게 쓴다
    "어드민", "아드민", "스태프", "오퍼레이터", "헬프데스크", "매니져",
    # 한자
    "管理者", "管理", "運營", "運営", "公式",
    # 영문
    "admin", "administrator", "staff", "manager", "moderator",
    "official", "system", "support", "helpdesk", "operator", "root", "owner",
)

# **완전 일치일 때만** 막는 낱말. 부분 일치로 막으면 정상 닉네임을 대량으로 오차단한다:
#   공식 → "공식적인여행" / 인증 → "인증샷러버" / 공지 → "공지천산책"(춘천 실제 지명)
# 사칭의 핵심은 "내가 그 역할이다"라는 주장이므로, 단독으로 쓰였을 때만 문제가 된다.
#   스탭 → "스탭업"(스텝업). 짧고 다른 외래어와 겹쳐 부분 일치로는 오차단이 난다.
_EXACT_TOKENS: frozenset[str] = frozenset(
    {"공식", "인증", "공지", "운영", "관리", "본사", "스탭"}
)

# 브랜드명 — 단독 사용은 차단.
_BRAND_TOKENS: tuple[str, ...] = ("숨은길", "sumeungil")

# 브랜드 + 역할 결합 — "숨은길공식", "숨은길봇" 처럼 브랜드로 **시작**하고 뒤에 역할어가 붙는 형태.
# 완전 일치만으로는 못 잡고, 브랜드를 부분 일치로 막으면 "숨은길팬" 이 걸린다. 그 사이를 메운다.
_BRAND_SUFFIXES: tuple[str, ...] = (
    "공식", "인증", "본사", "팀", "봇", "계정", "스탭", "스태프", "운영", "관리", "고객", "지원",
)


def _fold_for_compare(value: str) -> str:
    return _NON_WORD_RE.sub("", value.lower().translate(_CONFUSABLES))


def is_impersonating_staff(nickname: str | None) -> bool:
    """닉네임이 운영자/공식 계정을 사칭하는가.

    검사 순서(각 단계가 서로 다른 우회를 막는다):
      1. 소문자화 → 유사글자 되돌리기 → 공백·기호 제거   (`관 리 자`, `аdmin`, `ａｄｍｉｎ`)
      2. 역할어 부분 일치                                  (`숨은길운영팀`, `어드민계정`)
      3. 브랜드 단독 완전 일치                             (`숨은길`)
      4. 브랜드 + 역할어 접두 결합                         (`숨은길공식`, `숨은길봇`)
      5. 모호어 완전 일치                                  (`공식` 은 차단, `공식적인여행` 은 통과)

    한계(정직하게): 자모 분해(`ㄱㅘㄴ리자`)나 유사 발음(`운영티임`)까지는 막지 못한다.
    유사글자도 매핑에 없는 문자가 나오면 뚫린다 — 유니코드 전체를 커버할 수는 없다.
    **손쉬운 사칭을 없애는** 장치이지 완전 차단이 아니며, 남는 것은 관리자 콘솔의
    숨김·삭제로 처리한다는 전제다(그 콘솔은 2026-08-09 부로 존재한다).
    """
    folded = _fold_for_compare(nickname or "")
    if not folded:
        return False
    if any(token in folded for token in _STAFF_TOKENS):
        return True
    if folded in _EXACT_TOKENS:
        return True
    for brand in _BRAND_TOKENS:
        if folded == brand:
            return True
        if folded.startswith(brand):
            rest = folded[len(brand):]
            if rest in _BRAND_SUFFIXES:
                return True
    return False


def is_valid_device_id(value: str | None) -> bool:
    return bool(value and _DEVICE_ID_RE.match(value))


def is_valid_target_id(value: str | None) -> bool:
    return bool(value and _TARGET_ID_RE.match(value))


__all__ = (
    "clean_user_text",
    "is_impersonating_staff",
    "is_valid_device_id",
    "is_valid_target_id",
)
