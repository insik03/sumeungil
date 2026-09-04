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

import logging
from typing import Any

import httpx

logger = logging.getLogger("sumeungil.ai.gemini")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    """네트워크·상태코드·응답 형식 오류. 호출부가 폴백으로 전환할 수 있게 한 종류로 묶는다."""


def to_gemini_schema(schema: Any) -> Any:
    """Ollama/JSON Schema → Gemini responseSchema.

    Gemini 는 OpenAPI 3.0 부분집합만 받는다: `additionalProperties` 는 거부하고, nullable 은
    `"type": ["string","null"]` 대신 `"nullable": true` 로 써야 한다. 그 두 가지만 바꾸고
    나머지(type/properties/required/enum/items/description)는 그대로 통과시킨다.
    """
    if isinstance(schema, list):
        return [to_gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in value:
                out["nullable"] = True
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
) -> str:
    """messages 를 보내고 content 문자열을 돌려준다. 실패는 전부 GeminiError."""
    if not api_key:
        raise GeminiError("GEMINI_API_KEY 미설정")

    system, contents = _to_contents(messages)
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        # Qwen thinking 을 껐던 것과 같은 이유 — 짧은 구조화 응답에 사고 토큰은 지연·비용만 더한다.
        "thinkingConfig": {"thinkingBudget": 0},
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
    except httpx.HTTPError as exc:
        raise GeminiError(f"gemini request failed: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        # 본문에 사용자 입력이 되돌아올 수 있어 상태코드만 남긴다.
        raise GeminiError(f"gemini status {resp.status_code}")

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
