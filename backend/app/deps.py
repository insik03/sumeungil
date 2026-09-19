"""프로세스 싱글턴 조립 (경량 DI).

MVP-1은 인메모리 캐시 + Live 리포지토리 하나. 상용 전환은 여기서
구현체만 바꾸면 된다 (MemoryCache→RedisCache, Live→Db).
"""

from __future__ import annotations

from functools import lru_cache

from .ai.llm_provider import LLMProvider, create_provider_from_settings
from .ai.summarizer import Summarizer, create_summarizer_from_settings
from .ai.tips_generator import TipsGenerator, create_tips_generator_from_settings
from .cache.base import Cache
from .cache.memory import MemoryCache
from .config import settings
from .db.postgres import Database
from .middleware.rate_limit import SlidingWindowLimiter
from .repositories.congestion_repo import CongestionRepository, LiveCongestionRepository
from .repositories.region_repo import RegionRepository, StaticRegionRepository
from .repositories.spot_repo import JsonSpotRepository, SpotRepository
from .security.admin_auth import AdminAuth
from .security.user_auth import UserAuth
from .services.weather_provider import WeatherProvider, create_weather_provider


@lru_cache(maxsize=1)
def get_cache() -> Cache:
    return MemoryCache()


@lru_cache(maxsize=1)
def get_congestion_repository() -> CongestionRepository:
    return LiveCongestionRepository(
        cache=get_cache(),
        ttl_seconds=settings.cache_ttl_sec,
        forecast_ttl_seconds=settings.forecast_cache_ttl_sec,  # 부록 M: 예보는 6h(config 근거 주석)
    )


@lru_cache(maxsize=1)
def get_region_repository() -> RegionRepository:
    # MVP-2: 정적 seed 기반. 상용 전환 시 여기서 DbRegionRepository 로 교체.
    return StaticRegionRepository()


@lru_cache(maxsize=1)
def get_spot_repository() -> SpotRepository:
    # MVP-4: collector가 만든 spots_seed.json 기반 인메모리 리포지토리(프로세스 시작 시 1회 로드).
    # 상용 전환 시 여기서 DbSpotRepository/PostGIS 로 교체(엔드포인트 계약 불변).
    return JsonSpotRepository()


@lru_cache(maxsize=1)
def get_weather_provider() -> WeatherProvider:
    # MVP-7 파트4: settings.weather_provider 로 선택(기본 kma=D18 실호출, 실패 시 자동 None 폴백).
    # 상용 전환 시 create_weather_provider 에 격자 단기예보 구현체를 추가(계약 불변).
    return create_weather_provider(settings.weather_provider, settings.weather_cache_ttl_sec)


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    # MVP-3 온보딩: 로컬 Ollama 프로바이더 싱글턴(AI llm_provider.py 권장 배선).
    # 상용 전환 시 create_provider_from_settings 내부에서 CloudProvider 로 교체(계약 불변).
    return create_provider_from_settings(settings)


@lru_cache(maxsize=1)
def get_tips_generator() -> TipsGenerator:
    # 부록 Z: 개인화 여행 팁. 온보딩과 **같은 로컬 Ollama 모델**을 재사용한다(새 키·비용 0).
    # 실패·타임아웃은 tips_service 가 정적 폴백으로 흡수하므로 여기서 예외를 다루지 않는다.
    return create_tips_generator_from_settings(settings)


@lru_cache(maxsize=1)
def get_database() -> Database:
    """부록 R + 로그인/개인화 저장소 싱글턴(PostgreSQL 커넥션 풀). 풀은 최초 사용 시 lazy 오픈.

    2026-08-17: 이 함수가 원래 "상용 전환 시 PostgreSQL 구현으로 바꾼다"고 예고했던 지점
    그대로 — db/postgres.py로 교체했다. 라우터·서비스·리포지토리 함수 시그니처는 불변.
    """
    return Database(settings.database_url)


@lru_cache(maxsize=1)
def get_community_write_limiter() -> SlidingWindowLimiter:
    """**device_id 기준** 쓰기 한도. IP 기준 RateLimitMiddleware 와 목적이 다르다.

    - 미들웨어(IP): 서버 자원 보호. 공유기 뒤 여러 사용자가 한 IP 를 쓸 수 있어 넉넉하다.
    - 여기(device_id): 도배 방지. 한 사람이 분당 리뷰 3건 이상 쓸 이유가 없다.
    둘 다 프로세스 인메모리라 워커 1개 전제를 공유한다(Dockerfile 주석 참고).
    """
    return SlidingWindowLimiter(
        {
            "review": settings.review_write_per_min,
            "share": settings.share_write_per_min,
            # 부록 R.14: 좋아요만 키가 device_id 가 아니라 `user:{user_id}` 다(라우터 참고).
            "like": settings.like_write_per_min,
        },
        window_sec=60,
        max_keys=settings.rate_limit_max_keys,
    )


@lru_cache(maxsize=1)
def get_admin_auth() -> AdminAuth:
    """관리자 인증 핸들(부록 T). `.env` 의 ADMIN_PASSWORD_HASH 하나가 유일한 진실이다.

    미설정/형식오류면 `enabled=False` 이고, main.py 는 그 경우 관리자 라우터를 **등록하지
    않는다**(엔드포인트가 존재하지 않는 상태 = 404, OpenAPI 에도 나오지 않음).
    """
    return AdminAuth(
        password_hash=settings.admin_password_hash,
        session_secret=settings.admin_session_secret,
        session_ttl_sec=settings.admin_session_ttl_sec,
        cookie_name=settings.admin_cookie_name,
        cookie_secure=settings.admin_cookie_secure,
    )


@lru_cache(maxsize=1)
def get_user_auth() -> UserAuth:
    """로그인 세션 핸들(구글·카카오 공용, 2026-08-17 대표 지시). 세션 시크릿이 있어야
    `enabled=True`(main.py가 그 경우에만 auth 라우터를 등록) — provider별 client_id/
    secret/redirect_uri는 각각 `google_enabled`/`kakao_enabled`로 따로 확인한다.
    """
    return UserAuth(
        google_client_id=settings.google_client_id,
        google_client_secret=settings.google_client_secret,
        google_redirect_uri=settings.google_redirect_uri,
        kakao_client_id=settings.kakao_client_id,
        kakao_client_secret=settings.kakao_client_secret,
        kakao_redirect_uri=settings.kakao_redirect_uri,
        naver_client_id=settings.naver_client_id,
        naver_client_secret=settings.naver_client_secret,
        naver_redirect_uri=settings.naver_redirect_uri,
        session_secret=settings.user_session_secret,
        session_ttl_sec=settings.user_session_ttl_sec,
        cookie_name=settings.user_cookie_name,
        cookie_secure=settings.user_cookie_secure,
    )


@lru_cache(maxsize=1)
def get_admin_login_limiter() -> SlidingWindowLimiter:
    """**로그인 전용** IP 기준 카운터(브루트포스 방어).

    RateLimitMiddleware(부록 O)는 `RATE_LIMIT_ENABLED=false` 인 로컬에서 아예 등록되지 않는다.
    비밀번호 추측 방어는 그 스위치와 무관하게 **항상** 있어야 하므로 라우터 레벨에 따로 둔다.
    (배포에서는 미들웨어의 `admin` 버킷과 이중으로 걸린다 — 한도가 같아 체감 차이는 없다.)
    """
    return SlidingWindowLimiter(
        {"admin_login": settings.admin_login_per_min},
        window_sec=60,
        max_keys=settings.rate_limit_max_keys,
    )


@lru_cache(maxsize=1)
def get_summarizer() -> Summarizer:
    # Phase2 부록 G: 소개글 3줄 요약용 로컬 Ollama 요약기 싱글턴(온보딩과 같은 모델 재사용, 비용 0).
    # 상용 전환 시 create_summarizer_from_settings 내부에서 CloudProvider 로 교체(계약 불변).
    return create_summarizer_from_settings(settings)
