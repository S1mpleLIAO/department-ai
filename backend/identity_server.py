"""Explicit identity release preflight / foreground supervisor; never runs migrations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
from dotenv import dotenv_values
from app.core.config import get_settings
from app.features.assistant.auth import origins
from app.features.assistant.config import ROOT, runtime_config, gateway_bindings, pool_limits

SCOPED_TABLES = ("business_processes", "process_steps", "knowledge_categories", "knowledge_purposes",
                 "knowledge_documents", "knowledge_chunks", "review_submissions", "review_versions",
                 "review_sources", "skill_publications")


def load_environment(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid():
        raise RuntimeError("Environment file must be owned by the service user and mode 0600")
    # The named file is authoritative. Never fall back to the checkout's production .env.
    for key in list(os.environ):
        if key.startswith(("DEPARTMENT_", "SILICONFLOW_", "METADATA_", "DOCLING_")):
            del os.environ[key]
    os.environ.update({k:v for k,v in dotenv_values(path, interpolate=False).items() if v is not None})
    os.environ["DEPARTMENT_ENV_FILE"] = str(path)


def database_check(settings):
    with psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            role = conn.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
            if any(role.values()):
                raise RuntimeError("Application database role has administrative privileges")
            if conn.execute("SELECT has_schema_privilege(current_user,'public','CREATE') AS allowed").fetchone()["allowed"]:
                raise RuntimeError("Application role must not create objects in public schema")
            rows = conn.execute("SELECT version,checksum FROM schema_migrations").fetchall()
            versions = {r["version"]:r["checksum"] for r in rows}
            expected = {p.stem for p in (ROOT / "backend/migrations").glob("*.sql")}
            if set(versions) != expected:
                raise RuntimeError("Database migration versions do not match this release")
            for path in sorted((ROOT / "backend/migrations").glob("*.sql")):
                if versions.get(path.stem) != hashlib.sha256(path.read_text().encode()).hexdigest():
                    raise RuntimeError("Missing or mismatched migration: " + path.stem)
            for name in SCOPED_TABLES:
                row = conn.execute("""SELECT relrowsecurity,relforcerowsecurity,
                    pg_has_role(current_user,relowner,'MEMBER') AS owner_access
                    FROM pg_class WHERE oid=to_regclass(%s)""", ("public."+name,)).fetchone()
                if not row or not row["relrowsecurity"] or not row["relforcerowsecurity"] or row["owner_access"]:
                    raise RuntimeError("RLS or non-owner role check failed: " + name)
            if conn.execute("""SELECT has_table_privilege(current_user,'schema_migrations','INSERT,UPDATE,DELETE') OR
                    has_table_privilege(current_user,'audit_events','UPDATE,DELETE') AS allowed""").fetchone()["allowed"]:
                raise RuntimeError("Application role can modify migration/audit history")
            if not conn.execute("SELECT 1 FROM users WHERE superadmin AND active LIMIT 1").fetchone():
                raise RuntimeError("Bootstrap an active superadmin before starting")
            conn.execute("SELECT set_config('department.space','legacy',true)")
            # Counts only: this is not an ownership guess or a content migration.
            counts = {name:conn.execute("SELECT count(*) AS n FROM "+name).fetchone()["n"]
                      for name in ("business_processes","knowledge_categories","knowledge_documents","skill_publications")}
    return {"migrations":len(versions), "legacy_counts":counts}


def preflight():
    settings = get_settings()
    if settings.host != "127.0.0.1" or not 1024 <= settings.port <= 65535:
        raise RuntimeError("Department backend must bind an explicit unprivileged loopback port")
    values = origins()
    ports = []
    if values:
        config = runtime_config()
        from app.features.assistant.compatibility import verify
        from app.features.assistant.storage import limits
        verify(config.harness);limits()
        pool_limits()  # Fail before starting any service when limits are invalid.
        ports = gateway_bindings(values, config.mode)
        models = json.loads(os.getenv("DEPARTMENT_AI_MODELS", "[]"))
        if not isinstance(models,list) or not models or not all(isinstance(m,str) and 0<len(m)<128 for m in models):
            raise RuntimeError("Configure the allowed AI models explicitly")
        target = urlsplit(os.getenv("DEPARTMENT_AI_MODEL_URL", ""))
        if (not target.netloc or target.username or target.query or target.fragment or
            target.scheme not in ("http","https") or not os.getenv("DEPARTMENT_AI_MODEL_KEY")):
            raise RuntimeError("Configure the private model endpoint and key")
        if config.mode == "production" and target.scheme != "https":
            raise RuntimeError("Production model transport requires HTTPS")
        if not config.root.is_dir():
            raise RuntimeError("Create the private AI state directory explicitly before startup")
        if not config.node.is_file() or not os.access(config.node,os.X_OK):
            raise RuntimeError("Configured Node executable is unavailable")
        for part in ("apps/cli/lib/bin.js","apps/web/dist/index.html","packages","vendor","native",
                     "node_modules","package.json","pnpm-workspace.yaml","tsconfig.json","tsconfig.base.json"):
            if not (config.harness/part).exists():
                raise RuntimeError("Configured Harness is not built: "+part)
        for part in ("bin/landlock-run","bin/glibc/system.node","package.json"):
            if not (ROOT/".identity-state/native-system/linux-x64"/part).is_file():
                raise RuntimeError("Build the private native sandbox first: deploy/identity/build-native-sandbox.py")
        from app.features.assistant.host_command import command
        result = subprocess.run(command("image","inspect","pgvector/pgvector:0.8.6-pg17-bookworm"),
                                capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError("The verified container image / Docker daemon is unavailable; no automatic pull")
    if settings.port in ports:
        raise RuntimeError("Department and AI gateway ports conflict")
    result = database_check(settings)
    result.update({"app_port":settings.port,"gateway_ports":ports,"ai_enabled":bool(values)})
    return result


def serve(report):
    # Probe all ports before spawning; a conflict never kills the process already using a port.
    reserved=[]
    try:
        for port in [report["app_port"],*report["gateway_ports"]]:
            sock=socket.socket();reserved.append(sock)
            # A recently closed HTTP connection may remain in TIME_WAIT after restart.
            # REUSEADDR permits that reuse but does not share an active listening port.
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(("127.0.0.1",port))
    finally:
        for sock in reserved:sock.close()
    commands=[[sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1",
               "--port",str(report["app_port"]),"--no-access-log","--forwarded-allow-ips","127.0.0.1"]]
    if report["ai_enabled"]:
        commands.append([sys.executable,"-m","app.features.assistant.gateway"])
    children=[]
    stopped=False
    def shutdown(*_):
        nonlocal stopped
        stopped=True
    old={s:signal.signal(s,shutdown) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        env={**os.environ,"PYTHONPATH":str(ROOT/"backend")}
        for command in commands:
            children.append(subprocess.Popen(command,cwd=ROOT,env=env))
        while not stopped:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("An identity service exited; stopping only sibling processes started here")
            time.sleep(.25)
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        deadline=time.monotonic()+20
        for child in children:
            try:child.wait(timeout=max(.1,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for s,handler in old.items():signal.signal(s,handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("check","serve"))
    parser.add_argument("--env-file",required=True)
    args=parser.parse_args()
    try:
        load_environment(args.env_file)
        report=preflight()
        print(json.dumps(report,ensure_ascii=False),flush=True)
        if args.action=="serve":serve(report)
    except OSError as error:
        raise SystemExit(f"Readiness OS check failed (errno={error.errno}); no migration performed")
    except (psycopg.Error,subprocess.SubprocessError):
        # DB/OS exceptions can contain DSNs and provider secrets; never echo them.
        raise SystemExit("Readiness check failed: database, file, port or Docker unavailable; no migration/restart performed")
    except (RuntimeError,ValueError) as error:
        raise SystemExit(str(error))


if __name__=="__main__":main()
