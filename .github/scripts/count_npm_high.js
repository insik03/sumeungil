// dependency-audit.yml 전용 — npm audit --json 결과에서 high+critical 건수만 뽑는다.
// 인라인 YAML 문자열 대신 파일로 뺀 이유: 셸/YAML/JS 3중 이스케이프가 얽혀 깨지기 쉬워서다.
//
// 2026-08-22 보안/QA 병렬 검증 지적(count_pip_vulns.py 와 같은 종류의 버그 가능성) —
// npm audit 이 실패하면 `{"error":{"code":"EUSAGE",...}}` 형태의 **유효한 JSON**을
// 내놓는다. 이전 버전은 이걸 파싱은 성공하고 `metadata` 가 없으니 그냥 count=0 을
// 냈다 — "감사 실패"와 "취약점 0건"이 구분 안 되는 fail-open 이었다. 지금은 두 경우
// 모두 stderr 로 원인을 적고 비정상 종료(exit 1)한다.
const fs = require("fs");

function main() {
  let report;
  try {
    report = JSON.parse(fs.readFileSync("npm-audit.json", "utf8"));
  } catch (err) {
    console.error(`npm-audit.json 을 읽거나 파싱할 수 없습니다: ${err.message}`);
    return 1;
  }

  if (report && report.error) {
    console.error(
      `npm audit 자체가 실패했습니다(code=${report.error.code}): ${report.error.summary || ""}`
    );
    return 1;
  }

  const v = report && report.metadata && report.metadata.vulnerabilities;
  if (!v) {
    console.error("예상한 metadata.vulnerabilities 구조가 없습니다 — npm audit 출력 형식이 바뀐 것으로 보입니다.");
    return 1;
  }

  console.log((v.high || 0) + (v.critical || 0));
  return 0;
}

process.exit(main());
