"""Administrative migration/provisioning; never called by HTTP request handlers."""
from psycopg import sql
from app.db.postgres import Database

APP_ROLE = "sumeungil_app"
BACKUP_ROLE = "sumeungil_backup"

def prepare_roles(admin_dsn, app_password, backup_password):
    db = Database(admin_dsn)
    try:
        if not db.ensure_ready():
            raise RuntimeError("Administrative schema migration failed")
        def provision(conn):
            schema = conn.execute("SELECT current_schema() AS name").fetchone()["name"]
            database = conn.execute("SELECT current_database() AS name").fetchone()["name"]
            for role, password in ((APP_ROLE, app_password), (BACKUP_ROLE, backup_password)):
                existing = conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
                if existing:
                    raise RuntimeError("Runtime role already exists; use migration/refresh procedure, not credential rotation")
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role), sql.Literal(password)))
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
            conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema)))
            grant_runtime(conn, schema)
        db.write(provision)
    finally:
        db.close()

def grant_runtime(conn, schema="public"):
    """Run after each schema migration as its owner. Audit data is insert-only for app."""
    sc, app, backup = map(sql.Identifier, (schema, APP_ROLE, BACKUP_ROLE))
    conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(sc, app))
    conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(sc, app))
    conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(sc, backup))
    conn.execute(sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(sc, backup))
    for table in ("privacy_access_events", "schema_version", "admin_actions"):
        conn.execute(sql.SQL("REVOKE ALL ON {}.{} FROM {}").format(sc, sql.Identifier(table), app))
        permission = sql.SQL("SELECT" if table == "schema_version" else "SELECT, INSERT" if table == "admin_actions" else "INSERT")
        conn.execute(sql.SQL("GRANT {} ON {}.{} TO {}").format(permission, sc, sql.Identifier(table), app))
