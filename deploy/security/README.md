# Server hardening (2026-09-20)

The compose file limits json-file logs for every service, enables
no-new-privileges, and drops all Linux capabilities on backend, frontend,
Ollama, Prometheus, backup and retention services. PostgreSQL and nginx retain
their startup capabilities. No production volume is deleted by deployment.

Backup expiry runs independently of pg_dump/upload, every 5 minutes. It expires
matching files slightly before the configured age to allow for polling/rounding.
An interrupted scheduler can still delay expiry: monitor .last-retention-success.
External object storage needs its own lifecycle and restore test; local expiry
does not delete remote objects. The postgres-derived backup image has its own
anonymous data volume; that is not evidence that it shares the production DB.

## Host input guard

After checking that external RPC/LLMNR is not needed:

```sh
install -m 0755 deploy/security/host-guard.sh /usr/local/sbin/sumeungil-host-guard
install -m 0644 deploy/security/sumeungil-host-guard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sumeungil-host-guard
sumeungil-host-guard check
```

This only drops inbound TCP/UDP 111 and 5355, except loopback, for IPv4/IPv6.
It is not a full default-deny firewall or a replacement for NCP ACG. SSH, web
ports, FORWARD and Docker chains are unchanged. Applying twice is supported.
Rollback: `systemctl disable --now sumeungil-host-guard`.

Keep the existing SSH Match rule for the web terminal. Before restricting SSH
further, verify both an individual key login and an out-of-band recovery path.
Do not infer login ownership from an intermediate proxy IP alone.

## Verify and deploy

```sh
python3 deploy/backup/verify_retention.py
docker compose -f deploy/docker-compose.yml config --quiet
docker compose -f deploy/docker-compose.yml build postgres-backup
```

Recreate services in a controlled window with `--no-deps`, checking their health
after each change. Docker daemon restarts and OS upgrades are not required for
the compose changes. Verify all container log settings and NoNewPrivs after
recreation. PostgreSQL recreation causes a brief DB interruption; use the
existing named volume and never use `down -v` or `--renew-anon-volumes` on it.

OS security updates, SELinux enablement, NCP IAM/ACG and remote backups remain
separate operational changes requiring compatibility/access validation.


## DB/backup credential isolation

PostgreSQL receives only POSTGRES_DB/USER/PASSWORD. The backup service receives
those credentials plus explicitly listed backup/object-store settings. Do not
restore `env_file: .env` on either service: the shared file contains application,
OAuth and session secrets. Add any new backup setting explicitly and update the
rendered-Compose regression test. BACKUP_DIR is fixed to the mounted /backups.

Run `python3 deploy/security/verify_env_isolation.py` with Docker Compose installed;
it renders only synthetic credentials and requires no running Docker daemon.
Recreate the two containers to apply; preserve the database and backup volumes.
Database recreation briefly interrupts DB connections: check readiness and the
backend afterward. Keep a copy of the previous Compose file for rollback.


## Runtime database separation and read audit

After building the backend image, run `python3 deploy/security/provision-runtime.py`
once on the host. It migrates with the retained database owner, creates app CRUD
and backup read-only roles, prepares mode-600 `.backend.env` and preserves the old
`.env` as `.env.before-runtime-role`. It refuses to overwrite cutover files or
rotate existing roles automatically. Then validate Compose and recreate backend
and postgres-backup only. Keep the previous backend image for rollback.

The runtime env excludes POSTGRES_*, AWS_* and BACKUP_* owner credentials. It uses
Compose env_file `format: raw` so dollar signs and password hashes survive exactly
(Compose >=2.30; https://docs.docker.com/reference/compose-file/services/#format).
Future app secret changes must update `.backend.env`, not just the owner `.env`.
For future releases: build backend, run `python3 deploy/security/migrate-runtime.py`,
then recreate backend. That migration reapplies grants to new tables without
rotating roles. DATABASE_AUTO_MIGRATE=false fails closed on a schema mismatch.

users/inquiries list queries write minimal target IDs, selected operator label,
IP HMAC and time in the same transaction before returning data. App role cannot
read/update/delete/truncate privacy_access_events. A shared admin password still
cannot prove the selected label's human identity; this is not individual MFA.
The DB owner can inspect audit events and remains trusted. Audit retention and
independent archival need an explicit operator policy; this release does not
silently delete historical audit evidence.

## Independent backup monitor

`python3 deploy/security/backup-monitor.py --dry-run` checks container liveness,
local backup and expiry markers, plus offsite marker if configured. It never
sends or saves notification state. The timer checks every five minutes; actual
notifications require the existing Slack incoming webhook, acknowledge HTTP 200
and body `ok`, notify on failure/recovery, and remind hourly while failed.
No message bodies, user data or credentials are included. Enable the supplied
systemd timer only after authorization for the intended receiving channel.
Use `--test-notification` for the separately authorized one-time message.
