#!/usr/bin/env python3
"""Compare candidate runtime secrets privately and verify its actual DB privileges."""
import json
from pathlib import Path
import subprocess

DEPLOY = Path(__file__).resolve().parents[1]
def main():
    original = json.loads(subprocess.check_output(["docker", "inspect", "sumeungil-backend"]))[0]
    expected = dict(x.split("=",1) for x in original["Config"]["Env"])
    code = """
import os,json,psycopg
from app.db.postgres import Database
assert os.environ['DATABASE_AUTO_MIGRATE']=='false'
db=Database(os.environ['DATABASE_URL'],auto_migrate=False)
assert db.ensure_ready()
with psycopg.connect(os.environ['DATABASE_URL']) as c:
    row=c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
    assert row==(False,False,False,False,False)
    assert c.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0] is False
    assert c.execute("SELECT has_table_privilege(current_user,'privacy_access_events','INSERT')").fetchone()[0] is True
    assert c.execute("SELECT has_table_privilege(current_user,'privacy_access_events','DELETE')").fetchone()[0] is False
db.close()
print(json.dumps(dict(os.environ)))
"""
    result = subprocess.run(["docker", "compose", "-f", str(DEPLOY / "docker-compose.yml"),
                             "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "backend", "-c", code],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise RuntimeError("Candidate runtime/DB verification failed; old service was not recreated")
    actual = json.loads(result.stdout)
    for key,value in expected.items():
        if key.startswith(("POSTGRES_", "AWS_", "BACKUP_")) or key in ("DATABASE_URL", "DATABASE_AUTO_MIGRATE"):
            continue
        if actual.get(key) != value:
            raise RuntimeError("Existing runtime variable changed: " + key)
    if any(k.startswith(("POSTGRES_", "AWS_", "BACKUP_")) for k in actual):
        raise RuntimeError("Owner/backup credentials present in runtime")
    print("RUNTIME_SECRET_PRESERVATION_AND_DB_PERMISSIONS_OK")
if __name__ == "__main__":
    main()
