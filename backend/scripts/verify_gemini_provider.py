# -*- coding: utf-8 -*-
"""Hybrid routing and Gemini schema/PII regression; no network calls."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch
import httpx
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # CP949 콘솔에서 em dash 출력 오류 방지

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = ""
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")

from app.config import settings  # noqa: E402
from app.ai import gemini_client  # noqa: E402
from app.ai.injection_guard import PII_MASK, mask_pii, sanitize_free_text  # noqa: E402
from app.ai.llm_provider import OllamaProvider, _tag_extraction_schema, create_provider_from_settings  # noqa: E402
from app.ai.schemas import LLMExtractionError  # noqa: E402
from app.ai.summarizer import GeminiSummarizer, OllamaSummarizer, create_summarizer_from_settings, create_course_summarizer_from_settings  # noqa: E402
from app.ai.tips_generator import OllamaTipsGenerator, create_tips_generator_from_settings  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


print("=== 0. 한도(429) 카운터 ===")
gemini_client._quota_hits.clear()
base = 1_000_000.0
gemini_client._record_quota_hit(base - 7200)   # 2시간 전 → 24h 창 안, 1h 창 밖
gemini_client._record_quota_hit(base - 60)
gemini_client._record_success(base - 30)
q = gemini_client.quota_status(now=base)
check("1시간 1회 / 24시간 2회", q["quota_429_last_hour"] == 1 and q["quota_429_last_24h"] == 2, str(q))
check("마지막 429·성공 시각", q["last_429_ts"] == base - 60 and q["last_success_ts"] == base - 30)
q2 = gemini_client.quota_status(now=base + 25 * 3600)
check("24시간 지나면 0", q2["quota_429_last_24h"] == 0, str(q2))
gemini_client._quota_hits.clear()

print("=== 1. 팩토리 스위치 ===")
provider = create_provider_from_settings(settings)
summarizer = create_summarizer_from_settings(settings)
tips = create_tips_generator_from_settings(settings)
check("온보딩 → OllamaProvider", type(provider) is OllamaProvider, type(provider).__name__)
check("요약 → OllamaSummarizer", type(summarizer) is OllamaSummarizer, type(summarizer).__name__)
check("팁 → OllamaTipsGenerator", type(tips) is OllamaTipsGenerator, type(tips).__name__)

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


with patch("httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("stub"))):
    asyncio.run(_fallbacks())
course = create_course_summarizer_from_settings(settings)
check("코스 → Gemini", type(course) is GeminiSummarizer)
check("코스 키 없음 → 폴백", asyncio.run(course.summarize_course("해운대 산책 코스")) is None)

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
