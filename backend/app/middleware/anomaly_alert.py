"""이상행동(브루트포스 정황) 슬랙 알림 미들웨어 (2026-08-22).

## 왜 필요한가
4차 보안 감사(DAST, 2026-08-19)가 X-Forwarded-For 스푸핑으로 IP 기준 레이트리밋을
우회할 수 있음을 실증했다(rate_limit.py 에서 이미 패치). 그런데 **패치 이후에도** 이
공격 시도 자체가 실제로 벌어지는지는 아무도 모른다 — 5xx 만 감시하는 기존
`ErrorAlertMiddleware` 는 401/429 를 보지 않는다(둘 다 "정상적으로 막은" 응답이라
에러가 아니다).

이 미들웨어는 **IP 단위가 아니라 서비스 전체 집계**로 401/429 를 센다. 공격자가 매
요청마다 다른 IP(스푸핑이든 실제 봇넷이든)를 쓰면 IP 기준 카운터는 절대 못 잡지만,
"짧은 시간에 401/429가 비정상적으로 몰린다"는 신호는 IP 와 무관하게 남는다.

## 설계 원칙 (ErrorAlertMiddleware·rate_limit.py 와 동일선상)
- 알림 전송 실패가 요청을 죽이지 않는다(슬랙 다운 시에도 응답은 그대로 나간다).
- 외부 의존성 추가 금지 — rate_limit.py 의 `SlidingWindowLimiter` 를 그대로 재사용한다
  (IP 별이 아니라 "401"·"429" 라는 고정 키 두 개만 쓰는 것으로 용도를 바꿨을 뿐이다).
- 웹훅이 없으면 등록 자체를 생략한다(main.py, 레이트리밋과 같은 원칙).
- 같은 신호를 반복해서 보내지 않는다 — 문턱을 넘은 뒤 `cooldown_sec` 동안은 재알림 안 함.
"""

from __future__ import annotations

import asyncio
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..services import slack_notify
from .rate_limit import SlidingWindowLimiter

logger = logging.getLogger("sumeungil.middleware.anomaly_alert")

_WATCHED_STATUSES: dict[int, str] = {
    401: "401(인증 실패)",
    429: "429(레이트리밋)",
}


class AnomalyAlertMiddleware(BaseHTTPMiddleware):
    """401/429 응답이 서비스 전체 기준으로 짧은 시간에 몰리면 슬랙으로 알린다.

    webhook_url 이 빈 값이면 main.py 가 애초에 등록하지 않는다(로컬 개발 기본 꺼짐).
    """

    def __init__(
        self,
        app,
        *,
        webhook_url: str,
        env: str,
        window_sec: int = 60,
        threshold_401: int = 20,
        threshold_429: int = 30,
        cooldown_sec: int = 600,
    ) -> None:
        super().__init__(app)
        self._url = webhook_url
        self._env = env
        self._counter = SlidingWindowLimiter(
            limits={"401": max(1, threshold_401), "429": max(1, threshold_429)},
            window_sec=window_sec,
        )
        self._cooldown = max(0, cooldown_sec)
        # 상태코드 -> 마지막 알림 전송 시각(monotonic)
        self._last_alert: dict[int, float] = {}
        self._tasks: set[asyncio.Task] = set()

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        label = _WATCHED_STATUSES.get(response.status_code)
        if label is not None:
            self._observe(response.status_code, label)
        return response

    # --- 내부 ---------------------------------------------------------------

    def _observe(self, status: int, label: str) -> None:
        try:
            # 클라이언트 키를 고정값으로 둬 "IP 별"이 아니라 "전체 집계"로 셈한다.
            decision = self._counter.check("global", str(status))
            if decision.allowed:
                return  # 아직 문턱 아래 — 정상 범위

            now = time.monotonic()
            last = self._last_alert.get(status)
            if last is not None and (now - last) < self._cooldown:
                return  # 이미 알렸고 아직 쿨다운 중

            self._last_alert[status] = now
            text = (
                f":rotating_light: [이상행동 감지] {self._env} — 최근 {self._counter.window_sec}초 동안 "
                f"{label} 응답이 {decision.limit}건 이상 발생했습니다.\n"
                "브루트포스·스캔 시도 정황일 수 있습니다 — 관리자 로그인/레이트리밋 로그를 확인하세요.\n"
                f"_같은 신호는 {self._cooldown // 60}분 동안 다시 알리지 않습니다._"
            )
            task = asyncio.create_task(self._post(text))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:  # noqa: BLE001
            logger.warning("이상행동 알림 준비 실패 — 무시하고 계속", exc_info=True)

    async def _post(self, text: str) -> None:
        await slack_notify.post(text, webhook_url=self._url)
