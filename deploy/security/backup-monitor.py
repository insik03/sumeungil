#!/usr/bin/env python3
"""Root timer monitors backup independently; dry-run never sends or changes state."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

DEPLOY = Path(__file__).resolve().parents[1]
STATE = Path("/var/lib/sumeungil-security/backup-alert.json")

def assess(backup_dir, running, max_age, now):
    reasons = []
    if not running:
        reasons.append("backup_container_not_running")
    for filename, limit in ((".last-success", max_age), (".last-retention-success", 7200)):
        try:
            age = now - int((backup_dir / filename).read_text().strip())
            if age < -300 or age > limit:
                reasons.append(filename[1:] + "_stale")
        except (OSError, ValueError):
            reasons.append(filename[1:] + "_missing")
    return reasons

def should_send(previous, status, now):
    return ((status != "ok" and (previous.get("status") != status or now - previous.get("sent_at", 0) >= 3600))
            or (status == "ok" and previous.get("status") not in (None, "ok")))

def deliver(url, text):
    if not url.startswith("https://hooks.slack.com/services/"):
        raise RuntimeError("Configured destination is not a Slack incoming webhook")
    request = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200 or response.read().strip() != b"ok":
            raise RuntimeError("Slack did not acknowledge delivery")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-notification", action="store_true")
    args = parser.parse_args()
    now = int(time.time())
    # Inspect only the backup, never print environment values.
    try:
        item = json.loads(subprocess.check_output(["docker", "inspect", "sumeungil-postgres-backup"], stderr=subprocess.DEVNULL))[0]
        values = dict(x.split("=", 1) for x in item["Config"]["Env"])
        running = item["State"]["Running"]
        max_age = int(values.get("BACKUP_MAX_AGE_SECONDS", "93600"))
        offsite = bool(values.get("BACKUP_S3_URI"))
    except Exception:
        running, max_age, offsite = False, 93600, False
    reasons = assess(DEPLOY / "backups", running, max_age, now)
    if offsite:
        try:
            age = now - int((DEPLOY / "backups/.last-offsite-success").read_text())
            if age < -300 or age > max_age:
                reasons.append("offsite_stale")
        except (OSError, ValueError):
            reasons.append("offsite_missing")
    status = ",".join(reasons) or "ok"
    if args.dry_run:
        print(json.dumps({"status": status, "notification_sent": False}))
        return
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = {}
    if not args.test_notification and not should_send(previous, status, now):
        print("No notification required")
        return
    # The existing backend owns the Slack integration; backup never receives its secret.
    item = json.loads(subprocess.check_output(["docker", "inspect", "sumeungil-backend"]))[0]
    env = dict(x.split("=", 1) for x in item["Config"]["Env"])
    url = env.get("SLACK_WEBHOOK_URL", "")
    label = "백업 감시 시험 알림" if args.test_notification else "백업 상태 정상 복구" if status == "ok" else "백업 점검 필요"
    # Fixed status codes only: no users, filesystem paths, credentials or log bodies.
    deliver(url, "[숨은길] " + label + " — " + status)
    if not args.test_notification:
        STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = STATE.with_suffix(".tmp")
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"status": status, "sent_at": now}, stream)
        os.replace(str(temp), str(STATE))
    print("Slack delivery acknowledged")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exception messages may contain webhook URLs; log type only.
        print("Backup monitor failed: " + type(exc).__name__)
        raise SystemExit(1)
