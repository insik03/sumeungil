#!/bin/sh
# Separate process: expiry continues even when pg_dump/upload fails or hangs.
set -eu
dir="${BACKUP_DIR:-/backups}"
days="${BACKUP_RETENTION_DAYS:-14}"
interval="${BACKUP_RETENTION_CHECK_SECONDS:-300}"
case "$dir" in /*) ;; *) echo 'ERROR: BACKUP_DIR must be absolute' >&2; exit 1 ;; esac
[ "$dir" != / ] || exit 1
case "$days:$interval" in *[!0-9:]*|:*|*:) echo 'ERROR: invalid retention settings' >&2; exit 1 ;; esac
[ "$days" -ge 1 ] && [ "$days" -le 3650 ] || exit 1
[ "$interval" -ge 60 ] && [ "$interval" -le 3600 ] || exit 1
# Expire slightly early to allow for polling and find's minute rounding.
# Scheduling outages can still delay expiry: monitor this container's health.
cutoff=$((days * 1440 - (interval + 59) / 60 - 2))
mkdir -p "$dir"
while :; do
  find "$dir" -maxdepth 1 -type f \
    \( -name 'sumeungil-*.dump' -o -name 'sumeungil-*.dump.sha256' -o -name '.sumeungil-*.dump.partial' \) \
    -mmin "+$cutoff" -exec rm -f -- {} \;
  date +%s > "$dir/.last-retention-success"
  [ "${1:-}" != once ] || exit 0
  sleep "$interval"
done
