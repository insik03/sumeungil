"""Render Compose with synthetic secrets; no daemon or production .env needed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
# A new unexpected variable in the shared file must not leak to infrastructure.
blocked = {"GEMINI_API_KEY", "GOOGLE_CLIENT_SECRET", "ADMIN_SESSION_SECRET",
           "USER_SESSION_SECRET", "SLACK_WEBHOOK_URL", "UNEXPECTED_PRIVATE_VALUE"}
with tempfile.TemporaryDirectory() as directory:
    envfile = Path(directory) / "audit.env"
    values = {key: "synthetic-do-not-propagate" for key in blocked}
    values.update(POSTGRES_DB="audit", POSTGRES_USER="audit", POSTGRES_PASSWORD="synthetic-db",
                  BACKUP_RETENTION_DAYS="9", AWS_ACCESS_KEY_ID="synthetic-object-key",
                  AWS_SECRET_ACCESS_KEY="synthetic-object-secret", BACKUP_S3_URI="s3://synthetic/backup",
                  NEXT_PUBLIC_API_BASE="http://localhost", NEXT_PUBLIC_TMAP_APP_KEY="",
                  NEXT_PUBLIC_NAVER_MAP_CLIENT_ID="")
    envfile.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    # Remove host overrides for variables under test. Compose only renders config.
    environment = {k: v for k, v in os.environ.items() if k not in values}
    result = subprocess.run(["docker", "compose", "--env-file", str(envfile), "-f", str(compose),
                             "config", "--no-env-resolution", "--format", "json"],
                            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, check=True)
    services = json.loads(result.stdout)["services"]
    for name in ("postgres", "postgres-backup"):
        service = services[name]
        assert not service.get("env_file"), f"{name} loads the shared env file"
        assert not blocked.intersection(service["environment"]), f"{name} receives unrelated credentials"
        assert service["environment"]["POSTGRES_PASSWORD"] == "synthetic-db"
        assert not service.get("ports"), f"{name} publishes a host port"
    assert set(services["postgres"]["environment"]) == {"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"}
    backup = services["postgres-backup"]["environment"]
    assert backup["BACKUP_RETENTION_DAYS"] == "9"
    assert backup["AWS_SECRET_ACCESS_KEY"] == "synthetic-object-secret"
    assert backup["BACKUP_S3_URI"] == "s3://synthetic/backup"
    assert backup["BACKUP_DIR"] == "/backups"
print("PASS: rendered DB/backup environments exclude unrelated secrets and retain backup settings")
