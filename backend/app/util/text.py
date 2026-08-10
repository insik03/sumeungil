"""외부 텍스트(TourAPI overview·표준데이터 축제내용) 표시용 정제 — 단일 소스.

여기 두는 이유: 같은 규칙을 코스 blurb(course_enrich_service)·축제 상세 description
(festival_detail_service)이 함께 쓴다. 순수 함수만 두고 상위 정책(길이 상한·유니코드
정규화 여부)은 호출부가 정한다.

원천 실측: TourAPI `overview` 에는 `<br>`·`<b>`·`&lt;b&gt;` 같은 HTML 조각이 섞여 온다.
표시 문자열이므로 태그를 지우고 평문으로 만든다(원문 자체는 `/places/{id}.overview` 에
그대로 남는다 — 무회귀).
"""

from __future__ import annotations

import html
import re

# 순서 주의: **엔티티 복원(&lt;b&gt; → <b>)을 먼저** 하고 태그를 제거한다. 반대로 하면
# 인코딩된 태그가 결과물 안에 <script> 같은 평문으로 되살아난다(프론트가 텍스트 노드로
# 렌더하더라도 불필요한 표면을 남기지 않는다).
_TAG_RE = re.compile(r"<[^>]{0,200}>")
_WS_RE = re.compile(r"\s+")

# 한국어 종결(다./요./까?/!)과 영문 마침표 기준 문장 분리. 숫자 소수점(1.5)은 뒤에 공백이
# 없어 분리되지 않는다(뒤에 공백 또는 문자열 끝을 요구).
SENTENCE_END_RE = re.compile(r"(?<=[.!?。])\s+")


def strip_html_to_plain(text: str | None) -> str:
    """HTML 엔티티 복원 → 태그 제거 → 공백 정규화. 입력이 없으면 빈 문자열."""
    if not text or not isinstance(text, str):
        return ""
    out = html.unescape(text)
    out = _TAG_RE.sub(" ", out)
    return _WS_RE.sub(" ", out).strip()


def truncate_text(text: str, max_chars: int) -> str:
    """max_chars 이내로 절단. 가능하면 **문장 경계**에서 끊고, 아니면 하드 절단 + '…'.

    - 문장 경계 절단은 상한의 60% 이상을 남길 때만 채택한다(너무 짧아지는 것 방지).
    - 원문이 상한 이내면 그대로 반환(가공 0).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[:max_chars]
    cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"), head.rfind("。"))
    if cut >= int(max_chars * 0.6):
        return head[: cut + 1].rstrip()
    return head.rstrip() + "…"
