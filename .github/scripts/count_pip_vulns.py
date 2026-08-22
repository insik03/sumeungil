"""dependency-audit.yml 전용 — pip-audit -f json 결과에서 취약점 총 건수만 뽑는다.
인라인 YAML 문자열 대신 파일로 뺀 이유: 셸/YAML/파이썬 3중 이스케이프가 얽혀 깨지기 쉬워서다.
"""
import json

count = 0
try:
    with open("pip-audit.json", encoding="utf-8") as f:
        data = json.load(f)
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    count = sum(len(d.get("vulns", [])) for d in deps)
except Exception:
    count = 0
print(count)
