"""슬랙 슬래시 명령어 서명 검증 실측 (2026-08-18).

이 엔드포인트는 **인터넷에 열려 있고 인증 쿠키를 쓸 수 없다**(슬랙 서버가 호출한다).
서명 검증이 유일한 방어선이므로, 아래 8개 항목이 전부 PASS 여야 운영에 올린다.

  1. 올바른 서명 → 200 + 기대한 내용
  2. 서명 헤더 없음 → 401
  3. 서명이 틀림 → 401
  4. 서명은 맞지만 타임스탬프가 오래됨(재전송) → 401
  5. 서명을 만든 뒤 본문을 바꿈(개조) → 401
  6. 서명 키가 비어 있으면 전부 거부(fail-closed)
  7. 모르는 명령어 → 도움말(500 아님)
  8. **응답에 관리자 콘솔 경로가 들어가지 않는다** (경로 비밀 유지 결정, 2026-08-17)

DB·캐시는 가짜로 주입한다 — 검증 대상은 서명과 응답 형태이고, SQL 은 관리자 콘솔이
이미 실사용으로 검증하고 있다.

실행:
    cd backend
    .venv/Scripts/python.exe scripts/verify_slack_commands.py     (Windows)
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import slack as slack_api  # noqa: E402
from app.config import settings  # noqa: E402
from app.deps import (  # noqa: E402
    get_cache,
    get_congestion_repository,
    get_database,
)

SECRET = "test_signing_secret_0123456789"
# 관리자 콘솔 실제 경로(2026-08-17 변경). 응답에 이 문자열이 나타나면 실패다.
ADMIN_PATH = "ops-37878f1b71"


# --- 가짜 의존성 -----------------------------------------------------------------


class FakeCache:
    async def health(self) -> bool:
        return True


class FakeRepo:
    def last_upstream_status(self) -> str:
        return "ok"


class FakeDB:
    """aread 는 fn 을 실행하지 않고 미리 정한 값을 돌려준다(SQL 은 검증 대상이 아니다)."""

    payload: object = None

    async def aread(self, fn):  # noqa: ANN001
        return self.payload


FAKE_DB = FakeDB()

app = FastAPI()
app.include_router(slack_api.router)
app.dependency_overrides[get_database] = lambda: FAKE_DB
app.dependency_overrides[get_cache] = lambda: FakeCache()
app.dependency_overrides[get_congestion_repository] = lambda: FakeRepo()
client = TestClient(app)

STATS = {
    "reviews_total": 34,
    "reviews_hidden": 1,
    "reviews_today": 0,
    "reports_pending": 0,
    "reports_total": 2,
    "courses_total": 12,
    "courses_hidden": 0,
    "inquiries_total": 15,
    "inquiries_new": 2,
}
TRAFFIC = {"today_visitors": 7, "today_hits": 51, "daily": []}


def sign(body: str, ts: str) -> str:
    base = f"v0:{ts}:{body}".encode()
    return "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()


def call(command: str, *, ts: str | None = None, sig: str | None = None, body_extra: str = ""):
    body = urlencode({"command": command, "user_name": "insik03"}) + body_extra
    ts = ts or str(int(time.time()))
    return client.post(
        "/api/v1/slack/commands",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            **({"X-Slack-Signature": sig} if sig is not None else {"X-Slack-Signature": sign(body, ts)}),
        },
    )


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, note: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + note) if note else ''}")
        if not cond:
            failures.append(name)

    settings.slack_signing_secret = SECRET

    # --- 1) 정상 경로 -----------------------------------------------------
    print("\n[1] 올바른 서명 → 정상 응답")
    FAKE_DB.payload = TRAFFIC
    r = call("/서버상태")
    check("200 응답", r.status_code == 200, f"status={r.status_code}")
    body = r.json()
    check("ephemeral 응답(요청자만 보임)", body.get("response_type") == "ephemeral")
    check("서버 상태 문구", "서버 상태" in body.get("text", ""))
    check("오늘 방문 집계 포함", "7명" in body.get("text", ""))

    FAKE_DB.payload = STATS
    r = call("/문의")
    check("/문의 200", r.status_code == 200, f"status={r.status_code}")
    check("미답변 건수 포함", "미답변 2건" in r.json().get("text", ""))

    # --- 2~5) 서명 공격 ---------------------------------------------------
    print("\n[2] 서명 헤더 없음 → 401")
    body = urlencode({"command": "/문의"})
    r = client.post(
        "/api/v1/slack/commands",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(int(time.time())),
        },
    )
    check("401", r.status_code == 401, f"status={r.status_code}")

    print("\n[3] 서명이 틀림 → 401")
    r = call("/문의", sig="v0=" + "0" * 64)
    check("401", r.status_code == 401, f"status={r.status_code}")

    print("\n[4] 타임스탬프가 오래됨(재전송) → 401")
    old_ts = str(int(time.time()) - 60 * 10)  # 10분 전
    body = urlencode({"command": "/문의", "user_name": "insik03"})
    r = client.post(
        "/api/v1/slack/commands",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": old_ts,
            "X-Slack-Signature": sign(body, old_ts),  # 서명 자체는 유효
        },
    )
    check("401 (서명이 유효해도 거부)", r.status_code == 401, f"status={r.status_code}")

    print("\n[5] 서명 후 본문 개조 → 401")
    ts = str(int(time.time()))
    orig = urlencode({"command": "/문의", "user_name": "insik03"})
    good_sig = sign(orig, ts)
    r = client.post(
        "/api/v1/slack/commands",
        content=orig + "&injected=1",  # 서명은 그대로, 본문만 바꿈
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": good_sig,
        },
    )
    check("401", r.status_code == 401, f"status={r.status_code}")

    # --- 6) fail-closed ---------------------------------------------------
    print("\n[6] 서명 키가 비어 있으면 전부 거부(fail-closed)")
    settings.slack_signing_secret = ""
    r = call("/문의", sig="v0=" + "a" * 64)
    check("401", r.status_code == 401, f"status={r.status_code}")
    settings.slack_signing_secret = SECRET

    # --- 7) 모르는 명령어 --------------------------------------------------
    print("\n[7] 모르는 명령어 → 도움말")
    r = call("/없는명령")
    check("200 (500 아님)", r.status_code == 200, f"status={r.status_code}")
    check("도움말 안내", "쓸 수 있는 명령어" in r.json().get("text", ""))

    # --- 8) 관리자 경로 유출 -----------------------------------------------
    print("\n[8] 응답에 관리자 콘솔 경로가 없다")
    FAKE_DB.payload = STATS
    texts = [call("/문의").json()["text"]]
    FAKE_DB.payload = TRAFFIC
    texts.append(call("/서버상태").json()["text"])
    texts.append(call("/없는명령").json()["text"])
    joined = "\n".join(texts)
    check("실제 관리자 경로 문자열 없음", ADMIN_PATH not in joined)
    check("'/admin' 경로도 노출 안 함", "/admin" not in joined)

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ 실패 {len(failures)}건: {', '.join(failures)}")
        return 1
    print("✅ 전 항목 PASS — 운영 배포 가능")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
