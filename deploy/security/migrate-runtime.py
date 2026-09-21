#!/usr/bin/env python3
"""Host-only migration with DB owner credentials; runtime remains unprivileged."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

DEPLOY = Path(__file__).resolve().parents[1]

def main():
    pg = json.loads(subprocess.check_output(["docker", "inspect", "sumeungil-postgres"]))[0]
    env = dict(item.split("=",1) for item in pg["Config"]["Env"])
    networks = list(pg["NetworkSettings"]["Networks"])
    if len(networks) != 1:
        raise RuntimeError("Expected exactly one database network")
    fd, filename = tempfile.mkstemp(dir=str(DEPLOY), prefix=".migration-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
                if "\n" in env[key] or "\r" in env[key]:
                    raise RuntimeError("Multiline DB value unsupported")
                stream.write(key + "=" + env[key] + "\n")
        code = """
import os
from psycopg.conninfo import make_conninfo
from app.db.postgres import Database
from app.security.db_roles import grant_runtime
db=Database(make_conninfo(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD']))
try:
    if not db.ensure_ready(): raise RuntimeError('Migration failed')
    db.write(grant_runtime)
finally:
    db.close()
print('MIGRATION_AND_RUNTIME_GRANTS_OK')
"""
        result = subprocess.run(["docker", "run", "--rm", "--network", networks[0],
                                 "--env-file", filename, "--entrypoint", "python", "deploy-backend", "-c", code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode:
            raise RuntimeError("Migration failed; do not restart runtime with the new image")
        print("MIGRATION_AND_RUNTIME_GRANTS_OK")
    finally:
        os.unlink(filename)
if __name__ == "__main__":
    main()
