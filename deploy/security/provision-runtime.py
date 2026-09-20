#!/usr/bin/env python3
"""One-time host cutover preparation. Does not restart services or print credentials.
Run after building the new backend image. Existing admin credentials remain in .env
for migrations/recovery; only .backend.env is passed to the runtime container.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

DEPLOY = Path(__file__).resolve().parents[1]

def atomic_write(path, data):
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=".security-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)

def run():
    envpath = DEPLOY / ".env"
    runtimepath = DEPLOY / ".backend.env"
    rollback = DEPLOY / ".env.before-runtime-role"
    if runtimepath.exists() or rollback.exists():
        raise RuntimeError("Cutover files already exist; inspect state instead of rotating credentials")
    old = envpath.read_text()
    info = json.loads(subprocess.check_output(["docker", "inspect", "sumeungil-backend"]))[0]
    values = dict(entry.split("=", 1) for entry in info["Config"]["Env"])
    # Refuse complex values before making changes. They need an explicit renderer.
    if any("\n" in v or "\r" in v for v in values.values()):
        raise RuntimeError("Multiline environment value needs reviewed rendering")
    payload = {"app_password": secrets.token_urlsafe(40), "backup_password": secrets.token_urlsafe(40)}
    code = """
import json,sys,os
from psycopg.conninfo import make_conninfo
from app.security.db_roles import prepare_roles,APP_ROLE
v=json.load(sys.stdin)
dsn=make_conninfo(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
prepare_roles(dsn,v['app_password'],v['backup_password'])
# Runtime URI is generated without logging values; parent captures stdout privately.
from urllib.parse import quote
print(json.dumps({'url':'postgresql://'+APP_ROLE+':'+quote(v['app_password'],safe='')+'@postgres:5432/'+quote(os.environ['POSTGRES_DB'],safe='')}))
"""
    # Resolve network from the existing service instead of assuming Compose project name.
    networks = list(info["NetworkSettings"]["Networks"])
    if len(networks) != 1:
        raise RuntimeError("Expected exactly one application network")
    atomic_write(rollback, old)
    fd, migration_env = tempfile.mkstemp(dir=str(DEPLOY), prefix=".migration-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "PUBLIC_DATA_API_KEY"):
                stream.write(key + "=" + values.get(key, "") + "\n")
        result = subprocess.run(["docker", "run", "--rm", "-i", "--network", networks[0],
                                 "--env-file", migration_env, "--entrypoint", "python",
                                 "deploy-backend", "-c", code], input=json.dumps(payload),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    finally:
        os.unlink(migration_env)
    if result.returncode:
        raise RuntimeError("Role preparation failed; old runtime unchanged. Inspect migration status without printing secrets")
    url = json.loads(result.stdout)["url"]
    filtered = {k: v for k, v in values.items() if not k.startswith(("POSTGRES_", "AWS_", "BACKUP_"))}
    filtered.update(DATABASE_URL=url, DATABASE_AUTO_MIGRATE="false")
    def line(key, value):
        return key + "='" + value.replace("\\", "\\\\").replace("'", "\\'") + "'\n"
    atomic_write(runtimepath, "".join(line(k,v) for k,v in sorted(filtered.items())))
    updates = {"BACKEND_ENV_FILE": ".backend.env", "BACKUP_DB_USER": "sumeungil_backup", "BACKUP_DB_PASSWORD": payload["backup_password"]}
    retained = [l for l in old.splitlines() if l.split("=",1)[0] not in updates]
    atomic_write(envpath, "\n".join(retained) + "\n" + "".join(line(k,v) for k,v in updates.items()))
    print("PREPARED: migrated schema; restricted app/backup roles; private runtime env; admin recovery env preserved")

if __name__ == "__main__":
    run()
