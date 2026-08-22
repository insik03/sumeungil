"""dependency-audit.yml 전용 — pip-audit -f json 결과에서 취약점 총 건수만 뽑는다.
인라인 YAML 문자열 대신 파일로 뺀 이유: 셸/YAML/파이썬 3중 이스케이프가 얽혀 깨지기 쉬워서다.

2026-08-22 보안/QA 병렬 검증에서 발견된 버그를 고쳤다: 이전 버전은 `data.get(...)` 을
먼저 평가해 `data` 가 list 일 때(pip-audit 스키마 변형) `AttributeError` 를 던졌고,
바깥의 `except Exception: count = 0` 이 그걸 삼켜 **파싱 실패와 "취약점 0건"을 구분하지
못했다** — 감사 자체가 깨져도 "이번 주도 깨끗함"으로 보이는 fail-open 이었다.
지금은 파싱 실패 시 **stderr 로 원인을 적고 비정상 종료(exit 1)** 한다 — 워크플로가
이 실패를 그대로 잡(job) 실패로 전파해야 한다("count == 0" 과 "확인 못함"을 절대
같은 것으로 취급하지 않는다).
"""
import json
import sys


def main() -> int:
    try:
        with open("pip-audit.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"pip-audit.json 을 읽거나 파싱할 수 없습니다: {exc}", file=sys.stderr)
        return 1

    if isinstance(data, list):
        deps = data
    elif isinstance(data, dict):
        deps = data.get("dependencies", [])
    else:
        print(f"예상치 못한 최상위 타입: {type(data).__name__}", file=sys.stderr)
        return 1

    try:
        count = sum(len(d.get("vulns", [])) for d in deps)
    except (AttributeError, TypeError) as exc:
        print(f"dependencies 항목 형식이 예상과 다릅니다: {exc}", file=sys.stderr)
        return 1

    print(count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
