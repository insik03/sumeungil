"""같은 한국어 관광 입력으로 Ollama 모델의 태그 추출 품질과 지연을 비교한다.

모델을 자동으로 받거나 삭제하지 않는다. 먼저 ``ollama pull <model>``로 준비한 뒤 실행한다.

    cd backend
    python scripts/benchmark_local_llms.py
    python scripts/benchmark_local_llms.py --models qwen2.5:7b qwen3.5:2b-q4_K_M

출력 지표:
  - JSON: Ollama 응답이 구조화 스키마와 Pydantic 검증을 통과한 비율
  - F1: 사람이 정한 골든 태그 대비 정밀도/재현율의 조화평균
  - hallucinations: 입력 근거 없이 추가된 태그 수
  - p50/p95: 호출 전체 지연(모델 로드 포함)
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import tag_registry  # noqa: E402
from app.ai.llm_provider import OllamaProvider  # noqa: E402
from app.ai.schemas import LLMExtractionError, RawLLMExtraction  # noqa: E402


Tag = tuple[str, str]


@dataclass(frozen=True)
class Case:
    label: str
    text: str
    expected: frozenset[Tag]


CASES = (
    Case(
        "아이·반려견 산책",
        "6세 아이와 반려견이 함께 걸을 산책로를 찾고 있어요. 주차와 반려동물 동반이 꼭 필요해요.",
        frozenset(
            {
                ("companion", "with_child"),
                ("companion", "with_pet"),
                ("flag", "child_present"),
                ("flag", "pet_present"),
                ("mobility", "walk"),
                ("spot_pref", "walking_trail"),
                ("accessibility", "parking_required"),
                ("accessibility", "pet_friendly_required"),
                ("congestion_pref", "unspecified"),
            }
        ),
    ),
    Case(
        "연인·한적한 드라이브",
        "연인과 차로 조용한 공방을 둘러보고 싶고 붐비는 곳은 피하고 싶어요.",
        frozenset(
            {
                ("companion", "couple"),
                ("mobility", "car"),
                ("mood", "calm"),
                ("mood", "romantic"),
                ("spot_pref", "craft_shop"),
                ("congestion_pref", "avoid_priority"),
            }
        ),
    ),
    Case(
        "혼자·힐링 산책",
        "혼자 천천히 걸으면서 자연 풍경을 보고 힐링하고 싶어요. 혼잡도는 상관없어요.",
        frozenset(
            {
                ("companion", "solo"),
                ("mobility", "walk"),
                ("mood", "healing"),
                ("spot_pref", "nature_view"),
                ("congestion_pref", "indifferent"),
            }
        ),
    ),
    Case(
        "부모님·대중교통 시장",
        "부모님과 대중교통으로 전통시장에 가려 해요. 휠체어 접근이 가능한 곳이어야 해요.",
        frozenset(
            {
                ("companion", "with_parents"),
                ("mobility", "transit"),
                ("spot_pref", "traditional_market"),
                ("accessibility", "wheelchair_friendly"),
                ("congestion_pref", "unspecified"),
            }
        ),
    ),
    Case(
        "친구·축제 사진",
        "친구들과 활기찬 축제에서 사진 찍을 만한 곳을 찾고 있어요.",
        frozenset(
            {
                ("companion", "friends"),
                ("mood", "lively"),
                ("spot_pref", "festival"),
                ("spot_pref", "photo_spot"),
                ("congestion_pref", "unspecified"),
            }
        ),
    ),
)


def _actual_tags(raw: RawLLMExtraction) -> tuple[set[Tag], int]:
    actual: set[Tag] = set()
    unknown = 0
    for axis in tag_registry.AXES:
        for value in getattr(raw, axis):
            if tag_registry.is_valid(axis, value):
                actual.add((axis, value))
            else:
                unknown += 1
    return actual, unknown


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


async def _available_models(base_url: str) -> set[str]:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
    return {str(item.get("name", "")) for item in response.json().get("models", [])}


async def _benchmark_model(
    base_url: str,
    model: str,
    timeout_sec: float,
    runs: int,
) -> None:
    provider = OllamaProvider(
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        temperature=0,
        think=False,
        keep_alive="10m",
    )
    latencies: list[float] = []
    tp = fp = fn = unknown = successes = 0

    print(f"\n=== {model} ===")
    for run in range(1, runs + 1):
        for case in CASES:
            started = time.monotonic()
            try:
                raw = await provider.extract_tags(case.text)
            except LLMExtractionError as exc:
                latency = time.monotonic() - started
                latencies.append(latency)
                print(f"FAIL run={run} case={case.label} {latency:.2f}s error={exc}")
                continue

            latency = time.monotonic() - started
            latencies.append(latency)
            successes += 1
            actual, case_unknown = _actual_tags(raw)
            missing = case.expected - actual
            extra = actual - case.expected
            tp += len(case.expected & actual)
            fp += len(extra)
            fn += len(missing)
            unknown += case_unknown
            state = "PASS" if not missing and not extra and not case_unknown else "DIFF"
            print(
                f"{state} run={run} case={case.label} {latency:.2f}s "
                f"missing={sorted(missing)} extra={sorted(extra)} unknown={case_unknown}"
            )

    attempts = len(CASES) * runs
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(
        f"SUMMARY model={model} JSON={successes}/{attempts} ({successes / attempts:.0%}) "
        f"precision={precision:.3f} recall={recall:.3f} F1={f1:.3f} "
        f"hallucinations={fp} unknown={unknown} "
        f"p50={statistics.median(latencies):.2f}s p95={_percentile(latencies, 0.95):.2f}s"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument(
        "--models",
        nargs="+",
        default=("qwen2.5:7b", "qwen2.5:3b", "qwen3.5:2b-q4_K_M", "qwen3.5:4b-q4_K_M"),
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs는 1 이상이어야 합니다")

    try:
        available = await _available_models(args.base_url)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Ollama 연결 실패: {exc}", file=sys.stderr)
        return 2

    selected = [model for model in args.models if model in available]
    missing = [model for model in args.models if model not in available]
    for model in missing:
        print(f"SKIP {model}: 설치되지 않음 (ollama pull {model})")
    if not selected:
        print("비교할 설치 모델이 없습니다.", file=sys.stderr)
        return 2

    for model in selected:
        await _benchmark_model(args.base_url, model, args.timeout, args.runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
