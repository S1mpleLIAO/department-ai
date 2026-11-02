"""Provision ONLY the labelled isolated development database. No production env."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import quote
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app.features.identity.manage import migrate, bootstrap

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT / ".identity-state"
NAME="department-identity-dev-20261028"


def run(args):
    return subprocess.run(args,check=True,text=True,capture_output=True).stdout


def prepare():
    if not str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028"):
        raise RuntimeError("Only the isolated Aliyun worktree is supported")
    STATE.mkdir(mode=0o700,exist_ok=True)
    config=STATE/"credentials.json"
    if config.exists():
        data=json.loads(config.read_text())
        info=json.loads(run(["docker","inspect",NAME]))[0]
        if info["Config"]["Labels"].get("department.identity-development")!="true":
            raise RuntimeError("Container ownership mismatch")
        run(["docker","start",NAME])
    else:
        admin, app = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        data={"adminDsn":f"postgresql://postgres:{quote(admin)}@127.0.0.1:15433/identity_test",
              "appDsn":f"postgresql://department_app:{quote(app)}@127.0.0.1:15433/identity_test",
              "appPassword":app,"adminPassword":secrets.token_urlsafe(18)}
        # Credentials go over subprocess stdin/env file, never command output.
        env=STATE/"postgres.env"
        env.write_text("POSTGRES_PASSWORD="+admin+"\nPOSTGRES_DB=identity_test\n")
        env.chmod(0o600)
        run(["docker","run","-d","--pull=never","--name",NAME,
             "--label","department.identity-development=true","--memory","256m","--cpus","0.5",
             "-p","127.0.0.1:15433:5432","--env-file",str(env),
             "--mount","type=volume,src=department-identity-dev-20261028,dst=/var/lib/postgresql/data",
             "pgvector/pgvector:0.8.6-pg17-bookworm"])
        config.write_text(json.dumps(data))
        config.chmod(0o600)
    for _ in range(40):
        try:
            conn=psycopg.connect(data["adminDsn"],row_factory=dict_row)
            break
        except psycopg.OperationalError:
            time.sleep(1)
    else:
        raise RuntimeError("Test database did not start")
    with conn:
        migrate(conn)
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='department_app'").fetchone():
            conn.execute(sql.SQL("CREATE ROLE department_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(sql.Literal(data["appPassword"])))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("GRANT USAGE ON SCHEMA public TO department_app")
        conn.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO department_app")
        conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO department_app")
        conn.execute("REVOKE INSERT,UPDATE,DELETE ON schema_migrations FROM department_app")
        conn.execute("REVOKE UPDATE,DELETE ON audit_events FROM department_app")
        if not conn.execute("SELECT 1 FROM users WHERE superadmin").fetchone():
            bootstrap(conn,"admin","测试超级管理员",data["adminPassword"])
    env=STATE/"app.env"
    env.write_text("\n".join([
        "DEPARTMENT_DATABASE_URL="+data["appDsn"],
        "DEPARTMENT_AUTH_ORIGIN=http://127.0.0.1:3181",
        "DEPARTMENT_DATA_DIR="+str(STATE/"data"),
        "DEPARTMENT_SKILL_DIR="+str(STATE/"skills"),
        "DOCLING_BASE_URL=http://127.0.0.1:9",
        "DEPARTMENT_HARNESS_HEALTH_URL=http://127.0.0.1:9",
        "SILICONFLOW_API_KEY=",
        "METADATA_API_KEY=",
    ])+"\n")
    env.chmod(0o600)
    print("Isolated database ready on 127.0.0.1:15433. Synthetic data only; credentials retained privately.")


if __name__=="__main__":
    prepare()
