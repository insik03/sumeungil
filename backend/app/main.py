"""FastAPI 앱 진입점.

config import 시점에 필수 키 검증(fail-fast)이 이미 수행된다.
라우터/CORS 등록. MVP-1 엔드포인트: /health(2종), /api/v1/congestion/board.
상용 확장 시 이 파일에 라우터를 additive 로 추가한다(온보딩·경로비교·지도 등).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .api import (
    admin,
    auth,
    collections,
    compare,
    congestion,
    course_share,
    courses,
    festivals,
    health,
    inquiries,
    onboarding,
    places,
    plan,
    regions,
    reviews,
    slack,
    tips,
    visit,
    weather,
)
from .config import settings
from .deps import (
    get_admin_auth,
    get_cache,
    get_congestion_repository,
    get_database,
    get_user_auth,
)
from .middleware.anomaly_alert import AnomalyAlertMiddleware
from .middleware.error_alert import ErrorAlertMiddleware
from .middleware.rate_limit import RateLimitMiddleware, build_limits_from_settings
from .middleware.visit_log import VisitLogMiddleware
from .repositories import visit_repo
from .services import festival_service, share_service, slack_notify, slack_report
from .util.time import now_kst

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("sumeungil.main")

# 보안(QA M-1): httpx 기본 INFO 로거는 매 원천 호출 시 전체 요청 URL을 stdout에 남긴다.
# 공공데이터 URL은 쿼리스트링에 serviceKey(=PUBLIC_DATA_API_KEY)를 포함하므로,
# httpx 로거를 WARNING 이상으로 올려 정상 호출 URL(=시크릿)이 로그에 새지 않게 한다.
# 상용 로그 수집/배포 환경에서 이 누출은 Critical 이므로 반드시 유지할 것.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

async def _prewarm_festivals() -> None:
    """앱 기동 직후 전국 축제 스윕을 1회 미리 태워 festival_service 캐시를 채운다(QA Major 대응,
    2026-07-30). 콜드 캐시 상태로 첫 축제 문답 요청이 들어오면 원천 2개를 페이지네이션하느라
    수 초~십수 초가 걸려 축제 조회 타임아웃에 걸리기 쉬웠다 —
    부팅 시 미리 채워두면 실사용 트래픽의 첫 요청부터 캐시 히트가 된다.

    실패해도 앱 기동에 영향이 없다(try/except로 로그만 — 원천 API 문제로 부팅이 막히면 안 된다).
    """
    try:
        await festival_service.build_festivals_response(region_code=None, limit=1, cache=get_cache())
        logger.info("festivals prewarm 완료(전국 스윕 캐시 채움)")
    except Exception as exc:  # noqa: BLE001 — 프리워밍 실패는 무해(다음 요청이 다시 스윕)
        logger.info("festivals prewarm 실패(무시, 다음 요청이 재시도): %s", exc)


async def _prewarm_home() -> None:
    """부록 Q(2026-07-31): 홈 첫 화면이 쓰는 두 묶음을 미리 데운다.

    - 전국 9권역 날씨 보드: D18 9회(실측 콜드 ~8초, 이후 30분 캐시)
    - 홈 지역 다양성(diverse) 목록: 9권역 board 9회 + 사진(실측 콜드 ~24초, 이후 각 캐시)
    콜드 상태로 사용자의 첫 요청이 들어오면 그 요청이 이 시간을 통째로 기다린다 —
    축제 프리워밍(_prewarm_festivals)과 같은 이유·같은 방식(fire-and-forget, 실패 무해)이다.
    """
    from .deps import get_congestion_repository, get_spot_repository
    from .services import featured_service, nationwide_weather_service

    try:
        await nationwide_weather_service.build_nationwide_weather(get_cache())
        logger.info("weather/nationwide prewarm 완료")
    except Exception as exc:  # noqa: BLE001 — 프리워밍 실패는 무해(다음 요청이 재시도)
        logger.info("weather/nationwide prewarm 실패(무시): %s", exc)
    try:
        await featured_service.build_featured_response(
            region_code=None, limit=8,
            spot_repo=get_spot_repository(),
            congestion_repo=get_congestion_repository(),
            cache=get_cache(), diverse=True,
        )
        logger.info("featured(diverse) prewarm 완료")
    except Exception as exc:  # noqa: BLE001
        logger.info("featured(diverse) prewarm 실패(무시): %s", exc)


async def _share_retention_loop() -> None:
    """공유 코스 보존정책 정리 — 기동 직후 1회 + 이후 하루 1회(QA M-2 대응, 2026-08-01).

    프리워밍과 같은 성격이다: fire-and-forget · 실패해도 서비스에 영향 없음(다음 주기 재시도).
    정리 자체는 batch 단위 짧은 트랜잭션 여러 번이라 조회/쓰기를 오래 막지 않는다
    (`share_service.run_cleanup` 주석 참고).
    """
    while True:
        try:
            result = await share_service.run_cleanup(get_database())
            logger.info(
                "share retention 주기 정리 expired=%d overflow=%d remaining=%d",
                result["expired"], result["overflow"], result["remaining"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 정리 실패로 서비스가 죽으면 안 된다
            logger.warning("share retention 정리 실패(무시, 다음 주기 재시도): %s", exc)
        await asyncio.sleep(max(60, settings.share_cleanup_interval_sec))


async def _visit_retention_loop() -> None:
    """방문 집계 자동 삭제 — 기동 직후 1회 + 이후 하루 1회(2026-08-18 보안 감사 A-4).

    관리자 화면(AdminTraffic.tsx)이 "90일간 보관하고 자동으로 지웁니다"라고 안내하는데,
    실제로 `visit_repo.prune` 을 부르는 곳이 **어디에도 없었다**(집계가 무한히 쌓임 =
    개인정보 처리방침 위반 + 디스크 증가). `_share_retention_loop` 와 같은 패턴으로 배선한다:
    fire-and-forget · 실패해도 서비스 무영향 · 다음 주기 재시도.
    """
    while True:
        try:
            cutoff = (now_kst() - timedelta(days=visit_repo.RETENTION_DAYS)).strftime("%Y-%m-%d")
            removed = await get_database().awrite(
                lambda conn, _c=cutoff: visit_repo.prune(conn, before_day=_c)
            )
            if removed:
                logger.info(
                    "visit retention 정리 removed=%d (보관 %d일, cutoff=%s)",
                    removed, visit_repo.RETENTION_DAYS, cutoff,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 정리 실패로 서비스가 죽으면 안 된다
            logger.warning("visit retention 정리 실패(무시, 다음 주기 재시도): %s", exc)
        await asyncio.sleep(24 * 60 * 60)


async def _daily_summary_loop() -> None:
    """슬랙 아침 운영 요약 — 매일 지정 시각(KST)에 1회 (2026-08-18, 대표 지시).

    다른 루프들과 다른 점: **부팅 직후에 보내지 않는다.** 배포할 때마다 브리핑이 오면
    알림이 소음이 된다. 그래서 첫 실행 전에 다음 지정 시각까지 기다린다.

    시각을 맞추는 방식은 "24시간 sleep" 이 아니라 **매번 다음 목표 시각까지의 초를 다시
    계산**하는 것이다. 24시간 고정 sleep 은 컨테이너 재시작 시점에 따라 발송 시각이
    조금씩 밀려 결국 새벽에 오게 된다(드리프트).

    `_share_retention_loop` 와 같은 안전 원칙: fire-and-forget · 실패해도 서비스 무영향 ·
    다음 주기 재시도.
    """
    hour = settings.slack_daily_summary_hour
    while True:
        now = now_kst()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(60, (target - now).total_seconds()))
        try:
            text = await slack_report.build_daily_summary(
                get_database(),
                get_cache(),
                get_congestion_repository(),
                prometheus_base_url=settings.prometheus_base_url,
            )
            sent = await slack_notify.post(text, webhook_url=settings.slack_webhook_url)
            logger.info("슬랙 아침 요약 발송 %s", "완료" if sent else "실패(무시)")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 요약 실패로 서비스가 죽으면 안 된다
            logger.warning("슬랙 아침 요약 실패(무시, 내일 재시도): %s", exc)


async def _prewarm_all() -> None:
    """프리워밍을 **순차로** 돌린다 — 기동 직후 원천 호출이 한꺼번에 몰리면(축제 스윕 + D18 9회 +
    board 9회 + 사진) 무료 원천 쪽에서 타임아웃/스로틀이 나기 쉽고, 그 시간에 들어온 실사용
    요청과도 경합한다. 실측 총 소요는 축제 스윕 + 약 73초(보드 8초 + 홈 다양성 65초)다.
    """
    await _prewarm_festivals()
    await _prewarm_home()


def _warn_if_session_secret_derived() -> None:
    """`ADMIN_SESSION_SECRET` 미설정을 기동 시 **1회** 경고한다 (2026-08-18 보안 M-2).

    `settings.admin_session_secret` 을 보면 안 된다 — config 가 이미 `JWT_SECRET_KEY` 로
    폴백해 채워 넣기 때문에 "설정했는지"를 구분할 수 없다. 그래서 **원본 환경변수**를 본다.

    실제로 무엇이 나빠지는가(과장하지 않고 정확히):
      - 관리자 세션 서명키가 `JWT_SECRET_KEY` 또는 `ADMIN_PASSWORD_HASH` 파생값이 된다.
        즉 키 하나가 두 역할을 겸해, 그 값이 새면 세션 위조까지 한 번에 성립한다.
      - 방문 통계 IP 가명화 키도 같은 파생값을 쓴다. **집계가 꺼지는 것은 세 값(SESSION/
        JWT/PASSWORD_HASH)이 모두 없을 때뿐**이다(그때는 visit_log 가 별도 경고를 낸다).
    DEPLOY.md (h-1) ②-b 의 검증 단계가 이 경고 문자열을 grep 한다 — 문구를 바꾸면 그쪽도 고칠 것.
    """
    if os.getenv("ADMIN_SESSION_SECRET", "").strip():
        return
    logger.warning(
        "ADMIN_SESSION_SECRET 미설정 — 세션 서명키/방문 해시키가 파생값으로 동작 중. "
        "운영에서는 반드시 설정할 것 (deploy/DEPLOY.md (h-1) ②-b)"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_if_session_secret_derived()
    # 부록 R + Phase C: 저장소(PostgreSQL, 2026-08-17 SQLite에서 전환) 스키마를 기동 시
    # 1회 준비한다. 실패해도 부팅을 막지 않는다 — 나머지 조회 기능은 DB 없이 그대로 동작한다.
    # (실패 시 해당 라우트만 503 STORAGE_UNAVAILABLE 로 응답한다.)
    # db.safe_target(호스트:포트/DB명만)만 로그에 남긴다 — db.dsn은 비밀번호를 담고 있다.
    if settings.community_enabled:
        db = get_database()
        ok = await asyncio.to_thread(db.ensure_ready)
        if ok:
            logger.info("community 저장소 준비 완료 target=%s", db.safe_target)
        else:
            logger.error(
                "community 저장소 초기화 실패 — 리뷰/공유 API 는 503 을 반환합니다 target=%s",
                db.safe_target,
            )
    else:
        logger.info("community 기능 비활성(COMMUNITY_ENABLED=false) — 저장소 미초기화")

    # create_task로 fire-and-forget — 부팅 시퀀스를 막지 않는다(앱은 즉시 요청을 받기 시작한다).
    # QA 약식(2026-07-31) Minor 5: pending 태스크는 강참조가 없으면 드물게 GC 될 수 있어
    # 참조를 보관하고, 종료 시 취소해 "Task was destroyed but it is pending" 경고를 막는다.
    prewarm_task = asyncio.create_task(_prewarm_all())
    # 보존정책 정리도 같은 방식(fire-and-forget + 강참조 보관 + 종료 시 취소).
    # community 가 꺼져 있으면 저장소를 초기화하지도 않았으므로 돌리지 않는다.
    retention_task = (
        asyncio.create_task(_share_retention_loop()) if settings.community_enabled else None
    )
    # 방문 집계 정리는 **무조건** 돈다 (2026-08-18 QA Minor-1).
    # 처음엔 community_enabled 조건을 붙였는데, `VisitLogMiddleware` 는 그 스위치와 무관하게
    # 항상 등록된다 — 즉 킬스위치를 내린 상태에서도 방문 기록은 계속 쌓이는데 90일 정리만
    # 영영 안 도는 조합이 생긴다(= 관리자 화면의 "90일 후 자동 삭제" 안내가 거짓말이 된다).
    # 저장소가 준비되지 않았으면 prune 이 실패하지만, 루프가 예외를 삼키고 다음 날 재시도하므로
    # 서비스에는 무해하다(로그 warning 하루 1줄).
    visit_retention_task = asyncio.create_task(_visit_retention_loop())
    # 슬랙 아침 요약 — 웹훅이 있고 시각이 0~23 범위일 때만 돈다(-1 이면 요약만 끈다).
    # 위 루프들과 달리 community 와 무관하다: DB 가 죽어도 서버 상태는 알려야 하고,
    # slack_report 가 집계 조회 실패를 자체적으로 감당한다.
    summary_task = (
        asyncio.create_task(_daily_summary_loop())
        if settings.slack_webhook_url and 0 <= settings.slack_daily_summary_hour <= 23
        else None
    )
    yield
    if not prewarm_task.done():
        prewarm_task.cancel()
    if retention_task is not None and not retention_task.done():
        retention_task.cancel()
    if not visit_retention_task.done():
        visit_retention_task.cancel()
    if summary_task is not None and not summary_task.done():
        summary_task.cancel()
    get_database().close()


# 대화형 API 문서는 **개발에서만** 연다 (보안 점검 M-4, 2026-08-09).
#
# 두 가지가 걸린다:
#  1. 관리자 콘솔이 켜지면서 삭제 엔드포인트를 포함한 스키마 13개가 익명에게 광고된다.
#     부록 T 는 "관리자 기능이 없으면 404 로 존재 자체를 숨긴다"고 설계했는데,
#     켜진 지금 /openapi.json 이 그 설계를 정면으로 무력화한다.
#  2. 이쪽이 더 실질적이다 — FastAPI 기본 Swagger UI 는 **외부 CDN 스크립트를
#     우리 오리진에서** 로드한다. 그 CDN 이 오염되면 sumeungil.co.kr 에서 실행되는
#     JS 가 되고, 세션 쿠키가 HttpOnly 여도 same-origin fetch 에는 자동으로 실린다.
#     관리자가 로그인한 브라우저로 /docs 를 열기만 해도 성립하며, SameSite=Lax 는
#     same-origin 이라 아무 방어가 되지 않는다.
#
# nginx 에서도 같은 경로를 막지만(이중 방어), 여기서 끄는 것이 근본이다 —
# nginx 설정을 누가 되돌려도 앱이 스스로 닫혀 있다.
_docs_enabled = settings.app_env.lower() not in {"production", "prod"}

app = FastAPI(
    title="숨은길 (Sumeungil) API",
    version="mvp-1",
    description="관광지 실시간 혼잡도 전광판 — MVP-1 walking skeleton",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# 레이트 리미팅 (부록 O). 공개 배포 전용 방어선 — 인증이 없는 서비스라 IP 가 유일한 식별자다.
#
# ① **꺼져 있으면 아예 등록하지 않는다.** RATE_LIMIT_ENABLED 기본값이 false 이므로 로컬
#    개발/기존 검증 스크립트의 ASGI 스택은 이 기능 도입 전과 바이트 단위로 동일하다
#    (BaseHTTPMiddleware 는 요청마다 태스크 그룹을 만든다 — 통과만 시켜도 공짜가 아니다).
#    미들웨어 내부에도 enabled 가드가 남아 있다(이중 안전장치).
# ② **등록 순서가 계약이다.** Starlette 는 나중에 add_middleware 한 것이 더 바깥이다.
#    CORS 를 아래에서 나중에 등록해야 CORS 가 바깥이 되어 429 응답에도 CORS 헤더가 붙는다
#    (안 그러면 브라우저가 429 대신 "CORS 에러"를 보고 원인 파악이 어려워진다).
#    프리플라이트 OPTIONS 도 바깥의 CORS 가 먼저 처리하므로 레이트 리밋 대상이 아니다.
#    순서를 바꾸면 조용히 깨지는 종류의 회귀다 — 이 블록을 CORS 아래로 옮기지 말 것.

# --- 방문 집계 (부록 X, 2026-08-10) -------------------------------------------------
# 대표 지시: "관리자 화면에서 트래픽·오늘 방문자를 봐야 한다".
# 그전까지 앱은 방문을 전혀 기록하지 않았고, nginx 로그는 컨테이너를 재생성할 때마다
# 통째로 사라져 **배포할 때마다 리셋**됐다. 그래서 앱이 직접 집계를 쌓는다.
#
# **레이트리밋보다 먼저 등록한다.** Starlette 는 나중에 등록한 것이 더 바깥이므로,
# 이렇게 두면 VisitLog 가 더 **안쪽**이 되어 429 로 끊긴 요청은 집계에 들어오지 않는다.
# 차단된 요청은 방문이 아니다 — 봇이 두드린 횟수로 '방문자 수'가 부풀지 않게 한다.
#
# 원본 IP 는 저장하지 않는다(대표 결정, 2026-08-10). 해싱 키는 **미들웨어가 아니라
# `visit_log._secret_key()` 가** 결정한다(2026-08-18 QA Minor-4 — 여기 있던 "없으면 JWT
# 시크릿으로 폴백" 설명은 그쪽으로 옮겨졌다). 우선순위는 ADMIN_SESSION_SECRET →
# JWT_SECRET_KEY → ADMIN_PASSWORD_HASH 파생 → **셋 다 없으면 집계 중단(fail-closed)**.
# 키를 여기서 주입하지 않는 이유: 페이지 비콘(`api/visit.py`)과 키가 갈리면 같은 사람이
# 두 명으로 세어진다. 그래서 양쪽이 같은 모듈 함수 하나를 부른다.
app.add_middleware(
    VisitLogMiddleware,
    db=get_database(),
    trust_proxy=settings.rate_limit_trust_proxy,
    trusted_networks=settings.rate_limit_trusted_proxy_networks or None,
)

if settings.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        enabled=True,
        limits=build_limits_from_settings(settings),
        window_sec=settings.rate_limit_window_sec,
        trust_proxy=settings.rate_limit_trust_proxy,
        max_keys=settings.rate_limit_max_keys,
        trusted_networks=settings.rate_limit_trusted_proxy_networks or None,
    )
else:
    logger.info("rate limit 미등록(RATE_LIMIT_ENABLED=false) — 로컬 개발 기본값")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # 기본 http://localhost:3000
    # 기본 False 유지 — 공개 엔드포인트는 쿠키를 쓰지 않는다(무회귀).
    # 부록 T(관리자)는 **동일 오리진**(nginx 뒤 /admin → /api/v1/admin)을 전제로 하므로
    # 배포에서도 False 로 둔다. 로컬에서 프론트(:3000)/백엔드(:8000)를 따로 띄워 관리자
    # 화면을 개발할 때만 CORS_ALLOW_CREDENTIALS=true 로 켠다(와일드카드 오리진이면 config
    # 가 강제로 False 로 되돌린다 — 브라우저도 그 조합을 거부한다).
    allow_credentials=settings.cors_allow_credentials,
    # MVP-3 온보딩 analyze 는 POST → GET·POST·OPTIONS(preflight) 허용.
    # 부록 R(2026-08-01): 리뷰 수정/삭제 때문에 PATCH·DELETE 를 추가한다. 빠뜨리면
    # 브라우저가 프리플라이트 단계에서 막아 "CORS 에러"로만 보인다(서버 로그엔 흔적 없음).
    # allow_headers=["*"] 이므로 X-Device-Id 는 별도 등록 없이 통과한다.
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# --- 5xx 슬랙 알림 (2026-08-18, 대표 지시 — #알림-봇) ------------------------------
# **가장 바깥에 둔다.** Starlette 는 나중에 add_middleware 한 것이 더 바깥이므로, CORS
# 보다 나중에 등록하면 이 미들웨어가 최외곽이 되어 안쪽(CORS·레이트리밋·방문집계)에서
# 터진 5xx 까지 한 곳에서 잡는다. 응답을 읽기만 하고 고치지 않으므로 CORS 헤더에는
# 영향이 없다(429 에 CORS 헤더가 붙어야 한다는 위 계약은 그대로 유지된다).
#
# 웹훅 URL 이 없으면 **등록 자체를 생략한다** — 레이트리밋과 같은 원칙이다.
# BaseHTTPMiddleware 는 요청마다 태스크 그룹을 만들어 통과만 시켜도 공짜가 아니다.
#
# 켜졌을 때도 **반드시 한 줄 남긴다.** 처음엔 꺼진 경우만 로그를 찍었는데, 운영 배포
# 직후 "켜졌는지" 확인할 방법이 없었다 — 로그가 비어 있는 게 "켜짐"인지 "부팅 로그가
# tail 범위 밖으로 밀려남"인지 구분이 안 됐다(2026-08-18 실제로 확인 불가). 없음을
# 증명하는 로그보다 있음을 증명하는 로그가 낫다. URL 은 시크릿이라 절대 찍지 않는다.
if settings.slack_webhook_url:
    app.add_middleware(
        ErrorAlertMiddleware,
        webhook_url=settings.slack_webhook_url,
        env=settings.app_env,
        dedup_window_sec=settings.slack_alert_dedup_window_sec,
    )
    logger.info(
        "슬랙 5xx 알림 등록 완료 — 중복억제 창 %d초 (URL 은 로그에 남기지 않는다)",
        settings.slack_alert_dedup_window_sec,
    )
else:
    logger.info("슬랙 5xx 알림 미등록(SLACK_WEBHOOK_URL 미설정) — 로컬 개발 기본값")

# --- 이상행동(브루트포스 정황) 슬랙 알림 (2026-08-22, 대표 지시) -------------------
# 4차 보안 감사(DAST)가 발견한 XFF 스푸핑 우회는 rate_limit.py 에서 패치했지만, 그
# 시도 자체가 실제로 벌어지는지는 감시가 없었다. IP 별이 아니라 서비스 전체 집계로
# 401/429 를 세므로, 매 요청마다 IP 를 바꾸는 공격에도(스푸핑이든 실제 봇넷이든) 반응한다.
# ErrorAlertMiddleware 와 같은 웹훅을 쓰므로 등록 조건도 동일하다.
if settings.slack_webhook_url:
    app.add_middleware(
        AnomalyAlertMiddleware,
        webhook_url=settings.slack_webhook_url,
        env=settings.app_env,
    )
    logger.info("슬랙 이상행동(401/429 몰림) 알림 등록 완료")

# --- 운영 지표 (Prometheus, 2026-08-18) -----------------------------------------------
# 대표가 aitestbed.kr(그라파나 관측 인스턴스)를 받아온 걸 계기로 도입. Postgres를 직접
# 인터넷에 열지 않기로 하고(대표 선택), 대신 이 표준적인 방식을 골랐다.
#
# **가장 바깥에 등록한다** — 5xx 슬랙 알림 미들웨어보다도 나중에(=바깥에) 등록해야, 그
# 미들웨어를 포함해 실제로 클라이언트가 받는 최종 상태코드·소요시간이 지표에 잡힌다.
# 안쪽에 두면 레이트리밋 429나 CORS 프리플라이트 같은 것들이 지표에서 빠진다.
#
# **/metrics는 인터넷에 노출하지 않는다.** nginx의 어떤 location도 이 경로를 backend로
# 프록시하지 않는다(deploy/nginx.conf에 명시적 404 블록도 별도로 둔다 — 나중에 누가
# `location /api/`를 넓히더라도 안전하게). 오직 같은 도커 네트워크 안의 prometheus
# 컨테이너만 `http://backend:8000/metrics`로 직접 긁어간다(deploy/prometheus.yml).
# 그라파나(aitestbed.kr)는 prometheus를 nginx의 `/prom/`(Basic Auth) 뒤에서 조회한다 —
# DB나 앱 내부를 직접 노출하지 않고도 응답시간·에러율·요청수 같은 운영 지표를 볼 수 있다.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(congestion.router)
app.include_router(regions.router)
app.include_router(onboarding.router)
app.include_router(places.router)
app.include_router(compare.router)
app.include_router(courses.router)
app.include_router(collections.router)
app.include_router(festivals.router)
app.include_router(weather.router)    # 부록 Q.1: 전국 9권역 날씨 보드
app.include_router(plan.router)       # 부록 Q.2: 출발일 지정 전망(오늘~+180일)
app.include_router(reviews.router)      # 부록 R: 후기(별점+한줄평) — SQLite 저장
app.include_router(course_share.router) # 부록 R: 코스 공유(share_code) — SQLite 저장
app.include_router(inquiries.router)    # 2026-08-18: 고객문의(마이페이지, 로그인 필수)
app.include_router(tips.router)        # 부록 Z: 개인화 여행 팁(로그인 선택 — 비로그인은 정적)
app.include_router(visit.router)        # 부록 X: 페이지 조회 비콘(프론트가 처리하는 화면 경로 집계)

# 슬랙 슬래시 명령어 (2026-08-18) — **서명 검증 키가 없으면 등록하지 않는다.**
# 이 엔드포인트는 인증 쿠키를 쓸 수 없어(슬랙 서버가 호출) 서명 검증이 유일한 방어선이다.
# 키가 없는데 열어두면 URL 을 아는 누구나 방문자·문의 건수를 조회할 수 있다.
# ADMIN_PASSWORD_HASH 가 없으면 관리자 라우터가 사라지는 것과 같은 fail-closed 원칙.
if settings.slack_signing_secret:
    app.include_router(slack.router)
    logger.info("슬랙 슬래시 명령어 등록 완료 (/api/v1/slack/commands)")
else:
    logger.info("슬랙 슬래시 명령어 미등록(SLACK_SIGNING_SECRET 미설정)")

# 부록 T: 관리자(운영) 콘솔.
#
# **설정하지 않으면 존재하지 않는다.** ADMIN_PASSWORD_HASH 가 없거나 형식이 틀리면 이
# 라우터를 등록조차 하지 않는다 → /api/v1/admin/* 은 404 이고 OpenAPI(/docs)에도 없다.
# "비활성일 때 503 을 준다" 같은 방식은 관리자 기능의 존재 자체를 알려주므로 쓰지 않았다.
# 기본 비밀번호를 만들지 않는 이유는 자명하다 — 공개 서버에서 즉시 뚫린다.
_admin_auth = get_admin_auth()
if _admin_auth.enabled:
    app.include_router(admin.router)
    logger.info(
        "관리자 콘솔 활성화 — /api/v1/admin/* (세션 %d시간, 쿠키 secure=%s)",
        settings.admin_session_ttl_sec // 3600,
        settings.admin_cookie_secure,
    )
    if not settings.admin_session_secret:
        # 보안 점검 M-2(2026-08-09): 이 상태에서는 세션 서명키가 **비밀번호 해시에서
        # 파생**된다. 그러면 scrypt 해시가 "유출돼도 크래킹 비용이 드는 verifier" 가
        # 아니라 **자격증명 그 자체**가 된다 — 해시 문자열만 알면 비밀번호 없이 유효한
        # 세션 토큰을 만들 수 있다. .env 백업·VM 스냅샷·터미널 스크롤백이 전부 관리자
        # 권한 유출 경로가 된다(2026-08-09 compose 경고 출력으로 실제 노출 사고 발생).
        # ADMIN_SESSION_SECRET 를 넣으면 키가 비밀번호와 분리되고, 감사 로그의 가명화
        # 키(ip_hash/actor_hash)도 비밀번호 교체와 무관해진다(Mn-6 동시 해소).
        logger.warning(
            "ADMIN_SESSION_SECRET 미설정 — 세션 서명키가 비밀번호 해시에서 파생됩니다. "
            "해시 문자열이 새면 비밀번호 없이 세션 위조가 가능합니다. "
            "python3 -c \"import secrets;print(secrets.token_urlsafe(48))\" 결과를 .env 에 넣으세요."
        )
    if not settings.admin_cookie_secure:
        logger.warning(
            "ADMIN_COOKIE_SECURE=false — 관리자 쿠키가 평문(HTTP)으로도 전송됩니다. "
            "HTTPS 전환 전까지 신뢰할 수 없는 네트워크에서 관리자 로그인을 하지 마세요."
        )
elif _admin_auth.misconfigured:
    logger.error(
        "ADMIN_PASSWORD_HASH 형식이 올바르지 않습니다(값은 로그하지 않음) — 관리자 기능 비활성. "
        "backend/scripts/make_admin_hash.py 로 다시 생성하세요."
    )
else:
    logger.info("관리자 기능 비활성(ADMIN_PASSWORD_HASH 미설정) — /api/v1/admin/* 라우트 미등록")

# 구글·카카오 로그인(2026-08-17 대표 지시, 카카오는 같은 날 추가) — 데모 닉네임 로그인을
# 완전히 대체.
#
# **설정하지 않으면 존재하지 않는다** — admin과 동일 원칙. 세션 시크릿(USER_SESSION_SECRET)이
# 없으면 라우터 자체를 등록하지 않는다. 세션 시크릿은 있어도 구글·카카오 둘 다 미설정이면
# 마찬가지로 등록하지 않는다(로그인 수단이 하나도 없는데 /api/v1/auth/* 만 살아있어봐야
# 의미가 없다) — 반대로 둘 중 하나만 설정돼 있어도 라우터는 등록되고, 그 provider의
# `/{provider}/login`·`/{provider}/callback`만 각자 `google_enabled`/`kakao_enabled`로
# 개별 404 처리된다(auth.py 참고). 콘솔에서 대표가 직접 OAuth 클라이언트를 발급해야만 켜진다.
_user_auth = get_user_auth()
if _user_auth.enabled and (_user_auth.google_enabled or _user_auth.kakao_enabled):
    app.include_router(auth.router)
    active_providers = [
        name
        for name, on in (("구글", _user_auth.google_enabled), ("카카오", _user_auth.kakao_enabled))
        if on
    ]
    logger.info(
        "로그인 활성화(%s) — /api/v1/auth/* (세션 %d일, 쿠키 secure=%s)",
        "+".join(active_providers),
        settings.user_session_ttl_sec // 86400,
        settings.user_cookie_secure,
    )
    if not settings.user_cookie_secure:
        logger.warning("USER_COOKIE_SECURE=false — 로그인 쿠키가 평문(HTTP)으로도 전송됩니다.")
else:
    # QA M-6(2026-08-17) — 예전엔 GOOGLE_* 3개만 안내했는데, enabled 가 세션 시크릿까지
    # 보게 되면서(C-1 수정) "GOOGLE_* 는 다 있는데 시크릿만 없는" 상태에서도 이 메시지가
    # 나가 엉뚱한 변수를 가리켰다. 2026-08-17 카카오 추가로 provider별 필드명도 바뀌어서
    # (client_id→google_client_id 등) 미설정 항목을 provider별로 구분해 로그한다(값은
    # 노출 안 함).
    missing = []
    if not settings.user_session_secret:
        missing.append("USER_SESSION_SECRET(또는 JWT_SECRET_KEY)")
    for provider_label, cid, secret, redirect in (
        ("GOOGLE", _user_auth.google_client_id, _user_auth.google_client_secret, _user_auth.google_redirect_uri),
        ("KAKAO", _user_auth.kakao_client_id, _user_auth.kakao_client_secret, _user_auth.kakao_redirect_uri),
    ):
        provider_missing = [
            f"{provider_label}_{field}"
            for field, value in (("CLIENT_ID", cid), ("CLIENT_SECRET", secret), ("REDIRECT_URI", redirect))
            if not value
        ]
        if len(provider_missing) == 3:
            # 셋 다 없으면 "그 provider를 아예 안 씀"이라 개별 나열 대신 한 줄로 요약.
            missing.append(f"{provider_label}_*(미설정)")
        else:
            missing.extend(provider_missing)
    logger.info(
        "로그인 비활성(%s) — /api/v1/auth/* 라우트 미등록",
        ", ".join(missing) if missing else "원인 불명",
    )


@app.get("/", tags=["root"])
async def root():
    return {"service": "sumeungil-api", "version": "mvp-1", "docs": "/docs"}
