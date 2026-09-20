#!/bin/sh
# nginx 접속·오류 로그 순환 + 보관기간 경과분 자동 삭제 (2026-09-20).
#
# 개인정보처리방침이 "접속·오류 로그는 90일 보관 후 자동 삭제"라고 안내하므로 그 약속을 실제로 지키는
# 장치다. nginx 는 ./logs/nginx 에 access.log·error.log 를 쓰고(docker-compose.yml), 이 스크립트가
# 하루 1회:
#   1) 현재 로그를 날짜·시각 붙은 gzip 사본으로 옮기고 원본을 비운다(copytruncate — nginx 는 O_APPEND 로
#      열어 두므로 재시작·시그널 없이 안전. 복사와 비우기 사이 수 ms 의 줄은 유실될 수 있다)
#   2) LOG_RETENTION_DAYS(기본 90일)보다 오래된 사본을 지운다
#
#   LOG_DIR=/logs LOG_RETENTION_DAYS=90 LOG_ROTATE_INTERVAL_SECONDS=86400 retention.sh [once]
set -eu

dir="${LOG_DIR:-/logs}"
days="${LOG_RETENTION_DAYS:-90}"
interval="${LOG_ROTATE_INTERVAL_SECONDS:-86400}"

case "$days" in ''|*[!0-9]*) echo "ERROR: LOG_RETENTION_DAYS must be a positive integer" >&2; exit 1 ;; esac
[ "$days" -ge 1 ] || { echo "ERROR: LOG_RETENTION_DAYS must be >= 1" >&2; exit 1; }

rotate_once() {
  stamp=$(date +%Y%m%d%H%M%S)
  for name in access.log error.log; do
    f="$dir/$name"
    [ -s "$f" ] || continue
    if cp "$f" "$f.$stamp" && : > "$f"; then
      gzip -f "$f.$stamp"
    else
      echo "ERROR: rotate failed for $f" >&2
      rm -f "$f.$stamp"
    fi
  done
  # 분 단위로 비교한다(-mtime 은 일 단위 올림이라 91일째에야 지워진다).
  find "$dir" -type f -name '*.log.*' -mmin "+$((days * 1440))" -exec rm -f {} \;
}

if [ "${1:-}" = "once" ]; then
  rotate_once
  exit 0
fi

while :; do
  rotate_once
  sleep "$interval"
done
