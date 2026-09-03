#!/bin/sh
set -eu

umask 077

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

backup_dir=/backups
interval="${BACKUP_INTERVAL_SECONDS:-86400}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$backup_dir"

upload_backup() {
  backup_file="$1"
  checksum_file="$2"
  destination="${BACKUP_S3_URI:-}"

  if [ -z "$destination" ]; then
    echo "WARNING: BACKUP_S3_URI is empty; backup remains on this host only" >&2
    return 0
  fi
  destination="${destination%/}"

  if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
    aws s3 cp "$backup_file" "$destination/$(basename "$backup_file")" \
      --endpoint-url "$AWS_ENDPOINT_URL" --sse "${BACKUP_S3_SSE:-AES256}" --only-show-errors \
      || return 1
    aws s3 cp "$checksum_file" "$destination/$(basename "$checksum_file")" \
      --endpoint-url "$AWS_ENDPOINT_URL" --sse "${BACKUP_S3_SSE:-AES256}" --only-show-errors \
      || return 1
  else
    aws s3 cp "$backup_file" "$destination/$(basename "$backup_file")" \
      --sse "${BACKUP_S3_SSE:-AES256}" --only-show-errors \
      || return 1
    aws s3 cp "$checksum_file" "$destination/$(basename "$checksum_file")" \
      --sse "${BACKUP_S3_SSE:-AES256}" --only-show-errors \
      || return 1
  fi
}

while :; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  partial="$backup_dir/.sumeungil-$stamp.dump.partial"
  backup_file="$backup_dir/sumeungil-$stamp.dump"
  checksum_file="$backup_file.sha256"

  echo "Starting PostgreSQL backup: $backup_file"
  if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    --host postgres --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --format custom --no-owner --no-privileges --file "$partial" \
    && pg_restore --list "$partial" >/dev/null; then
    mv "$partial" "$backup_file"
    sha256sum "$backup_file" > "$checksum_file"
    date +%s > "$backup_dir/.last-success"
    if upload_backup "$backup_file" "$checksum_file"; then
      if [ -n "${BACKUP_S3_URI:-}" ]; then
        date +%s > "$backup_dir/.last-offsite-success"
      fi
    else
      echo "ERROR: off-site upload failed; local backup remains valid" >&2
    fi
    echo "Backup completed: $backup_file"

    find "$backup_dir" -type f \
      \( -name 'sumeungil-*.dump' -o -name 'sumeungil-*.dump.sha256' \) \
      -mtime "+$retention_days" -exec rm -f {} \;
  else
    rm -f "$partial"
    echo "ERROR: PostgreSQL backup failed" >&2
  fi

  sleep "$interval"
done
