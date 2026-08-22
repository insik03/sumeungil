// dependency-audit.yml 전용 — npm audit --json 결과에서 high+critical 건수만 뽑는다.
// 인라인 YAML 문자열 대신 파일로 뺀 이유: 셸/YAML/JS 3중 이스케이프가 얽혀 깨지기 쉬워서다.
const fs = require("fs");

let count = 0;
try {
  const report = JSON.parse(fs.readFileSync("npm-audit.json", "utf8"));
  const v = report.metadata && report.metadata.vulnerabilities;
  if (v) count = (v.high || 0) + (v.critical || 0);
} catch {
  count = 0;
}
console.log(count);
