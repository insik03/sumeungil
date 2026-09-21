"""Isolated schema: restricted runtime CRUD, audit fail-closed and forbidden SQL."""
import asyncio
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from _pg_test_helpers import isolated_database_url, drop_schema
from app.security.db_roles import prepare_roles, APP_ROLE, BACKUP_ROLE
from app.db.postgres import Database
from app.services import admin_service

admin, base, schema = isolated_database_url()
password, backup_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
runtime = None
created = False
try:
    prepare_roles(admin, password, backup_password)
    created = True
    restricted = make_conninfo(admin, user=APP_ROLE, password=password)
    runtime = Database(restricted, auto_migrate=False)
    assert runtime.ensure_ready()
    def insert(conn):
        return conn.execute("INSERT INTO users(display_name,created_at,last_login_at) VALUES (%s,%s,%s) RETURNING id", ("audit synthetic", "2026-09-20", "2026-09-20")).fetchone()["id"]
    user_id = runtime.write(insert)
    result = asyncio.run(admin_service.list_users(runtime, limit=10, offset=0, operator="test operator", ip_hash="synthetic-hash"))
    assert result.total == 1 and not hasattr(result.items[0], "audit_user_id")
    asyncio.run(admin_service.list_inquiries(runtime, status="all", limit=10, offset=0, operator="test operator", ip_hash="synthetic-hash"))
    with psycopg.connect(admin) as c:
        events = c.execute("SELECT operator,resource,target_ids FROM privacy_access_events ORDER BY id").fetchall()
        assert events == [("test operator", "users", [user_id]), ("test operator", "inquiries", [])]
    for statement in ["CREATE TABLE forbidden(id int)", "CREATE ROLE forbidden", "DELETE FROM privacy_access_events", "UPDATE schema_version SET version=0", "TRUNCATE users"]:
        try:
            runtime.write(lambda c: c.execute(statement))
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError("Restricted runtime accepted forbidden SQL")
    with psycopg.connect(make_conninfo(admin, user=BACKUP_ROLE, password=backup_password)) as c:
        assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        try:
            c.execute("DELETE FROM users")
        except psycopg.errors.InsufficientPrivilege:
            c.rollback()
        else:
            raise AssertionError("Backup role can write")
    with psycopg.connect(admin) as c:
        c.execute(sql.SQL("REVOKE INSERT ON privacy_access_events FROM {}").format(sql.Identifier(APP_ROLE)))
    try:
        asyncio.run(admin_service.list_users(runtime, limit=10, offset=0, operator="test", ip_hash="test"))
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("Privacy query returned without a durable audit event")
    runtime.write(lambda c: c.execute("DELETE FROM users WHERE id=%s", (user_id,)))
    print("PASS: runtime CRUD, read-only backup, append-only audit, forbidden DDL, fail-closed disclosure")
finally:
    if runtime:
        runtime.close()
    if created:
        with psycopg.connect(base, autocommit=True) as c:
            for role in (APP_ROLE, BACKUP_ROLE):
                c.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
    drop_schema(base, schema)
