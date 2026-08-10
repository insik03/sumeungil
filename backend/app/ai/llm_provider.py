"""LLMProvider 추상 인터페이스 + OllamaProvider 구현.

08-interface-contract.md 부록B §B.4.1: "Provider 인터페이스 뒤에 Ollama 호출을 숨긴다.
상용 시 CloudProvider로 교체(엔드포인트 계약 불변)".

방어계층 4(02-ai-strategy.md §1.5): 이 Provider는 함수/툴 호출 권한을 전혀 요청하지
않는다 — 순수 text→JSON 변환. `tools`/`format` 외 다른 기능 파라미터를 추가하지 말 것.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from . import concierge_prompts, prompts
from .schemas import LLMExtractionError, RawConciergeExtraction, RawLLMExtraction

logger = logging.getLogger("sumeungil.ai.llm_provider")


class LLMProvider(ABC):
    """LLM 호출 추상화. backend는 이 인터페이스만 보고 analyze 엔드포인트를 짠다."""

    @abstractmethod
    async def extract_tags(self, free_text: str, chips: list[str] | None = None) -> RawLLMExtraction:
        """자유 텍스트에서 축별 태그(RawLLMExtraction, 아직 registry 미검증)를 추출한다.

        `chips`는 인터페이스 일관성을 위해 받지만 08 §1.7 설계상 LLM 프롬프트에는
        넣지 않는다(칩 선택분은 rule_fallback의 칩→태그 매핑이 별도로 담당하며
        LLM을 거치지 않는다). 실패 시 예외를 던지지 않고 값을 지어내면 안 되며,
        Ollama/네트워크/파싱 오류는 반드시 LLMExtractionError로 승격해 던진다
        (호출부가 §B.3 룰 폴백으로 전환할 수 있도록).
        """
        raise NotImplementedError

    async def extract_concierge_understanding(self, free_text: str) -> RawConciergeExtraction:
        """부록 N.10(2026-07-30) — 컨시어지 전용 통합 이해(태그+intent+region_text+wants_*)를
        LLM 호출 1회로 받는다. `POST /api/v1/concierge/ask`의 ① 조건 해석이 `extract_tags` 대신
        이 메서드를 쓴다(대체이지 추가 호출이 아니다).

        **abstractmethod 가 아니다** — 기본 구현은 미지원을 뜻하는 `LLMExtractionError`를
        던진다. 이렇게 두는 이유는 하위호환: `extract_tags`만 구현한 기존/테스트용 Provider가
        이 메서드를 몰라도 계속 유효한 구현체로 남는다(추상 메서드였다면 전부 깨졌을 것).
        호출부(`app.ai.concierge_understanding`)는 이 예외를 룰 폴백 신호로 받는다 — 실제 로컬
        Ollama 동작은 `OllamaProvider`가 override 한다.
        """
        raise LLMExtractionError("extract_concierge_understanding not supported by this provider")


class OllamaProvider(LLMProvider):
    """로컬 Ollama `POST /api/chat` 구현체.

    08 부록B §B.0/B.4: `http://localhost:11434/api/chat`, `format:"json"`,
    `options.temperature≈0.1`, `stream:false`. 모델 태그는 착수 시 `ollama list`로
    실측 확인함(U-1) — 아래 `docs/` 참고. gemma4:12b 확인됨(2026-07-24,
    `ollama_tags_verified.txt` 참고).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_sec: float = 45.0,
        temperature: float = 0.1,
        concierge_understanding_timeout_sec: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_sec = timeout_sec
        self._temperature = temperature
        # 부록 N.10: 컨시어지 통합 이해도 같은 로컬 모델을 재사용하되(신규 키·비용 0), 사용자가
        # 화면에서 기다리는 경로라 온보딩과 별도로 타임아웃을 튜닝할 수 있게 분리한다.
        self._concierge_understanding_timeout_sec = concierge_understanding_timeout_sec or timeout_sec

    async def extract_tags(self, free_text: str, chips: list[str] | None = None) -> RawLLMExtraction:
        messages, sanitized = prompts.build_messages(free_text)

        payload = {
            "model": self._model,
            "format": "json",
            "stream": False,
            "options": {"temperature": self._temperature},
            "messages": messages,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            logger.warning("ollama 호출 실패: %s", exc)
            raise LLMExtractionError(f"ollama request failed: {exc}") from exc

        if resp.status_code != 200:
            logger.warning("ollama 비정상 상태코드 %s", resp.status_code)
            raise LLMExtractionError(f"ollama status {resp.status_code}")

        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("ollama 응답 envelope 파싱 실패: %s", exc)
            raise LLMExtractionError("ollama response envelope malformed") from exc

        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            # format:"json" 강제에도 불구하고 파싱 실패 시 → §B.3 룰 폴백 대상(정상 경로)
            logger.warning("ollama content가 유효 JSON이 아님(길이=%d): %s", len(content), exc)
            raise LLMExtractionError("ollama content is not valid json") from exc

        if not isinstance(raw, dict):
            raise LLMExtractionError(f"ollama content json이 object가 아님: {type(raw)}")

        try:
            return RawLLMExtraction.model_validate(raw)
        except ValidationError as exc:
            logger.warning("ollama JSON이 예상 구조와 다름: %s", exc)
            raise LLMExtractionError("ollama content failed schema validation") from exc

    async def extract_concierge_understanding(self, free_text: str) -> RawConciergeExtraction:
        """부록 N.10 — `extract_tags`와 완전히 같은 HTTP 호출 패턴, 프롬프트/스키마만 다르다
        (`concierge_prompts.py` + `RawConciergeExtraction`). 온보딩 `extract_tags`는 이 메서드가
        생겨도 한 글자도 안 바뀐다(별도 메서드).
        """
        messages, _sanitized = concierge_prompts.build_understanding_messages(free_text)

        payload = {
            "model": self._model,
            "format": "json",
            "stream": False,
            "options": {"temperature": self._temperature},
            "messages": messages,
        }

        try:
            async with httpx.AsyncClient(timeout=self._concierge_understanding_timeout_sec) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            logger.warning("ollama(concierge understanding) 호출 실패: %s", exc)
            raise LLMExtractionError(f"ollama request failed: {exc}") from exc

        if resp.status_code != 200:
            logger.warning("ollama(concierge understanding) 비정상 상태코드 %s", resp.status_code)
            raise LLMExtractionError(f"ollama status {resp.status_code}")

        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("ollama(concierge understanding) 응답 envelope 파싱 실패: %s", exc)
            raise LLMExtractionError("ollama response envelope malformed") from exc

        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "ollama(concierge understanding) content가 유효 JSON이 아님(길이=%d): %s",
                len(content), exc,
            )
            raise LLMExtractionError("ollama content is not valid json") from exc

        if not isinstance(raw, dict):
            raise LLMExtractionError(f"ollama content json이 object가 아님: {type(raw)}")

        try:
            return RawConciergeExtraction.model_validate(raw)
        except ValidationError as exc:
            logger.warning("ollama(concierge understanding) JSON이 예상 구조와 다름: %s", exc)
            raise LLMExtractionError("ollama content failed schema validation") from exc


def create_provider_from_settings(settings) -> LLMProvider:  # noqa: ANN001 (app.config.Settings)
    """`app.config.settings`로부터 기본 OllamaProvider를 만든다.

    backend deps.py에서 `get_llm_provider()`로 감싸 싱글턴화해 쓰면 된다:
        from app.ai.llm_provider import create_provider_from_settings
        @lru_cache(maxsize=1)
        def get_llm_provider(): return create_provider_from_settings(settings)
    """
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_sec=settings.ollama_timeout_sec,
        temperature=settings.ollama_temperature,
        concierge_understanding_timeout_sec=getattr(
            settings, "concierge_understanding_timeout_sec", None
        ),
    )
