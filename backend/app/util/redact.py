"""로그로 나가는 외부 응답 본문에서 시크릿을 지운다 (보안 감사 2026-08-18 A-2).

## 왜 필요한가
공공데이터포털·기상청 원천은 오류를 **요청을 그대로 되비추는 XML/HTML** 로 돌려주는 경우가
있다. 그 본문에는 우리가 보낸 `serviceKey` 가 통째로 들어 있다. 파싱 실패 경로에서
`resp.text[:200]` 을 그대로 `logger.warning` 에 넘기면 **API 키가 운영 로그 파일에 평문으로
남는다** — 로그는 백업·전송·열람 경로가 코드보다 훨씬 넓다.

`tourapi_client._redact` 가 이미 같은 일을 하고 있었으나 그 파일 안에만 있었다. 여기로 옮겨
detail/festival/gallery/kma 클라이언트가 **같은 함수 하나**를 쓰게 한다 — 클라이언트가 늘어날
때마다 각자 재구현하면 언젠가 한 곳이 빠진다.

## 원칙
- 지울 대상은 "설정에 실제로 들어 있는 값"뿐이다. 정규식으로 키처럼 생긴 문자열을 추측해
  지우지 않는다(오탐으로 진단에 필요한 본문까지 뭉개면 로그의 가치가 사라진다).
- URL 인코딩된 형태(`%2F`·`%2B` 등)도 같이 지운다 — 원천이 쿼리스트링을 되비출 때는
  인코딩된 상태로 나온다.
"""

from __future__ import annotations

from urllib.parse import quote

# 아주 짧은 값(테스트용 더미 등)까지 치환하면 본문이 마스킹 투성이가 된다. 실제 공공데이터
# 서비스키는 수십 자라 이 하한에 걸리지 않는다.
_MIN_SECRET_LEN = 8
MASK = "***"


def _secret_candidates() -> list[str]:
    """설정에 들어 있는 "로그에 나가면 안 되는 문자열" 목록."""
    from ..config import settings

    raw = [
        getattr(settings, "public_data_api_key", ""),
        getattr(settings, "tmap_app_key", ""),
    ]
    out: list[str] = []
    for value in raw:
        value = (value or "").strip()
        if len(value) < _MIN_SECRET_LEN:
            continue
        out.append(value)
        encoded = quote(value, safe="")
        if encoded != value:
            out.append(encoded)
    # 긴 것부터 지운다 — 짧은 값이 긴 값의 부분문자열이면 순서에 따라 마스킹이 어긋난다.
    return sorted(set(out), key=len, reverse=True)


def redact_secrets(text: str | None) -> str:
    """로그에 남길 문자열에서 설정된 시크릿을 `***` 로 치환한다. None 은 빈 문자열."""
    if not text:
        return ""
    for secret in _secret_candidates():
        if secret in text:
            text = text.replace(secret, MASK)
    return text


__all__ = ("MASK", "redact_secrets")
