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
