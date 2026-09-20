# 숨은길 backend (FastAPI) — Oracle Always Free ARM (VM.Standard.A1.Flex / aarch64) 배포용
#
# ARM64 메모:
#   python:3.12-slim 은 멀티아치 매니페스트(linux/amd64 + linux/arm64)라 ARM VM 에서 그대로
#   `docker compose build` 하면 arm64 레이어가 자동 선택된다. --platform 플래그 불필요.
#   (교차빌드로 x86 PC 에서 만들려면 buildx + --platform linux/arm64 가 필요하지만,
#    DEPLOY.md 방침은 "첫 빌드는 VM 위에서" 라 그럴 일이 없다.)
#
#   의존성(fastapi/uvicorn[standard]/httpx/pydantic)은 전부 aarch64 manylinux 휠이 있어
#   컴파일러가 필요 없다. 혹시 휠이 없는 버전으로 올려 빌드가 깨지면 DEPLOY.md 트러블슈팅 참고.

FROM python:3.12-slim

# .pyc 쓰지 않기 / stdout 즉시 flush(도커 로그가 밀리지 않게)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

WORKDIR /app

# 의존성 레이어 분리 — 코드만 바뀌면 pip install 을 다시 돌리지 않는다(ARM 빌드는 느리다).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 + 시드 데이터(app/spots/data/spots_seed.json 등).
# .dockerignore 가 .env·.venv·__pycache__·백업 시드(20MB+)를 제외한다.
COPY app ./app
# 운영 컨테이너에서 실행하는 관광지/축제 요약 배치. 같은 /app/data 볼륨에 결과를 저장한다.
COPY scripts/build_spot_summaries.py scripts/build_festival_summaries.py ./scripts/

# 비루트 실행 — 컨테이너 탈출 시 피해면 축소. 코드는 읽기 전용으로만 쓰므로 소유권 변경 불필요.
RUN useradd --create-home --uid 10001 appuser
# SQLite 데이터 디렉터리(부록 R) — named volume 이 이 경로에 마운트된다. 도커는 **이미지에 존재하는
# 디렉터리의 소유권을 빈 볼륨에 그대로 복사**하므로, 여기서 appuser 소유로 미리 만들어 두지 않으면
# 볼륨이 root:root 로 생성돼 비루트 프로세스가 DB 파일을 못 연다
# (실측: sqlite3.OperationalError "unable to open database file" → 커뮤니티 API 전부 503).
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

# 헬스체크는 curl 없이 표준 라이브러리로(슬림 이미지에 curl 미포함).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# !!! 워커는 반드시 1개 !!!
#   app/cache/memory.py 의 MemoryCache 와 app/middleware/rate_limit.py 의 카운터는 둘 다
#   **프로세스 인메모리**다. 워커를 늘리면
#     (1) 캐시가 워커 수만큼 쪼개져 원천 API 호출이 배로 늘고(무료 쿼터 소모),
#     (2) 레이트 리밋 실효 한도가 워커 수만큼 곱해지며,
#     (3) Ollama 동시 추론이 겹쳐 4 OCPU 가 즉시 포화된다.
#   멀티워커가 필요해지면 먼저 캐시/카운터를 Redis 로 옮겨야 한다(deps.py 교체 지점 주석 참고).
# --no-proxy-headers: uvicorn 자신도 기본값(proxy_headers=True, forwarded_allow_ips=
# "127.0.0.1")으로 X-Forwarded-For 를 읽어 request.client.host 를 덮어쓴다. 이게 켜져
# 있으면 앱 코드(rate_limit.py 의 extract_client_ip)가 "request.client.host = 진짜 소켓
# peer" 라고 믿는 전제가 loopback 접속에서 깨진다 — 즉 uvicorn 계층에서 이미 XFF 값으로
# 치환된 걸 앱이 다시 신뢰 판정하게 된다(보안 검증 2026-08-22, H-1). X-Forwarded-For 해석은
# 앱 코드 하나가만 하도록 우리가 직접 끈다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
