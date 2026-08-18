"""5xx 슬랙 알림 미들웨어 (2026-08-18, 대표 지시 — #알림-봇).

## 왜 미들웨어인가
`@app.exception_handler` 는 **라우터에서 올라온 예외만** 본다. 안쪽 미들웨어
(레이트리밋·방문집계)에서 터진 예외나 라우터가 직접 만들어 반환한 500 응답은
그 훅에 걸리지 않는다. 요청을 감싸는 미들웨어로 두면 그 셋을 한 곳에서 잡는다.

## 설계 원칙 네 가지

**1. 알림 실패가 요청을 죽이지 않는다.**
VisitLogMiddleware 와 같은 원칙이다. 슬랙이 죽어도, 웹훅이 만료돼도, 사용자가 보는
응답은 그대로 나가야 한다. 전송은 별도 태스크로 던지고(await 하지 않음) 실패는
로그 한 줄로 끝낸다. 예외는 원래대로 다시 raise 해서 Starlette 가 처리하게 둔다.

**2. 쿼리스트링을 보내지 않는다 — 경로만 보낸다.**
`/api/v1/...?serviceKey=<실키>` 를 그대로 붙이면 공공데이터 키가 슬랙에 영구히 남는다.
main.py 가 httpx 로거를 WARNING 으로 올려 놓은 것과 **완전히 같은 이유**다.
(그 주석에 "상용 로그 수집/배포 환경에서 이 누출은 Critical" 이라고 적혀 있다.)

**3. 그래도 예외 메시지는 한 번 더 세탁한다.**
httpx 계열 예외는 메시지 안에 요청 URL 을 통째로 넣는다 — 즉 경로만 보내도
`str(exc)` 경로로 키가 새어나갈 수 있다. 그래서 serviceKey·token·secret 류 파라미터
값을 `***` 로 치환한 뒤 보낸다. 새 시크릿 파라미터가 생기면 _SECRET_PARAM_RE 에 추가할 것.

**4. 같은 에러를 반복해 보내지 않는다.**
5xx 는 몰려서 터진다(원천 장애 하나에 초당 수십 건). `(경로, 예외이름)` 단위로
창(기본 10분) 안에서 1회만 보낸다. 이 가드가 없으면 장애 1건에 슬랙이 수백 줄로 잠기고
무료 워크스페이스의 90일 히스토리를 그것만으로 태운다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import traceback
from pathlib import Path

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sumeungil.middleware.error_alert")

_EXC_MSG_MAX = 400
# 호출 경로에 적을 우리 코드 프레임 최대 개수. 슬랙 메시지 상한(4000자)에 여유를 둔다.
_TRAIL_MAX_FRAMES = 6

# 우리 코드의 뿌리. 이 미들웨어는 app/middleware/ 에 있으므로 두 단계 위가 app/ 다.
_APP_ROOT = Path(__file__).resolve().parent.parent

# 값이 시크릿인 쿼리 파라미터/키 이름. `이름=값` 과 `"이름": "값"` 두 형태를 함께 잡는다.
_SECRET_PARAM_RE = re.compile(
    r"(?i)(serviceKey|api[_-]?key|app[_-]?key|access[_-]?token|refresh[_-]?token|token"
    r"|client[_-]?secret|secret|password|passwd|pwd|authorization)"
    # 이름 뒤에 닫는 따옴표가 올 수 있다: `serviceKey=값` 과 `"password": "값"` 을 함께 잡는다.
    r"([\"']?\s*[=:]\s*[\"']?)"
    r"([^&\s\"'<>]{4,})"
)


def _scrub(text: str) -> str:
    """시크릿으로 보이는 값을 *** 로 가린다. 알림에 나가는 모든 문자열에 적용한다."""
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def _locate(exc: BaseException) -> tuple[str, str]:
    """예외가 터진 **우리 코드** 위치와 호출 경로를 뽑는다.

    반환: (`"congestion_service.py Line 142"`, `"api/congestion.py:88 → services/...:142"`)

    ## 왜 마지막 프레임을 쓰지 않는가
    트레이스백의 맨 끝은 대개 라이브러리 내부다(httpx 의 소켓 코드, pydantic 검증기 등).
    "Line 219 of httpcore/_sync/connection.py" 를 받아도 우리가 고칠 데는 아니다.
    그래서 `app/` 아래에 있는 프레임만 남기고, 그중 **가장 깊은 것**을 터진 지점으로 본다.

    우리 코드 프레임이 하나도 없으면(미들웨어 밖·라이브러리 단독 실패) 맨 끝 프레임을
    쓰되 파일명만 적는다 — 그때는 호출 경로가 더 중요한 단서다.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "위치 불명 (트레이스백 없음)", ""

    ours = []
    for f in frames:
        try:
            rel = Path(f.filename).resolve().relative_to(_APP_ROOT)
        except (ValueError, OSError):
            continue
        ours.append((rel.as_posix(), f.lineno, f.name))

    if ours:
        rel, lineno, _ = ours[-1]
        where = f"{Path(rel).name} Line {lineno}"
        trail = " → ".join(f"{r}:{n}" for r, n, _ in ours[-_TRAIL_MAX_FRAMES:])
    else:
        last = frames[-1]
        where = f"{Path(last.filename).name} Line {last.lineno} (라이브러리 내부)"
        trail = " → ".join(
            f"{Path(f.filename).name}:{f.lineno}" for f in frames[-_TRAIL_MAX_FRAMES:]
        )
    return where, trail


class ErrorAlertMiddleware(BaseHTTPMiddleware):
    """5xx 응답과 미처리 예외를 슬랙 웹훅으로 알린다.

    webhook_url 이 빈 값이면 main.py 가 애초에 등록하지 않는다(로컬 개발 기본 꺼짐).
    """

    def __init__(
        self,
        app,
        *,
        webhook_url: str,
        env: str,
        dedup_window_sec: int = 600,
        max_keys: int = 500,
    ) -> None:
        super().__init__(app)
        self._url = webhook_url
        self._env = env
        self._window = max(0, dedup_window_sec)
        self._max_keys = max_keys
        # (경로, 예외이름) -> 마지막 전송 시각(monotonic)
        self._seen: dict[tuple[str, str], float] = {}
        # create_task 결과를 안 붙들면 GC 가 태스크를 거둬가 전송이 조용히 사라진다.
        self._tasks: set[asyncio.Task] = set()

    async def dispatch(self, request: Request, call_next):
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            self._maybe_alert(request, exc=exc, status=500)
            raise  # 응답 생성은 Starlette 몫 — 알림은 부가 기능이다.
        if response.status_code >= 500:
            self._maybe_alert(request, exc=None, status=response.status_code)
        return response

    # --- 내부 ---------------------------------------------------------------

    def _maybe_alert(self, request: Request, *, exc: BaseException | None, status: int) -> None:
        """중복 창을 확인하고 전송 태스크를 띄운다. 어떤 이유로도 예외를 밖으로 내지 않는다."""
        try:
            path = request.url.path  # 쿼리스트링은 의도적으로 버린다(원칙 2)
            kind = type(exc).__name__ if exc is not None else f"HTTP{status}"
            key = (path, kind)

            now = time.monotonic()
            last = self._seen.get(key)
            if last is not None and (now - last) < self._window:
                return

            self._prune(now)
            self._seen[key] = now

            text = self._build_text(request, exc, status, path)
            task = asyncio.create_task(self._post(text))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:  # noqa: BLE001
            logger.warning("에러 알림 준비 실패 — 무시하고 계속", exc_info=True)

    def _prune(self, now: float) -> None:
        """만료 항목을 치우고, 그래도 넘치면 오래된 것부터 버린다(무제한 증가 방지)."""
        if len(self._seen) < self._max_keys:
            expired = [k for k, t in self._seen.items() if (now - t) >= self._window]
            for k in expired:
                self._seen.pop(k, None)
            return
        for k, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[: self._max_keys // 2]:
            self._seen.pop(k, None)

    def _build_text(
        self, request: Request, exc: BaseException | None, status: int, path: str
    ) -> str:
        lines = [
            f"🔥 서버에서 에러가 발생했습니다. uri: {request.method} {path}",
        ]
        if exc is not None:
            where, trail = _locate(exc)
            lines.append(f"Exception: {type(exc).__name__}")
            lines.append(f"Location: {where}  (환경: {self._env})")
            msg = _scrub(str(exc)) or "(메시지 없음)"
            lines.append(f"```{msg[:_EXC_MSG_MAX]}```")
            if trail:
                lines.append(f"호출 경로: {_scrub(trail)}")
        else:
            # 라우터가 직접 만든 5xx — 트레이스백이 없다. 서버 로그를 봐야 원인이 나온다.
            lines.append("예외 없이 반환된 5xx 입니다 — 서버 로그를 확인하세요.")

        if self._window >= 60:
            lines.append(f"_같은 경로·예외는 {self._window // 60}분 동안 다시 알리지 않습니다._")
        return "\n".join(lines)

    async def _post(self, text: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._url, json={"text": text, "unfurl_links": False}
                )
            if resp.status_code != 200:
                # 본문에 웹훅 URL 이 들어가지 않도록 상태코드만 남긴다.
                logger.warning("슬랙 에러 알림 전송 실패 — HTTP %s", resp.status_code)
        except Exception:  # noqa: BLE001
            logger.warning("슬랙 에러 알림 전송 실패 — 무시하고 계속", exc_info=True)
