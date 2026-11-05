"""Explicit migration/bootstrap CLI. Never loads the production .env."""
import argparse
import getpass
import hashlib
import os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.core.security import ALL_ACTIONS
from app.features.catalog.space_defaults import seed_purposes
from .service import HASHER, audit


def migrate(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(281003)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        folder=Path(__file__).resolve().parents[3] / "migrations"
        for path in sorted(folder.glob("*.sql")):
            version, sql = path.stem, path.read_text()
            checksum=hashlib.sha256(sql.encode()).hexdigest()
            previous=conn.execute("SELECT checksum FROM schema_migrations WHERE version=%s",(version,)).fetchone()
            if previous:
                if previous["checksum"] != checksum:
                    raise RuntimeError("迁移文件已变化，拒绝继续："+version)
                continue
            existing=conn.execute("SELECT to_regclass('public.business_processes') AS present").fetchone()["present"]
            if version != "000_baseline" or not existing:
                conn.execute(sql)
                conn.execute("RESET ALL")
                conn.execute("SET search_path=public")
            conn.execute("INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)",(version,checksum))
        readers=sorted(a for a in ALL_ACTIONS if a.endswith((".read",".source_download",".use")))
        members=sorted(set(readers)|{"skills.source_read"}|{m+".create" for m in ("processes","knowledge","skills")})
        templates=[("readers","只读人员","查看已发布资料并使用技能，不包含技能源码访问。",readers),
                   ("members","内容提交人员","新增、维护本人草稿并提交审核，不直接发布。",members),
                   ("knowledge-reviewers","知识库审核人员","审核并发布本空间知识，不能审核自己的提交。",
                    ["catalog.read","knowledge.read","knowledge.review","knowledge.publish"]),
                   ("business-managers","业务管理人员","管理本空间业务资料、审核与发布；免审核发布默认关闭。",
                    sorted(a for a in ALL_ACTIONS if not a.endswith(".publish_direct")))]
        # Templates are initial data only; never overwrite an administrator's edits.
        for id,name,description,actions in templates:
            conn.execute("INSERT INTO permission_groups(id,name,description,actions) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (id,name,description,Jsonb(actions)))
        for space in ("zkxk","senyuan","shared"):
            seed_purposes(conn, space)


def bootstrap(conn,username,display_name,password):
    if len(password)<12 or len(password)>128:
        raise ValueError("密码需为12至128个字符")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(281002)")
        if conn.execute("SELECT 1 FROM users WHERE superadmin").fetchone():
            raise RuntimeError("已有超级管理员，禁止重复初始化")
        uid=str(uuid4())
        conn.execute("""INSERT INTO users(id,username,display_name,password_hash,company_id,superadmin)
                        VALUES(%s,%s,%s,%s,'zkxk',true)""",(uid,username.lower(),display_name,HASHER.hash(password)))
        audit(conn,uid,"system.bootstrap",uid)
        return uid


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["migrate","bootstrap"])
    parser.add_argument("--username",default="admin")
    parser.add_argument("--display-name",default="超级管理员")
    args=parser.parse_args()
    # Explicit admin DSN only. Do not reuse the app or infer production settings.
    dsn=os.environ.get("IDENTITY_MIGRATION_DATABASE_URL")
    if not dsn:
        raise SystemExit("请显式提供 IDENTITY_MIGRATION_DATABASE_URL")
    with psycopg.connect(dsn,row_factory=dict_row) as conn:
        if args.action=="migrate":
            migrate(conn)
        else:
            bootstrap(conn,args.username,args.display_name,getpass.getpass("初始密码（首次登录须修改）："))
    print("完成；没有启动或重启服务")
