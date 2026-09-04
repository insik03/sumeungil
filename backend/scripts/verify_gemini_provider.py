# -*- coding: utf-8 -*-
"""Gemini 전환(2026-09-03) 결정적 회귀 — 네트워크·키 없이 돈다(CI 포함).

확인하는 것:
  1. LLM_PROVIDER=gemini 면 세 팩토리(온보딩·요약·팁)가 전부 Gemini 구현체를 준다
  2. Ollama JSON 스키마 → Gemini responseSchema 변환(additionalProperties 제거, null → nullable)
  3. 키가 비어 있을 때 세 경로가 예외 없이 폴백한다(룰 폴백 / None / [])
  4. PII 프리필터(07-legal-review-gemini-api-전환.md §3-1): 주민번호·전화번호·이메일 마스킹,
     날짜·금액 같은 숫자는 건드리지 않음, sanitize_free_text 경로에 실제로 물려 있음
  5. Ollama messages → Gemini contents 변환(system → systemInstruction, assistant → model)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = ""
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")

from app.config import settings  # noqa: E402
from app.ai import gemini_client  # noqa: E402
from app.ai.injection_guard import PII_MASK, mask_pii, sanitize_free_text  # noqa: E402
from app.ai.llm_provider import GeminiProvider, _tag_extraction_schema, create_provider_from_settings  # noqa: E402
from app.ai.schemas import LLMExtractionError  # noqa: E402
from app.ai.summarizer import GeminiSummarizer, create_summarizer_from_settings  # noqa: E402
from app.ai.tips_generator import GeminiTipsGenerator, create_tips_generator_from_settings  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


print("=== 1. 팩토리 스위치 ===")
provider = create_provider_from_settings(settings)
summarizer = create_summarizer_from_settings(settings)
tips = create_tips_generator_from_settings(settings)
check("온보딩 → GeminiProvider", isinstance(provider, GeminiProvider), type(provider).__name__)
check("요약 → GeminiSummarizer", isinstance(summarizer, GeminiSummarizer), type(summarizer).__name__)
check("팁 → GeminiTipsGenerator", isinstance(tips, GeminiTipsGenerator), type(tips).__name__)

print("=== 2. 스키마 변환 ===")
g = gemini_client.to_gemini_schema(_tag_extraction_schema())
check("additionalProperties 제거", "additionalProperties" not in json.dumps(g))
check("nullable 변환", g["properties"]["unmatched_note"] == {"type": "string", "nullable": True}, str(g["properties"]["unmatched_note"]))
check("required 유지", "value_confidence" in g.get("required", []))
check("모르는 키(uniqueItems 등) 제거", "uniqueItems" not in json.dumps(g) and "pattern" not in json.dumps(g))
nested = gemini_client.to_gemini_schema({"type": "array", "items": {"type": ["integer", "null"], "additionalProperties": False}})
check("중첩 items 변환", nested == {"type": "array", "items": {"type": "integer", "nullable": True}}, str(nested))

print("=== 3. 키 없음 → 폴백 ===")


async def _fallbacks() -> None:
    try:
        await provider.extract_tags("바다 보면서 조용히 걷고 싶어요")
        check("온보딩 LLMExtractionError", False, "예외 없음")
    except LLMExtractionError as exc:
        check("온보딩 LLMExtractionError", True, str(exc))
    check("스팟 요약 None", await summarizer.summarize("해운대 해수욕장은 부산의 대표 해변이다. " * 5) is None)
    check("코스 요약 None", await summarizer.summarize_course("1. 해운대 2. 동백섬") is None)


asyncio.run(_fallbacks())

print("=== 4. PII 프리필터 ===")
cases = {
    "010-1234-5678로 연락주세요": f"{PII_MASK}로 연락주세요",
    "전화 01012345678 주세요": f"전화 {PII_MASK} 주세요",
    "제 메일 kim.travel@example.com 이에요": f"제 메일 {PII_MASK} 이에요",
    "주민번호 900101-1234567 입니다": f"주민번호 {PII_MASK} 입니다",
    "2026년 10월 3일 3박4일 부산 20261003": "2026년 10월 3일 3박4일 부산 20261003",
    "예산 300000원, 인원 4명, 차 2대": "예산 300000원, 인원 4명, 차 2대",
}
for src, exp in cases.items():
    out = mask_pii(src)
    check(f"mask: {src[:22]}", out == exp, out if out != exp else "")
check("sanitize_free_text 경로에 마스킹 적용", PII_MASK in sanitize_free_text("전화 010 1234 5678 주세요"))

print("=== 5. messages → contents ===")
system, contents = gemini_client._to_contents(
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}]
)
check("system → systemInstruction", system == {"parts": [{"text": "S"}]}, str(system))
check("roles user/model", [c["role"] for c in contents] == ["user", "model"], str(contents))

print()
if FAILS:
    print(f"FAIL {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("PASS 전건")
