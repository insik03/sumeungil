#!/bin/sh
# retention.sh 동작 검증 — docker 없이 로컬에서: sh deploy/logs/test-retention.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
check() { if [ "$2" = "ok" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; fail=1; fi; }

# 90일보다 오래된 사본 / 89일 된 사본 / 현재 로그
echo "old" | gzip > "$tmp/access.log.20250101000000.gz"
echo "recent" | gzip > "$tmp/access.log.20250601000000.gz"
touch -d '91 days ago' "$tmp/access.log.20250101000000.gz"
touch -d '89 days ago' "$tmp/access.log.20250601000000.gz"
echo "GET /a 200" > "$tmp/access.log"
echo "[warn] x" > "$tmp/error.log"

LOG_DIR="$tmp" LOG_RETENTION_DAYS=90 sh "$here/retention.sh" once

[ ! -e "$tmp/access.log.20250101000000.gz" ] && check "91일 지난 사본은 삭제" ok || check "91일 지난 사본은 삭제" no
[ -e "$tmp/access.log.20250601000000.gz" ] && check "89일 된 사본은 유지" ok || check "89일 된 사본은 유지" no
[ ! -s "$tmp/access.log" ] && [ ! -s "$tmp/error.log" ] && check "현재 로그는 비워짐(계속 기록 가능)" ok || check "현재 로그는 비워짐(계속 기록 가능)" no
n=$(ls "$tmp"/access.log.2* 2>/dev/null | wc -l)
[ "$n" -eq 2 ] && check "새 사본 생성(기존 유지 1 + 신규 1)" ok || check "새 사본 생성(기존 유지 1 + 신규 1)" no
new=$(ls -t "$tmp"/access.log.*.gz | head -1)
[ "$(gzip -dc "$new")" = "GET /a 200" ] && check "새 사본에 원래 내용 보존" ok || check "새 사본에 원래 내용 보존" no

# 빈 로그는 사본을 만들지 않는다 / 잘못된 보관일은 거부
before=$(ls "$tmp" | wc -l)
LOG_DIR="$tmp" LOG_RETENTION_DAYS=90 sh "$here/retention.sh" once
[ "$(ls "$tmp" | wc -l)" -eq "$before" ] && check "빈 로그는 사본 안 만듦" ok || check "빈 로그는 사본 안 만듦" no
LOG_DIR="$tmp" LOG_RETENTION_DAYS=abc sh "$here/retention.sh" once 2>/dev/null && check "잘못된 보관일 거부" no || check "잘못된 보관일 거부" ok

[ "$fail" -eq 0 ] && echo "== ALL PASS ==" || { echo "== FAIL =="; exit 1; }
