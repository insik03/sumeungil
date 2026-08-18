#!/usr/bin/env bash
# 배포 알림을 #알림-봇 으로 보낸다 (2026-08-18, 대표 지시).
#
# 왜 필요한가: 이 저장소는 서버에 git 이 없어 배포가 수동(tar+scp)이다. 그래서 누가 언제
# 무엇을 배포했는지 팀원(지훈·태준)이 알 방법이 없었다 — 사이트가 잠깐 끊기면 "장애인가?"
# 부터 의심하게 된다. 배포 앞뒤로 이 스크립트를 부르면 그 혼선이 사라진다.
#
# 사용법 (서버 또는 개발 PC 어디서나):
#   ./notify-slack.sh start "관리자 콘솔 문의 탭 추가"
#   ./notify-slack.sh done  "관리자 콘솔 문의 탭 추가"
#   ./notify-slack.sh fail  "빌드 실패 — 롤백함"
#
# 웹훅 URL 은 (1) 환경변수 SLACK_WEBHOOK_URL 또는 (2) 이 스크립트와 같은 폴더의 .env 에서
# 읽는다. **URL 을 인자로 받지 않는다** — 셸 히스토리(~/.bash_history)에 시크릿이 남기 때문이다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "사용법: $(basename "$0") {start|done|fail} [메모]" >&2
  exit 2
}

[ $# -ge 1 ] || usage
PHASE="$1"
NOTE="${2:-}"

# --- 인자 검증을 **웹훅 조회보다 먼저** 한다 ---
# 순서를 바꾸면 `notify-slack.sh strat` 같은 오타가 "웹훅 없음"으로 조용히 끝나
# 배포 알림이 안 온 이유를 오타에서 찾지 못한다.
case "$PHASE" in
  start) ICON="🛠"; LABEL="배포 시작" ;;
  done)  ICON="🚀"; LABEL="배포 완료" ;;
  fail)  ICON="⛔"; LABEL="배포 실패" ;;
  *)     echo "알 수 없는 단계: '$PHASE'" >&2; usage ;;
esac

# --- 웹훅 URL 확보 (값은 절대 출력하지 않는다) ---
if [ -z "${SLACK_WEBHOOK_URL:-}" ] && [ -f "$SCRIPT_DIR/.env" ]; then
  # .env 전체를 source 하면 다른 시크릿까지 셸에 퍼진다 — 필요한 한 줄만 뽑는다.
  SLACK_WEBHOOK_URL="$(grep -m1 '^SLACK_WEBHOOK_URL=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
fi

if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
  echo "SLACK_WEBHOOK_URL 이 없어 알림을 건너뜁니다 (배포 자체와 무관)." >&2
  exit 0   # 알림 실패로 배포 절차를 멈추지 않는다
fi

WHO="$(whoami 2>/dev/null || echo unknown)"
HOST="$(hostname 2>/dev/null || echo unknown)"
WHEN="$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M')"

TEXT="${ICON} *${LABEL}* — sumeungil.co.kr"
TEXT="${TEXT}"$'\n'"실행: ${WHO}@${HOST} · ${WHEN} KST"
[ -n "$NOTE" ] && TEXT="${TEXT}"$'\n'"내용: ${NOTE}"
if [ "$PHASE" = "start" ]; then
  TEXT="${TEXT}"$'\n'"잠시 사이트가 끊길 수 있습니다. 완료되면 다시 알립니다."
fi

# jq 가 있으면 그것으로, 없으면 python3 으로 JSON 을 만든다(따옴표·개행 이스케이프).
# printf 로 직접 조립하면 메모에 " 나 \ 가 들어갈 때 JSON 이 깨진다.
if command -v jq >/dev/null 2>&1; then
  PAYLOAD="$(jq -nc --arg t "$TEXT" '{text:$t, unfurl_links:false}')"
elif command -v python3 >/dev/null 2>&1; then
  PAYLOAD="$(TEXT="$TEXT" python3 -c 'import json,os; print(json.dumps({"text":os.environ["TEXT"],"unfurl_links":False}))')"
else
  echo "jq 도 python3 도 없어 알림을 건너뜁니다." >&2
  exit 0
fi

CODE="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-type: application/json' --data "$PAYLOAD" "$SLACK_WEBHOOK_URL" || echo 000)"

if [ "$CODE" = "200" ]; then
  echo "슬랙 알림 전송 완료 (${LABEL})"
else
  # 실패해도 0 으로 끝낸다 — 알림 때문에 배포 스크립트가 멈추면 안 된다.
  echo "슬랙 알림 전송 실패 (HTTP ${CODE}) — 배포는 계속하세요." >&2
fi
exit 0
