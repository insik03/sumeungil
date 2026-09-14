"""애플리케이션 설정 로더.

.env 로딩 규칙:
  1) backend/.env 가 있으면 그것을 사용
  2) 없으면 상위 프로젝트의 projects/sumeungil/.env 를 fallback 으로 참조
필수 키(PUBLIC_DATA_API_KEY)가 없으면 부팅 즉시 종료한다(fail-fast).
시크릿 값은 절대 로그로 출력하지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# backend/  (config.py 기준 두 단계 위)
BACKEND_DIR = Path(__file__).resolve().parent.parent
# 상위 sumeungil/.env (실키 보관 위치) — backend/.env 가 없을 때 fallback
FALLBACK_ENV = BACKEND_DIR.parent.parent / "sumeungil" / ".env"


def _load_env() -> str:
    """사용한 .env 경로 문자열을 반환(로깅용, 값은 노출 안 함)."""
    local_env = BACKEND_DIR / ".env"
    if local_env.exists():
        load_dotenv(local_env)
        return str(local_env)
    if FALLBACK_ENV.exists():
        load_dotenv(FALLBACK_ENV)
        return str(FALLBACK_ENV)
    # .env 파일이 없어도 프로세스 환경변수로 주입됐을 수 있으므로 계속 진행
    return "(no .env file — using process environment)"


class Settings:
    """런타임 설정. 인스턴스화 시점에 필수 키를 검증한다."""

    def __init__(self) -> None:
        self.env_source = _load_env()

        # --- 필수 ---
        self.public_data_api_key: str = os.getenv("PUBLIC_DATA_API_KEY", "").strip()

        # --- 선택(기본값 있음) ---
        # 데모 기본 지역: 부산광역시 해운대구 — 실호출로 데이터 존재 확인함.
        self.default_area_cd: str = os.getenv("DEFAULT_AREA_CD", "26").strip()
        self.default_sigungu_cd: str = os.getenv("DEFAULT_SIGUNGU_CD", "26350").strip()
        self.cache_ttl_sec: int = int(os.getenv("CACHE_TTL_SEC", "600"))
        # 부록 M 예보 캐시 TTL — board(600s)와 분리한 이유:
        #   (1) 원천이 주는 값은 '날짜별 예측치'라 하루 안에서 바뀔 이유가 거의 없다(baseYmd 일 단위).
        #   (2) 예보 응답은 관광지 전체 × 17일이라 board(1페이지)보다 페이로드가 크고 최대 3페이지
        #       호출이 필요하다 → 짧은 TTL 은 무료 원천 쿼터만 소모한다.
        #   (3) "이번 주 한적한 날"이 새로고침마다 흔들리면 오히려 신뢰를 잃는다(표시 안정성).
        # 그래서 6h. 날짜 롤오버는 서버가 매 요청마다 '오늘' 기준으로 윈도우를 다시 자르므로 안전.
        self.forecast_cache_ttl_sec: int = int(os.getenv("FORECAST_CACHE_TTL_SEC", str(6 * 60 * 60)))
        self.upstream_timeout_sec: float = float(os.getenv("UPSTREAM_TIMEOUT_SEC", "8"))
        self.app_env: str = os.getenv("APP_ENV", "development").strip()

        # 공공 API 원천
        self.kto_base_url: str = os.getenv(
            "KTO_BASE_URL",
            "https://apis.data.go.kr/B551011/TatsCnctrRateService/tatsCnctrRatedList",
        ).strip()

        # CORS 허용 오리진 (콤마 구분)
        raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").strip()
        self.cors_origins: list[str] = [o.strip() for o in raw_origins.split(",") if o.strip()]
        # 부록 T: 관리자 세션 쿠키를 **크로스 오리진**으로 주고받아야 할 때만 true.
        # 배포는 nginx 뒤 동일 오리진(http://<IP>/admin → /api/v1/admin)이라 false 로 둔다.
        # 로컬에서 프론트(:3000)와 백엔드(:8000)를 따로 띄워 관리자 화면을 개발할 때만 켠다.
        # 와일드카드 오리진과 credentials 를 함께 켜는 것은 브라우저가 거부하고 보안상으로도
        # 금지이므로, `*` 가 섞여 있으면 강제로 false 로 되돌린다(조용한 사고 방지).
        self.cors_allow_credentials: bool = (
            os.getenv("CORS_ALLOW_CREDENTIALS", "false").strip().lower() == "true"
            and "*" not in self.cors_origins
        )

        # --- LLM 제공자 선택 (2026-09-03, 대표 결정 "전부 제미나이로") ---
        # "ollama"(로컬, 기본) | "gemini"(Google Gemini API). 온보딩 태그추출·스팟/코스 요약·
        # 개인화 팁 네 경로가 전부 이 스위치를 따른다. gemini 인데 키가 비어 있으면 부팅은
        # 되지만 모든 LLM 경로가 폴백(룰/요약 생략/정적 팁)으로만 돈다 — 시작 시 경고 로그.
        # 운영 서버(CPU 2코어)의 로컬 추론이 초당 2.5토큰이라 요약·팁이 타임아웃 폴백으로
        # 빠지던 문제의 해법. 국외이전 관련 조치는 07-legal-review-gemini-api-전환.md §3
        # (PII 프리필터는 injection_guard.sanitize_free_text, 처리방침 §10 문구).
        self.llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        # 모델명은 Google AI Studio 의 현재 목록에서 확인 후 .env 로 고정한다. 2026-09-03 운영
        # 실측: gemini-2.5-flash 는 "no longer available to new users"(404) — API 가 안내한
        # gemini-3.6-flash 로 기본값을 맞췄다.
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
        # 외부 API 라 로컬 CPU 추론보다 훨씬 빠르다 — 15초면 넉넉하고, 더 길면 프론트 체감만 나빠진다.
        self.gemini_timeout_sec: float = float(os.getenv("GEMINI_TIMEOUT_SEC", "15"))

        # --- MVP-3 온보딩 LLM (로컬 Ollama) ---
        # 08-interface-contract.md 부록B B.0/B.4 — 로컬 실행, API 키·국외이전 없음.
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        # 2026-09-03 로컬 실측: qwen3.5 4B Q4가 관광 태그 스모크 테스트 F1 0.951로
        # qwen2.5 7B(0.889)·qwen3.5 2B(0.787)보다 정확했다. 개발 기본값은 4B로 두되,
        # CPU 2코어 운영 서버는 .env.production.example처럼 2B를 명시해 지연을 제한한다.
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.5:4b-q4_K_M").strip()
        # 추출·요약은 창작보다 재현성이 중요하다. Ollama 구조화 출력 권장값과 같이 0을 쓴다.
        self.ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
        # Qwen 계열 thinking은 짧은 API 응답에 지연만 더하므로 기본 비활성화한다.
        self.ollama_think: bool = os.getenv("OLLAMA_THINK", "false").strip().lower() == "true"
        # 연속 요청의 모델 재로딩(콜드 스타트)을 줄인다. 빈 문자열이면 Ollama 기본값을 쓴다.
        self.ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip()
        # CPU 추론 부하 변동 여유로 30초. (부록B §B.6: 프론트 fetch
        # 타임아웃은 이보다 길게 — 프론트 60초로 이미 넉넉함.)
        self.ollama_timeout_sec: float = float(os.getenv("OLLAMA_TIMEOUT_SEC", "30"))

        # --- Phase 2 부록 G: 소개글 AI 3줄 요약(로컬 LLM 재사용, 비용 0) ---
        # 온보딩과 동일한 Ollama 모델/엔드포인트를 재사용한다(새 키·국외이전 없음).
        # 요약 실패/타임아웃은 ai_summary:null 로 graceful — 원문 overview 는 그대로 유지된다.
        self.summary_timeout_sec: float = float(os.getenv("SUMMARY_TIMEOUT_SEC", "25"))
        # overview 는 KTO 외부 텍스트라 DoS/비용폭주 방지용 상한(요약 대상만 절단, 원문 overview 는 불변).
        self.summary_max_overview_chars: int = int(os.getenv("SUMMARY_MAX_OVERVIEW_CHARS", "1500"))
        # 성공 요약 캐시 TTL 24h — 매 클릭마다 LLM 을 돌리지 않는다(overview 캐시와 별도 키).
        self.summary_cache_ttl_sec: int = int(os.getenv("SUMMARY_CACHE_TTL_SEC", str(24 * 60 * 60)))

        # --- 부록 I.11: 코스 AI 요약(arrange/recommend 응답의 ai_summary) ---
        # 같은 로컬 Ollama 모델을 재사용한다(새 키·비용 0). 사용자가 화면에서 기다리는 경로라
        # 소개글 요약(25s)보다 짧은 타임아웃을 둔다 — 초과 시 ai_summary:null 로 graceful.
        self.course_summary_timeout_sec: float = float(os.getenv("COURSE_SUMMARY_TIMEOUT_SEC", "20"))
        # --- AI 코스 비용 상한 (2026-09-14, 대표: "코스 짜는 사람은 10~20번씩 누른다") ---
        # 코스 1회 = Gemini 2회(선택기+제목/요약) ≈ 6.6원. 같은 입력은 하루 캐시, 계정당 하루 30회,
        # 서비스 전체 하루 2,000회를 넘으면 LLM 없이 규칙 기반 코스로 폴백(화면은 그대로).
        self.course_pick_cache_ttl_sec: int = int(os.getenv("COURSE_PICK_CACHE_TTL_SEC", str(24 * 60 * 60)))
        self.course_llm_daily_cap_per_user: int = int(os.getenv("COURSE_LLM_DAILY_CAP_PER_USER", "30"))
        self.course_llm_daily_cap_global: int = int(os.getenv("COURSE_LLM_DAILY_CAP_GLOBAL", "2000"))
        # 코스 텍스트(스팟명=외부 문자열 포함) 상한 — DoS/비용 폭주 방지.
        self.course_summary_max_chars: int = int(os.getenv("COURSE_SUMMARY_MAX_CHARS", "1200"))
        # 같은 spot_ids 순서 조합의 성공 요약만 24h 캐시(매 요청마다 LLM 을 돌리지 않는다).
        self.course_summary_cache_ttl_sec: int = int(
            os.getenv("COURSE_SUMMARY_CACHE_TTL_SEC", str(24 * 60 * 60))
        )
        # ai_summary 기능 스위치(운영 중 즉시 끄기용). false 면 LLM 미호출 + ai_summary:null.
        self.course_summary_enabled: bool = (
            os.getenv("COURSE_SUMMARY_ENABLED", "true").strip().lower() != "false"
        )

        # --- 부록 Z: 개인화 여행 팁 — POST /api/v1/tips/personalized (2026-08-20) ---
        # 같은 로컬 Ollama 모델을 재사용한다(새 외부 API·키·비용 0). 실패·타임아웃·킬스위치는
        # 전부 정적 5건 폴백이므로 이 값들을 어떻게 바꿔도 화면이 비지 않는다.
        # 코스 요약과 같은 20초 상한에서 시작한다(02-ai-strategy.md §10.4 제안값).
        self.tips_timeout_sec: float = float(os.getenv("TIPS_TIMEOUT_SEC", "20"))
        # 같은 취향·같은 지역·같은 날이면 LLM 을 다시 태우지 않는다(비용 0 유지의 핵심).
        self.tips_cache_ttl_sec: int = int(os.getenv("TIPS_CACHE_TTL_SEC", str(24 * 60 * 60)))
        # 기능 스위치(운영 중 즉시 끄기용). false 면 LLM 미호출 + 즉시 정적 폴백.
        self.tips_enabled: bool = os.getenv("TIPS_ENABLED", "true").strip().lower() != "false"
        # 유효 팁 건수 하한/상한(부록 Z.4). 하한 미만이면 부분 응답 대신 정적 폴백으로 간다.
        self.tips_min_items: int = int(os.getenv("TIPS_MIN_ITEMS", "3"))
        self.tips_max_items: int = int(os.getenv("TIPS_MAX_ITEMS", "5"))

        # --- MVP-7 파트4 날씨(기상청 D18) ---
        # WEATHER_PROVIDER: "kma"(기상청 D18 실호출, 기본) | "null"(항상 준비중, 순수 graceful).
        # D18 은 이미 PUBLIC_DATA_API_KEY 에 승인·발급됨(무료). 4개 데모 지역 매핑 실호출 확인함.
        # 어떤 값이든 호출/매핑 실패 시 자동으로 None→"준비중" 폴백이라 무해하다.
        self.weather_provider: str = os.getenv("WEATHER_PROVIDER", "kma").strip()
        # D18 응답이 다소 느릴 수 있어 별도(짧은) 타임아웃 — 실패 시 graceful None.
        self.weather_timeout_sec: float = float(os.getenv("WEATHER_TIMEOUT_SEC", "6"))
        self.weather_cache_ttl_sec: int = int(os.getenv("WEATHER_CACHE_TTL_SEC", "1800"))
        # 부록 Q(2026-07-31): 9권역 보드/출발일 전망 전용 타임아웃.
        # 보드는 D18 을 9번 **동시에** 부르는데, 이때 원천이 6초를 넘기는 경우가 실측으로
        # 관측됐다(권역 1곳이 통째로 unavailable 로 떨어짐). 이 두 경로는 캐시가 길어
        # (보드 30분·전망 6시간) 한 번 잘 받아두는 편이 사용자 체감에 유리하므로 더 넉넉히 준다.
        # rerank 경로(사용자가 목록을 기다리는 곳)의 6초는 그대로 둔다 — 회귀 없음.
        self.weather_slow_timeout_sec: float = float(os.getenv("WEATHER_SLOW_TIMEOUT_SEC", "12"))
        # 권역 1곳이 오래 끌어도 보드 전체 응답 시간을 묶어두는 상한(초).
        self.weather_board_block_budget_sec: float = float(
            os.getenv("WEATHER_BOARD_BLOCK_BUDGET_SEC", "20")
        )

        # --- 부록 H.3: 스팟 사진 폴백(detailImage2 → 포토갤러리) ---
        # 대표이미지(firstimage)가 없는 스팟만 타는 경로다. 새 키 불필요 — 기존
        # PUBLIC_DATA_API_KEY 로 detailImage2 / PhotoGalleryService1 둘 다 200 확인
        # (2026-07-29, 포토갤러리는 예전 403 → 활용신청 승인 후 열림).
        # false 로 두면 폴백 원천 호출 0 + 사진 없는 스팟은 계속 null(프론트 플레이스홀더).
        self.photo_fallback_enabled: bool = (
            os.getenv("PHOTO_FALLBACK_ENABLED", "true").strip().lower() != "false"
        )

        # --- 부록 I: Tmap 길안내(코스 legs) ---
        # 선택 키. 없으면 legs 를 전부 null 로 graceful(코스 spots 는 정상). 새 키 발급 불필요 —
        # 기존 TMAP_APP_KEY 로 보행자경로/자동차경로 둘 다 실호출됨(2026-07-24 backend-engineer 확인).
        # appKey 는 헤더로만 전달하고 절대 로그·URL 에 남기지 않는다(httpx WARNING 억제, main.py).
        self.tmap_app_key: str = os.getenv("TMAP_APP_KEY", "").strip()
        self.tmap_base_url: str = os.getenv("TMAP_BASE_URL", "https://apis.openapi.sk.com").strip()
        self.tmap_timeout_sec: float = float(os.getenv("TMAP_TIMEOUT_SEC", "6"))
        # 같은 좌표쌍 구간은 24h 캐시 → 반복 호출·무료 한도 소모 방지.
        self.tmap_cache_ttl_sec: int = int(os.getenv("TMAP_CACHE_TTL_SEC", "86400"))

        # --- 레이트 리미팅 (부록 O, 2026-07-31 배포 준비) ---
        # 공개 배포(Oracle VM) 전용 방어선. 인증이 없는 서비스라 IP 기준 제한이 유일한 1차 방어다.
        # **기본값 false** — 로컬 개발/기존 검증 스크립트 동작을 바꾸지 않기 위해서다(무회귀 최우선).
        # 배포 .env 에서만 RATE_LIMIT_ENABLED=true 로 켠다.
        self.rate_limit_enabled: bool = (
            os.getenv("RATE_LIMIT_ENABLED", "false").strip().lower() == "true"
        )
        self.rate_limit_window_sec: int = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
        # LLM 추론이 도는 경로(onboarding/analyze, tips/personalized). 1건당 CPU 수 초~수십 초.
        self.rate_limit_llm_per_min: int = int(os.getenv("RATE_LIMIT_LLM_PER_MIN", "6"))
        # 코스 생성/정렬(Tmap 외부 호출 + 요약 LLM).
        self.rate_limit_course_per_min: int = int(os.getenv("RATE_LIMIT_COURSE_PER_MIN", "10"))
        # 그 외 전부(조회 API 등). 0 이하로 두면 해당 버킷 제한 해제.
        self.rate_limit_default_per_min: int = int(os.getenv("RATE_LIMIT_DEFAULT_PER_MIN", "120"))
        # 부록 R: 사용자 생성 콘텐츠 쓰기(리뷰 POST/PATCH/DELETE, 코스 공유 생성/삭제).
        # 디스크에 영구 기록이 남는 유일한 경로다. 서비스 레이어의 device_id 한도는 클라이언트가
        # device_id 를 갈아끼우면 우회되므로, IP 기준의 이 한도가 바깥 방어선이 된다.
        # 공유기 뒤 여러 사람을 고려해 개인 한도(3~5/분)보다는 넉넉히 잡는다.
        self.rate_limit_ugc_per_min: int = int(os.getenv("RATE_LIMIT_UGC_PER_MIN", "20"))
        # X-Forwarded-For 신뢰 여부. nginx 뒤에 있을 때만 true 여야 한다(헤더는 위조 가능).
        # 배포 compose 는 backend 포트를 호스트에 공개하지 않아 nginx 우회 접근이 불가능하다.
        self.rate_limit_trust_proxy: bool = (
            os.getenv("RATE_LIMIT_TRUST_PROXY", "true").strip().lower() != "false"
        )
        # 위조 IP 로 카운터 키를 무한 생성하는 메모리 공격 방지 상한.
        self.rate_limit_max_keys: int = int(os.getenv("RATE_LIMIT_MAX_KEYS", "20000"))
        # 2026-08-22(보안 검증 M-1) — X-Forwarded-For 를 신뢰할 소켓 peer 대역을 RFC1918
        # 전체보다 더 좁히고 싶을 때(예: NAVER VPC의 다른 인스턴스가 ACG 실수로 backend
        # 포트에 닿는 상황까지 막고 싶을 때) 콤마 구분 CIDR 목록으로 지정한다.
        # 빈 값(기본)이면 rate_limit.py 의 내장 기본값(RFC1918 + IPv6 ULA)을 그대로 쓴다.
        # 실제 docker 네트워크 대역 확인: `docker network inspect sumeungil-repo_sumeungil
        # --format '{{(index .IPAM.Config 0).Subnet}}'`
        from .middleware.rate_limit import parse_trusted_proxy_cidrs

        raw_trusted_cidrs = os.getenv("RATE_LIMIT_TRUSTED_PROXY_CIDRS", "").strip()
        self.rate_limit_trusted_proxy_networks = (
            parse_trusted_proxy_cidrs(raw_trusted_cidrs.split(","))
            if raw_trusted_cidrs
            else ()
        )

        # --- 부록 R: 리뷰 · 코스 공유 (2026-08-01 신설, 2026-08-17 PostgreSQL로 전환) ---
        # 원래는 표준 라이브러리 sqlite3 파일 1개였다(신규 의존성 0, 데모 스코프 전제).
        # 로그인 기반 개인화(온보딩 취향 프로필·AI 코스 저장, db/postgres.py)를 계정에
        # 영구 저장하기로 하면서 PostgreSQL로 전환했다 — 아래 database_url이 실제 저장소다.
        # sqlite_file은 과거 로컬 데이터 이관(scripts/migrate_sqlite_to_postgres.py) 참조용으로만
        # 남겨둔다 — deps.get_database()는 더 이상 이 경로를 쓰지 않는다.
        self._sqlite_path_raw: str = os.getenv("SQLITE_PATH", "./data/sumeungil.db").strip()
        # PostgreSQL 접속 문자열(필수). 비어 있으면 db/postgres.py의 ensure_ready()가 연결
        # 실패로 처리해 리뷰·공유·로그인 등 DB 의존 기능만 비활성화된다(조회 위주 기능은
        # 그대로 동작 — sqlite.py 시절부터의 "저장소 장애로 부팅을 막지 않는다" 원칙 유지).
        # 로컬 예: postgresql://sumeungil:<비밀번호>@localhost:5433/sumeungil
        self.database_url: str = os.getenv("DATABASE_URL", "").strip()
        # 기능 킬스위치. 운영 중 남용이 발견되면 false 로 두고 재시작하면 쓰기·읽기 모두
        # 503 FEATURE_DISABLED 로 닫힌다(코드 배포 없이 차단).
        self.community_enabled: bool = (
            os.getenv("COMMUNITY_ENABLED", "true").strip().lower() != "false"
        )
        # device_id 1개 기준 분당 쓰기 상한(IP 기준 레이트리밋과 **별개**의 2차 방어선).
        self.review_write_per_min: int = int(os.getenv("REVIEW_WRITE_PER_MIN", "3"))
        self.share_write_per_min: int = int(os.getenv("SHARE_WRITE_PER_MIN", "5"))
        # 부록 R.14(2026-08-20) 좋아요 — 여기만 **계정(user_id) 기준**이다(하트는 로그인 필수).
        # 리뷰·공유보다 넉넉한 이유: 피드를 훑으며 여러 카드에 연속으로 누르는 것이 정상 사용이다.
        self.like_write_per_min: int = int(os.getenv("LIKE_WRITE_PER_MIN", "30"))
        # 좋아요 킬스위치. false 면 두 라우트가 503 FEATURE_DISABLED 이고, 피드는 like_count·
        # liked_by_me 를 계속 내려준다(값만 고정) — 프론트가 하트를 숨길 필요 없이 서버가 막는다.
        self.like_enabled: bool = os.getenv("LIKE_ENABLED", "true").strip().lower() != "false"
        # 서로 다른 기기 N 명이 신고하면 자동 숨김(운영자 없는 데모의 최소 안전장치).
        self.review_hide_report_threshold: int = int(
            os.getenv("REVIEW_HIDE_REPORT_THRESHOLD", "3")
        )
        # 공유 코스 payload 상한(바이트). nginx client_max_body_size(1m) 보다 훨씬 작다.
        self.share_payload_max_bytes: int = int(os.getenv("SHARE_PAYLOAD_MAX_BYTES", "32768"))

        # --- 부록 R 보존정책 (QA M-2, 2026-08-01) -----------------------------------
        # payload 를 해석하지 않고 32KB 까지 보관하는 저장소에 **상한이 하나도 없으면**
        # 산술적으로 IP 하나가 하루 900MB 를 채울 수 있다(UGC 20/분 × 32KB × 1440분).
        # 디스크가 차면 SQLite 쓰기가 실패하고 커뮤니티 전체가 503 이 된다 — 그래서 3중 상한.
        #
        # ① 기기당 보유 상한: 초과 시 **가장 오래된 내 공유부터 자동 삭제**한다(409 로 막지
        #    않는다 — 사용자는 "공유가 안 된다"는 실패보다 "옛날 링크가 정리된다"가 낫다).
        self.share_max_per_device: int = int(os.getenv("SHARE_MAX_PER_DEVICE", "20"))
        # ② 전체 row 상한: 초과 시 **오래되고 조회수 0인 것부터** 정리(아무도 안 본 것 우선).
        self.share_max_total: int = int(os.getenv("SHARE_MAX_TOTAL", "5000"))
        # ③ 보존 기간: 이보다 오래된 공유는 정리 대상. 0 이하면 기간 정리를 끈다.
        self.share_retention_days: int = int(os.getenv("SHARE_RETENTION_DAYS", "180"))
        # ②③ 의 유예: 최근 N일 안에 만들어졌고 조회수가 1 이상인 것은 지우지 않는다
        #    (지금 사람들이 보고 있는 링크를 용량 때문에 끊지 않기 위한 안전판).
        self.share_recent_view_grace_days: int = int(
            os.getenv("SHARE_RECENT_VIEW_GRACE_DAYS", "30")
        )
        # 정리 1회 트랜잭션에서 지우는 최대 행 수. 작게 유지해야 쓰기 락이 길어지지 않는다
        # (한 번에 수천 건을 지우면 그동안 다른 쓰기가 전부 대기한다).
        self.share_cleanup_batch: int = int(os.getenv("SHARE_CLEANUP_BATCH", "50"))
        # 주기 정리 간격(초, 기본 24h). 기동 직후 1회 + 이 간격마다 fire-and-forget 으로 돈다.
        self.share_cleanup_interval_sec: int = int(
            os.getenv("SHARE_CLEANUP_INTERVAL_SEC", str(24 * 60 * 60))
        )

        # --- 부록 T: 관리자(운영) 콘솔 (2026-08-01) ---
        #
        # !!! 기본값을 만들지 않는다 !!! `ADMIN_PASSWORD_HASH` 가 비어 있으면 관리자 기능이
        # **전부 비활성**이다(라우터 자체를 등록하지 않아 /api/v1/admin/* 은 404). 기본 비밀번호·
        # 백도어를 두는 순간 공개 서버에서 즉시 뚫린다 — 그래서 "설정 안 하면 없는 기능"이다.
        #
        # 값은 **평문이 아니라 scrypt 해시**다. 대표가 자기 PC 에서
        #   py backend/scripts/make_admin_hash.py
        # 를 돌려 나온 `scrypt$...` 문자열만 서버 .env 에 붙여넣는다(평문은 어디에도 남지 않는다).
        self.admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
        # 세션 토큰 HMAC 서명 키. 미설정이면 기존 JWT_SECRET_KEY → 그것도 없으면 비밀번호
        # 해시에서 파생한다(security/admin_auth.derive_signing_key 주석 참고).
        # 범용 서명 키. 관리자 세션 키의 폴백이자, 방문 집계(부록 X)의 IP 해싱 키 폴백이다.
        # 값 자체는 서버 .env 안에만 있고 응답·로그 어디에도 나가지 않는다.
        self.jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "").strip()
        self.admin_session_secret: str = (
            os.getenv("ADMIN_SESSION_SECRET", "").strip() or self.jwt_secret_key
        )
        # Mn-1(2026-08-10, 06-security-report-admin): 기본 8h → 4h. 서버측 세션 폐기 수단이
        # 없어(M-5 미조치) 탈취 시 노출 시간이 곧 TTL — 심사 전 완화 조치로 절반으로 줄였다.
        self.admin_session_ttl_sec: int = int(os.getenv("ADMIN_SESSION_TTL_SEC", str(4 * 60 * 60)))
        # 쿠키 Secure 속성. **기본 true** — HTTPS 가 아니면 브라우저가 쿠키를 저장하지 않는다.
        # 2026-08-09 HTTPS(https://sumeungil.co.kr) 적용 완료 — 예전에 여기 적혀 있던
        # "평문 공개 중이라 false 가 필요하다"는 안내는 더 이상 유효하지 않다.
        # **배포에서 false 로 내리지 말 것**: 세션 쿠키가 평문으로 흐른다.
        self.admin_cookie_secure: bool = (
            os.getenv("ADMIN_COOKIE_SECURE", "true").strip().lower() != "false"
        )
        # 관리자 표시 이름 목록(부록 V). 셋이 **같은 비밀번호를 공유**하므로 로그만으로는
        # "누가 지웠는지"를 알 수 없다. 로그인 시 본인 이름을 고르게 해 감사 로그에 남긴다.
        #   ADMIN_OPERATORS=지훈,인식,태준
        # 비워두면 이름 선택 자체가 없는 기존 동작 그대로다(무회귀).
        # 보안 경계가 아니라 **책임 추적 장치**다 — 비밀번호를 아는 사람은 서로의 이름을
        # 고를 수 있다. 악의 차단이 아니라 실수 되짚기가 목적이다.
        self.admin_operators: tuple[str, ...] = tuple(
            name.strip()
            for name in os.getenv("ADMIN_OPERATORS", "").split(",")
            if name.strip()
        )
        self.admin_cookie_name: str = os.getenv("ADMIN_COOKIE_NAME", "sumeungil_admin").strip()
        # 로그인 시도 상한(IP 기준, 분당). 브루트포스 1차 방어선 —
        # RATE_LIMIT_ENABLED 와 **무관하게 항상 동작**한다(로컬에서도 켜져 있다).
        self.admin_login_per_min: int = int(os.getenv("ADMIN_LOGIN_PER_MIN", "5"))

        # --- 구글 로그인 (2026-08-17, 대표 지시 — "임시로 붙이자", 운영 배포 대상) ---
        #
        # 데모 닉네임 로그인(§R.0, authStorage.ts)을 완전히 대체한다. ADMIN_PASSWORD_HASH와
        # 같은 원칙: **미설정이면 기능 전부 비활성**(라우터 미등록 → /api/v1/auth/* 404).
        # 기본값을 만들지 않는다 — Google Cloud Console에서 대표가 직접 발급한 클라이언트
        # ID/시크릿 없이는 아예 켜지지 않는다.
        #
        # 2026-08-17 갱신(QA m-1) — 아래 주석은 한때 맞았으나 지금은 stale하다. **계정
        # 테이블(users, db/sqlite.py schema_version 4)이 실제로 있고 이메일·표시이름을
        # 영구 저장한다** — 표시 이름을 바꿔도 재로그인 시 구글 원본으로 되돌아가는 문제
        # 때문에 도입됐다(대표 지적, user_repo.py). 세션 토큰은 admin_auth.py와 동일한
        # "서버가 서명한 만료시각" 방식(HMAC)이지만, users_id만 서명해 나르고 이메일·이름은
        # 토큰에 넣지 않는다 — 매 요청 DB에서 최신값을 읽는다 — security/user_auth.py 참고.
        self.google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        self.google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        # Google Cloud Console의 "승인된 리디렉션 URI"에 등록한 값과 문자 그대로 일치해야 한다.
        # 예: 로컬 http://localhost:8000/api/v1/auth/google/callback
        #     운영 https://sumeungil.co.kr/api/v1/auth/google/callback (nginx가 /api를 backend로 프록시)
        self.google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "").strip()

        # --- 카카오 로그인 (2026-08-17, 대표 지시 — 구글 옆에 간편로그인으로 추가) ---
        # 구글과 완전히 같은 원칙: 셋 다 있어야 카카오 로그인 라우트가 활성화된다
        # (security/user_auth.py의 kakao_enabled 참고). 카카오 개발자 콘솔에서
        # 대표가 직접 발급 — deploy/DEPLOY.md 카카오 절 참고.
        self.kakao_client_id: str = os.getenv("KAKAO_CLIENT_ID", "").strip()
        self.kakao_client_secret: str = os.getenv("KAKAO_CLIENT_SECRET", "").strip()
        self.kakao_redirect_uri: str = os.getenv("KAKAO_REDIRECT_URI", "").strip()

        # 로그인 팝업이 postMessage로 결과를 돌려줄 때 origin 검증에 쓴다(다른 탭이 위조한
        # 메시지를 프론트가 신뢰하지 않게). 로컬은 프론트/백엔드 포트가 달라 필수로 채워야 한다.
        # 구글·카카오 두 provider가 공유한다(프론트가 받는 postMessage 자체가 provider
        # 무관 공통 포맷이라 — api/auth.py의 _popup_close_html 참고).
        self.frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").strip()
        # 세션 서명 키 — 미설정이면 JWT_SECRET_KEY로 폴백(admin_session_secret과 동일 패턴).
        # admin과 **다른 라벨**로 키를 파생하므로(user_auth.py) 같은 시크릿을 공유해도 관리자
        # 세션 위조에 쓸 수 없다.
        self.user_session_secret: str = (
            os.getenv("USER_SESSION_SECRET", "").strip() or self.jwt_secret_key
        )
        # 2026-08-17 보안검토(M-2) — 원래 30일이었으나, 세션을 서버에서 강제로 끊을 수단이
        # 없는 무상태 서명 토큰이라 "탈취 시 노출 시간 = TTL"이다(admin 세션이 같은 이유로
        # 8h→4h로 줄인 전례, Mn-1). 개인정보(이메일)를 여는 /me가 걸린 세션이라 admin보다
        # 길게 둘 이유가 없어 최소 조치로 7일로 단축한다. 완전한 해법(로그아웃 즉시 전
        # 세션 무효화)은 users 테이블에 session_epoch 컬럼을 추가해야 하며 이번 스코프
        # 밖 — 후속 과제로 남긴다.
        # 2026-09-04(대표 C안: "짧게, 쓰면 연장") — 7일 고정 → **24시간 슬라이딩**. /me 가
        # 남은 수명이 절반 아래면 쿠키를 재발급하므로(api/auth.py) 매일 쓰는 사람은 계속
        # 로그인 상태, 하루 안 쓰면 풀린다. 탈취 시 노출 시간도 7일→1일로 준다.
        self.user_session_ttl_sec: int = int(
            os.getenv("USER_SESSION_TTL_SEC", str(24 * 60 * 60))
        )
        self.user_cookie_name: str = os.getenv("USER_COOKIE_NAME", "sumeungil_user").strip()
        self.user_cookie_secure: bool = (
            os.getenv("USER_COOKIE_SECURE", "true").strip().lower() != "false"
        )

        # --- 슬랙 5xx 알림 (2026-08-18, 대표 지시 — #알림-봇) ---
        # 웹훅 URL 이 없으면 main.py 가 미들웨어를 아예 등록하지 않는다(기본 꺼짐).
        # 그래서 로컬 개발/기존 검증 스크립트의 ASGI 스택은 이 기능 도입 전과 동일하다.
        # 이 값은 시크릿이다 — .env 에만 두고 로그로 출력하지 않는다(config 전체 원칙).
        self.slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        # 같은 (경로, 예외) 조합을 이 창 안에서 1회만 알린다. 0 이면 매번 알린다(권장하지 않음 —
        # 원천 장애 한 건에 슬랙이 수백 줄로 잠긴다).
        self.slack_alert_dedup_window_sec: int = int(
            os.getenv("SLACK_ALERT_DEDUP_WINDOW_SEC", "600")
        )

        # 아침 운영 요약을 보낼 시각(KST, 0~23). 웹훅이 없으면 루프를 돌리지 않는다.
        # -1 이면 요약 기능만 끈다(에러 알림은 그대로).
        self.slack_daily_summary_hour: int = int(os.getenv("SLACK_DAILY_SUMMARY_HOUR", "9"))
        # 슬래시 명령어(/서버상태 ·/문의) 서명 검증 키. slack.com/apps > Basic Information >
        # Signing Secret. **비우면 /api/v1/slack/* 라우터를 등록하지 않는다**(404) —
        # 관리자 라우터가 ADMIN_PASSWORD_HASH 없으면 사라지는 것과 같은 원칙이다.
        # 서명 검증 없이 이 엔드포인트를 열면 누구나 우리 운영 수치를 조회할 수 있다.
        self.slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "").strip()

        # 2026-08-22(대표 지시) — 아침 요약에 Prometheus 운영 지표(응답시간·에러율) 한 줄을
        # 추가하기 위한 조회 대상. 같은 docker 네트워크 안의 prometheus 컨테이너를 직접
        # 쿼리한다(nginx의 /prom/ Basic Auth 는 그라파나 등 **외부** 조회용이라 여긴 우회 —
        # 내부망이라 인증이 필요 없다). 비어 있으면(로컬 개발 기본) 이 부분만 조용히 생략된다.
        self.prometheus_base_url: str = os.getenv(
            "PROMETHEUS_BASE_URL", "http://prometheus:9090"
        ).strip()
        # 2026-08-23(대표 지시 "그라파나랑 운영대시보드랑 붙여야 한다") — 관리자 콘솔
        # "서버 상태" 탭의 "그라파나에서 자세히 보기" 링크용. 그라파나 자체를 임베드하지
        # 않는 이유는 deploy/SLACK-ALERTS.md·NAVER-MIGRATION.md 참고 — 외부 인스턴스라
        # iframe 임베드 시 그쪽 X-Frame-Options/인증 설정에 종속되고, 우리가 못 고친다.
        # 핵심 지표는 이 백엔드가 직접 Prometheus에서 읽어 콘솔 안에 표시하고, 상세 조회는
        # 링크로만 연결한다.
        self.grafana_url: str = os.getenv("GRAFANA_URL", "https://grafana.aitestbed.kr").strip()

    @property
    def sqlite_file(self) -> Path:
        """상대 경로는 **BACKEND_DIR 기준**으로 푼다(프로세스 cwd 에 의존하지 않게).

        - 컨테이너: WORKDIR=/app, BACKEND_DIR=/app → `/app/data/sumeungil.db` (볼륨 마운트 지점)
        - 로컬:     backend/ 어디서 uvicorn 을 띄우든 항상 `backend/data/sumeungil.db`
        cwd 기준으로 풀면 실행 위치에 따라 DB 파일이 여러 개 생겨 "리뷰가 사라졌다"로 보인다.
        """
        raw = Path(self._sqlite_path_raw)
        return raw if raw.is_absolute() else (BACKEND_DIR / raw).resolve()

    def validate_or_die(self) -> None:
        """필수 키 검증. 없으면 명확한 메시지와 함께 프로세스 종료."""
        if not self.public_data_api_key:
            sys.stderr.write(
                "\n[FATAL] 필수 환경변수 PUBLIC_DATA_API_KEY 가 설정되지 않았습니다.\n"
                f"        확인한 .env 경로: {self.env_source}\n"
                "        backend/.env 를 만들거나 상위 projects/sumeungil/.env 에 키를 두세요.\n"
                "        (fail-fast: 기본값으로 몰래 부팅하지 않습니다.)\n\n"
            )
            raise SystemExit(1)


# 모듈 로드 시 1회 생성 + 검증 → import 시점에 fail-fast
settings = Settings()
settings.validate_or_die()
