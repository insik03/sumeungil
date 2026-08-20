"""레이트 리미팅 — 순수 인메모리 슬라이딩 윈도우 (외부 의존성 0).

## 왜 필요한가
공개 배포(Oracle VM, 80 포트 오픈) 시 `/onboarding/analyze`·`/tips/personalized` 는 요청 1건이
로컬 Ollama LLM 추론 수 초~수십 초를 태운다. 무제한이면 익명 1명이 CPU 를 통째로 점유해
서비스 전체가 멈춘다(가용성 DoS). 인증이 없는 서비스라 IP 기준 제한이 유일한 1차 방어선이다.

## 설계 원칙
- **외부 의존성 추가 금지**: Redis/slowapi 없이 표준 라이브러리만 쓴다(requirements.txt 불변).
- **무회귀 최우선**: `RATE_LIMIT_ENABLED=false`(기본값) 면 미들웨어가 즉시 통과시킨다.
  로컬 개발 동작은 이 파일 도입 전과 100% 동일하다. 배포 `.env` 에서만 true 로 켠다.
- **에러 봉투 동일**: 429 응답도 기존 `{"error":{"code","message","detail"}}` 형식을 그대로 쓴다
  (01-interface-contract.md §3). 프론트가 새 파서를 만들 필요가 없다.

## 동시성 메모
카운터 갱신 구간에는 `await` 가 하나도 없다 — asyncio 단일 이벤트루프에서 동기 코드 블록은
원자적으로 실행되므로 Lock 이 필요 없다(MemoryCache 와 달리 I/O 를 끼지 않는다).
대신 **프로세스별로 카운터가 분리**되므로 uvicorn 워커는 반드시 1개여야 한다
(멀티워커면 실효 한도가 워커 수만큼 곱해진다 — deploy/docker-compose.yml 주석 참고).

## 신뢰 경계 (중요)
`X-Forwarded-For` 는 클라이언트가 위조할 수 있다. nginx 뒤에 있을 때만 신뢰해야 하므로
`RATE_LIMIT_TRUST_PROXY` 로 분리했다. 배포 시 backend 컨테이너 포트를 호스트에 공개하지 않아
(compose 에서 ports 미기재) nginx 를 우회한 직접 접근 자체가 불가능하다.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any, Deque, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("sumeungil.middleware.rate_limit")

# --- 버킷 분류 규칙 (경로는 라우터 prefix 와 1:1) ---------------------------------
# LLM 추론이 요청당 1~2회 도는 경로 = 가장 비싼 경로.
LLM_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/onboarding/analyze",
        "/api/v1/tips/personalized",  # 부록 Z(2026-08-20): 컨시어지가 비운 자리를 팁이 쓴다
    }
)
# 코스 생성/정렬 — Tmap 외부 호출 + 요약 LLM 이 붙는다(캐시 히트면 저렴하지만 미스가 비싸다).
COURSE_PREFIX = "/api/v1/courses"
# 부록 R(2026-08-01): 사용자 생성 콘텐츠(UGC) 쓰기 — 디스크에 영구 기록이 남는 유일한 경로다.
# 서비스 레이어에 device_id 기준 한도가 이미 있지만, device_id 는 클라이언트가 만드는 값이라
# **무한히 갈아끼울 수 있다.** IP 기준의 이 버킷이 그 우회를 막는 바깥 방어선이다.
UGC_PREFIX = "/api/v1/reviews"
UGC_SHARE_PATH = "/api/v1/courses/share"
UGC_SHARED_PREFIX = "/api/v1/courses/shared"  # DELETE /shared/{code}
# 2026-08-18(보안 L-4) — 계정 보관함 쓰기도 디스크에 영구 기록을 남기는 UGC 다.
# 분류가 빠져 있어 POST /mine 이 course 버킷(비싼 조립용 한도)으로 새고 있었다.
# 로그인 필수라 device_id 우회는 없지만, 한 계정이 코스를 도배하는 것은 IP 버킷이 막는다.
UGC_MINE_PATH = "/api/v1/courses/mine"  # POST /mine · DELETE /mine/{id}
# 2026-08-18(qa-reviewer M-5) — 고객문의도 디스크에 영구 기록을 남기는 사용자 쓰기라
# UGC와 같은 성격인데 분류가 빠져 있어 기본(120/분)으로 새고 있었다. 로그인 필수라
# device_id 우회는 없지만, 같은 계정이 문의를 도배하는 것까지 막으려면 review/share와
# 동일하게 IP 기준 UGC 버킷으로 묶는 게 맞다.
UGC_INQUIRY_PATH = "/api/v1/inquiries"
UGC_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "DELETE"})
# 부록 T(2026-08-01): 관리자 로그인 — 비밀번호 추측 시도를 묶는다. **로그인 경로만** 이 버킷이다.
# 관리자 목록 조회까지 5/분으로 묶으면 정상 운영이 불가능하므로 나머지는 default 로 둔다.
# 이 미들웨어는 RATE_LIMIT_ENABLED=false 면 등록조차 되지 않으므로, 로그인 방어의 본체는
# 라우터의 `deps.get_admin_login_limiter`(항상 동작)다. 여기는 배포 환경의 두 번째 겹이다.
ADMIN_LOGIN_PATH = "/api/v1/admin/login"
# 헬스체크는 컨테이너 HEALTHCHECK·모니터링이 주기적으로 두드리므로 제한하지 않는다.
EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/api/v1/health"})

BUCKET_LLM = "llm"
BUCKET_COURSE = "course"
BUCKET_UGC = "ugc"
BUCKET_ADMIN = "admin"
BUCKET_DEFAULT = "default"


def resolve_bucket(method: str, path: str) -> str | None:
    """(method, path) → 버킷 이름. None 이면 제한 없음(면제).

    분류에 없는 모든 요청은 `default` 로 떨어진다 — "빠뜨린 엔드포인트가 무제한"이 되지 않게
    화이트리스트가 아니라 폴백 방식으로 설계했다.

    판정 순서 주의: UGC 판정이 코스 판정보다 **먼저**여야 한다. `POST /api/v1/courses/share`
    는 두 규칙에 모두 걸리는데, 이건 Tmap/LLM 을 태우는 코스 조립이 아니라 디스크에 기록을
    남기는 쓰기라서 UGC 한도를 적용해야 한다.
    """
    normalized = path.rstrip("/") or "/"
    if normalized in EXEMPT_PATHS:
        return None
    upper = method.upper()
    # 관리자 로그인 판정이 가장 먼저다 — POST 이고 /api/v1/admin/ 아래라 다른 규칙과 겹치지
    # 않지만, 나중에 규칙이 늘어나도 이 경로의 한도가 느슨해지지 않도록 맨 위에 둔다.
    if upper == "POST" and normalized == ADMIN_LOGIN_PATH:
        return BUCKET_ADMIN
    if upper in UGC_METHODS and (
        normalized == UGC_PREFIX
        or normalized.startswith(UGC_PREFIX + "/")
        or normalized == UGC_SHARE_PATH
        or normalized.startswith(UGC_SHARED_PREFIX + "/")
        or normalized == UGC_MINE_PATH
        or normalized.startswith(UGC_MINE_PATH + "/")
        or normalized == UGC_INQUIRY_PATH
    ):
        return BUCKET_UGC
    if upper == "POST":
        if normalized in LLM_PATHS:
            return BUCKET_LLM
        if normalized == COURSE_PREFIX or normalized.startswith(COURSE_PREFIX + "/"):
            return BUCKET_COURSE
    return BUCKET_DEFAULT


@dataclass(frozen=True)
class Decision:
    allowed: bool
    bucket: str
    limit: int
    remaining: int
    retry_after_sec: int


class SlidingWindowLimiter:
    """(클라이언트키, 버킷) 별 슬라이딩 윈도우 카운터.

    고정 윈도우(매 분 0초 리셋)와 달리 경계에서 한도의 2배가 통과하는 문제가 없다.
    타임스탬프 deque 를 들고 있고 윈도우 밖은 좌측에서 pop 한다 — 한도가 수십~수백이라
    메모리·연산 모두 무시할 수준이다.
    """

    def __init__(
        self,
        limits: dict[str, int],
        window_sec: int = 60,
        max_keys: int = 20_000,
    ) -> None:
        self._limits = dict(limits)
        self._window = max(1, int(window_sec))
        # 위조 XFF 로 키를 무한 생성해 메모리를 터뜨리는 것을 막는 상한.
        self._max_keys = max(100, int(max_keys))
        self._hits: dict[tuple[str, str], Deque[float]] = {}

    @property
    def window_sec(self) -> int:
        return self._window

    def limit_for(self, bucket: str) -> int:
        return self._limits.get(bucket, self._limits.get(BUCKET_DEFAULT, 0))

    def check(self, client_key: str, bucket: str, now: float | None = None) -> Decision:
        """1회 요청을 계산에 반영하고 허용 여부를 돌려준다(허용된 경우에만 카운트 증가)."""
        limit = self.limit_for(bucket)
        ts = monotonic() if now is None else now

        # limit <= 0 은 "이 버킷 제한 없음"으로 해석한다(운영 중 특정 버킷만 끄기).
        if limit <= 0:
            return Decision(True, bucket, limit, -1, 0)

        key = (client_key, bucket)
        window_start = ts - self._window
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            if len(self._hits) >= self._max_keys:
                self._evict(ts)
            self._hits[key] = hits

        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= limit:
            # 가장 오래된 히트가 윈도우를 벗어나는 시각까지 기다려야 한다.
            retry_after = max(1, int(self._window - (ts - hits[0])) + 1)
            return Decision(False, bucket, limit, 0, retry_after)

        hits.append(ts)
        return Decision(True, bucket, limit, limit - len(hits), 0)

    def _evict(self, now: float) -> None:
        """키 상한 초과 시 정리: ① 윈도우가 완전히 빈 키 제거 ② 그래도 넘치면 오래된 순 제거."""
        window_start = now - self._window
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= window_start]
        for k in stale:
            self._hits.pop(k, None)
        if len(self._hits) < self._max_keys:
            return
        # 마지막 히트가 오래된 순으로 10% 를 덜어낸다(전량 정렬은 드물게만 발생).
        victims = sorted(self._hits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0)
        for k, _ in victims[: max(1, self._max_keys // 10)]:
            self._hits.pop(k, None)
        logger.warning("rate_limit 키 상한 도달 — 오래된 카운터를 정리했습니다(max_keys=%d)", self._max_keys)


def extract_client_ip(request: Any, trust_proxy: bool = True) -> str:
    """클라이언트 식별자.

    nginx 리버스 프록시 뒤에서는 `request.client.host` 가 항상 nginx 컨테이너 IP 라 쓸모없다 —
    `X-Forwarded-For` 의 **첫 값**(원 클라이언트)을 쓴다. 프록시 없이 직접 노출된 경우를 대비해
    헤더가 없으면 `request.client.host` 로 폴백한다.

    `request` 는 `.headers`(Mapping)·`.client`(host 속성 보유 or None) 만 요구한다 —
    테스트에서 가짜 객체로 대체할 수 있게 Starlette Request 타입을 강제하지 않는다.
    """
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for") if request.headers else None
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or "unknown"


def scope_path(request: Any) -> str:
    """요청 경로 — **ASGI scope 원본**을 1순위로 쓴다(보안 감사 2026-08-18 A-1).

    `request.url.path` 는 Starlette 가 `Host` 헤더까지 붙여 절대 URL 을 만든 뒤 다시 쪼갠
    값이라, 헤더를 조작할 수 있는 클라이언트가 경로 파싱에 영향을 줄 여지가 있다
    (starlette CVE-2026-48710). scope["path"] 는 서버(uvicorn)가 요청 라인에서 직접 채운
    값이라 헤더의 영향을 받지 않는다.

    scope 가 없는 객체(단위 테스트의 가짜 request)는 기존대로 `.url.path` 로 폴백한다 —
    이 함수 때문에 테스트 더블이 깨지지 않게 하기 위해서다.
    """
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        path = scope.get("path")
        if isinstance(path, str) and path:
            return path
    url = getattr(request, "url", None)
    return getattr(url, "path", "") or "/"


# 내부 별칭(dispatch 가독성용). 공개 이름은 scope_path 하나만 둔다.
_scope_path = scope_path


def rate_limited_response(decision: Decision, window_sec: int = 60) -> JSONResponse:
    """429 — 기존 에러 봉투 형식과 동일(01-interface-contract.md §3 / 부록 O)."""
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
                "detail": {
                    "retry_after_sec": decision.retry_after_sec,
                    "limit": decision.limit,
                    "window_sec": window_sec,
                },
            }
        },
        headers={"Retry-After": str(decision.retry_after_sec)},
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette 미들웨어 어댑터.

    등록 순서 주의: CORSMiddleware 가 **더 바깥**에 있어야 429 응답에도 CORS 헤더가 붙는다.
    Starlette 의 `add_middleware` 는 나중에 추가한 것이 바깥이므로, main.py 에서 이 미들웨어를
    먼저 추가하고 CORS 를 나중에 추가한다.
    """

    def __init__(
        self,
        app: Any,
        *,
        enabled: bool,
        limits: dict[str, int],
        window_sec: int = 60,
        trust_proxy: bool = True,
        max_keys: int = 20_000,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self.limiter = SlidingWindowLimiter(limits, window_sec=window_sec, max_keys=max_keys)
        if enabled:
            logger.info(
                "rate limit 활성화 — llm=%s/%ds, course=%s/%ds, default=%s/%ds (trust_proxy=%s)",
                limits.get(BUCKET_LLM),
                window_sec,
                limits.get(BUCKET_COURSE),
                window_sec,
                limits.get(BUCKET_DEFAULT),
                window_sec,
                trust_proxy,
            )
        else:
            logger.info("rate limit 비활성화(RATE_LIMIT_ENABLED=false) — 모든 요청 통과")

    async def dispatch(self, request: Any, call_next):  # type: ignore[override]
        if not self.enabled:
            return await call_next(request)

        # 버킷 판정은 **ASGI 원본 경로**(scope["path"])로만 한다. `request.url.path` 는 Host
        # 헤더로 절대 URL 을 재구성하는 경로라 클라이언트 헤더의 영향을 받을 수 있고
        # (starlette CVE-2026-48710), 그 틈으로 판정이 흔들리면 LLM/UGC 버킷을 빠져나간다.
        path = _scope_path(request)
        bucket = resolve_bucket(request.method, path)
        if bucket is None:
            return await call_next(request)

        client_key = extract_client_ip(request, trust_proxy=self.trust_proxy)
        decision = self.limiter.check(client_key, bucket)
        if not decision.allowed:
            # 로그에 IP 는 남기되 쿼리스트링·바디는 남기지 않는다(시크릿/개인정보 누출 방지).
            logger.warning(
                "429 RATE_LIMITED bucket=%s path=%s client=%s limit=%d",
                bucket,
                path,
                client_key,
                decision.limit,
            )
            return rate_limited_response(decision, window_sec=self.limiter.window_sec)

        return await call_next(request)


def build_limits_from_settings(settings: Any) -> dict[str, int]:
    """config.Settings → 버킷별 한도 dict (미들웨어와 config 의 결합을 한 곳으로 모은다)."""
    return {
        BUCKET_LLM: settings.rate_limit_llm_per_min,
        BUCKET_COURSE: settings.rate_limit_course_per_min,
        # 부록 R. getattr 폴백은 두지 않는다 — 설정 키를 빠뜨렸으면 부팅 때 바로 알아야 한다.
        BUCKET_UGC: settings.rate_limit_ugc_per_min,
        # 부록 T. 라우터 레벨 로그인 리미터와 같은 값(둘 다 걸려도 체감 차이가 없게).
        BUCKET_ADMIN: settings.admin_login_per_min,
        BUCKET_DEFAULT: settings.rate_limit_default_per_min,
    }


__all__: Iterable[str] = (
    "BUCKET_ADMIN",
    "BUCKET_COURSE",
    "BUCKET_DEFAULT",
    "BUCKET_LLM",
    "BUCKET_UGC",
    "Decision",
    "RateLimitMiddleware",
    "SlidingWindowLimiter",
    "build_limits_from_settings",
    "extract_client_ip",
    "rate_limited_response",
    "resolve_bucket",
    "scope_path",
)
