"""Google Gemini `generateContent` 얇은 클라이언트 (2026-09-03, 대표 결정 "전부 제미나이로").

왜 SDK 대신 REST인가: 의존성 하나 안 늘리고(httpx 는 이미 있음), 기존 Ollama `/api/chat`
호출부 세 곳(온보딩 태그추출 · 요약 · 팁)이 전부 "messages + 선택적 JSON 스키마 → content
문자열" 모양이라, 같은 모양의 함수 하나면 세 클래스가 전송부만 바꿔 끼울 수 있다.

호출 규약 (Ollama 와 동일하게 맞춤):
  - messages: [{"role": "system"|"user"|"assistant", "content": str}]
  - response_schema: Ollama `format` 에 넣던 JSON Schema 그대로 — Gemini 가 못 받는 키
    (`additionalProperties`, `["string","null"]` 식 type 배열)는 여기서 변환한다.
  - 반환: 모델이 낸 텍스트(content). 오류는 전부 GeminiError 로 승격 — 호출부가 각자
    "룰 폴백 / 요약 생략 / 정적 팁" 으로 처리한다(값을 지어내지 않는다).

보안 규약 (기존 계층 그대로):
  - 툴/함수 호출을 부여하지 않는다. 시스템 프롬프트는 `systemInstruction` 로만 전달.
  - API 키는 헤더(`x-goog-api-key`)로만 보내고 URL·로그에 남기지 않는다.
  - 입력 텍스트는 로그에 남기지 않는다(오류 유형만).
  - 사용자 자유서술은 호출 전에 injection_guard.sanitize_free_text 가 PII 마스킹까지 끝낸
    뒤 들어온다(07-legal-review-gemini-api-전환.md §3-1).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger("sumeungil.ai.gemini")

# --- 한도(429) 관측 (2026-09-07, n8n 감시용) ------------------------------------------
# 무료 티어 하루 20회 한도(#99)에 걸리면 AI 기능이 조용히 폴백돼 아무도 모른다. 여기서 429 발생
# 시각을 프로세스 메모리에 남기고 /api/v1/health/llm 이 읽는다 — 외부 감시(n8n)가 폴링해 슬랙으로
# 알린다. 재시작하면 0 부터 (영속화 불필요: "지금 막혀 있나"만 알면 된다).
_QUOTA_WINDOW_SEC = 24 * 60 * 60
_quota_hits: deque[float] = deque()
_last_success_ts: float | None = None


def _record_quota_hit(now: float | None = None) -> None:
    ts = time.time() if now is None else now
    _quota_hits.append(ts)
    while _quota_hits and ts - _quota_hits[0] > _QUOTA_WINDOW_SEC:
        _quota_hits.popleft()


def _record_success(now: float | None = None) -> None:
    global _last_success_ts
    _last_success_ts = time.time() if now is None else now


def quota_status(now: float | None = None) -> dict[str, Any]:
    """최근 1시간/24시간 429 횟수와 마지막 429·성공 시각(epoch). 개인정보·키 없음."""
    ts = time.time() if now is None else now
    while _quota_hits and ts - _quota_hits[0] > _QUOTA_WINDOW_SEC:
        _quota_hits.popleft()
    last_hour = sum(1 for t in _quota_hits if ts - t <= 3600)
    return {
        "quota_429_last_hour": last_hour,
        "quota_429_last_24h": len(_quota_hits),
        "last_429_ts": _quota_hits[-1] if _quota_hits else None,
        "last_success_ts": _last_success_ts,
    }

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    """네트워크·상태코드·응답 형식 오류. 호출부가 폴백으로 전환할 수 있게 한 종류로 묶는다."""


# Gemini responseSchema 가 받는 키(OpenAPI 3.0 부분집합). 목록 밖 키(`additionalProperties`,
# `uniqueItems`, `pattern`, `default` …)는 400 "Unknown name" 으로 요청 전체가 거부된다 —
# 2026-09-03 운영 실측(`uniqueItems` 때문에 첫 배포가 전부 400). 그래서 통과 목록으로 거른다.
_GEMINI_SCHEMA_KEYS = frozenset({
    "type", "format", "description", "nullable", "enum", "items", "properties", "required",
    "minItems", "maxItems", "minimum", "maximum", "anyOf", "title", "propertyOrdering",
})


def to_gemini_schema(schema: Any) -> Any:
    """Ollama/JSON Schema → Gemini responseSchema.

    Gemini 는 OpenAPI 3.0 부분집합만 받는다: 모르는 키는 400 으로 거부하고, nullable 은
    `"type": ["string","null"]` 대신 `"nullable": true` 로 써야 한다. `_GEMINI_SCHEMA_KEYS`
    에 있는 키만 남기고 type 배열을 변환한다. 검증이 헐거워지는 만큼은 호출부의 pydantic
    재검증(RawLLMExtraction 등, 방어계층 5)이 그대로 막는다.
    """
    if isinstance(schema, list):
        return [to_gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in value:
                out["nullable"] = True
            continue
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            # 프로퍼티 **이름**은 스키마 키워드가 아니다 — 이름은 그대로 두고 값만 변환한다.
            out[key] = {name: to_gemini_schema(sub) for name, sub in value.items()}
            continue
        out[key] = to_gemini_schema(value)
    return out


def _to_contents(messages: list[dict[str, str]]) -> tuple[dict | None, list[dict]]:
    """Ollama 식 messages → (systemInstruction, contents). system 은 한 덩어리로 합친다."""
    system_parts: list[str] = []
    contents: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        if role == "system":
            system_parts.append(text)
            continue
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
    system = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    return system, contents


async def chat(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    timeout_sec: float,
    temperature: float = 0.0,
    response_schema: dict | None = None,
    max_output_tokens: int = 1024,
    thinking_level: str = "minimal",
) -> str:
    """messages 를 보내고 content 문자열을 돌려준다. 실패는 전부 GeminiError."""
    if not api_key:
        raise GeminiError("GEMINI_API_KEY 미설정")

    system, contents = _to_contents(messages)
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        # Qwen thinking 을 껐던 것과 같은 이유 — 짧은 구조화 응답에 사고 토큰은 지연·비용만 더한다.
        # 2026-09-03 운영 실측(gemini-3.6-flash): `thinkingBudget: 0` 은 400, thinkingLevel 을 안 주면
        # 사고 토큰 541개를 쓰며 32초, `thinkingLevel: "minimal"` 이면 2.1초에 같은 JSON. Gemini 3
        # 계열은 budget 대신 level 이다.
        "thinkingConfig": {"thinkingLevel": thinking_level},
    }
    if response_schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = to_gemini_schema(response_schema)

    body: dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
    if system is not None:
        body["systemInstruction"] = system

    url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
            if resp.status_code in (429, 503):
                # 운영 실측에서 "high demand" 503 이 간헐적으로 온다 — 짧게 한 번만 재시도.
                # (폴백이 있으니 더 끈질기게 붙잡지 않는다.)
                await asyncio.sleep(0.8)
                resp = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
    except httpx.HTTPError as exc:
        raise GeminiError(f"gemini request failed: {type(exc).__name__}") from exc

    if resp.status_code == 429:
        _record_quota_hit()
    if resp.status_code != 200:
        # 본문에 사용자 입력이 되돌아올 수 있어 상태코드만 남긴다.
        raise GeminiError(f"gemini status {resp.status_code}")
    _record_success()

    try:
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            # 안전필터 차단(promptFeedback.blockReason) 등 — 지어내지 않고 폴백.
            raise GeminiError(f"gemini no candidates ({(data.get('promptFeedback') or {}).get('blockReason', 'unknown')})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except GeminiError:
        raise
    except (ValueError, AttributeError, TypeError) as exc:
        raise GeminiError("gemini response envelope malformed") from exc

    if not text:
        raise GeminiError("gemini empty content")
    return text
