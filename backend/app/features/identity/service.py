from __future__ import annotations
import hashlib
import secrets
from uuid import uuid4
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from app.core.security import Principal

HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(24))
COOKIE = "department_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify(encoded, password):
    try:
        return HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def audit(conn, actor, action, target="", space=None, details=None):
    conn.execute("INSERT INTO audit_events(actor_id,action,target_id,space_id,details) VALUES(%s,%s,%s,%s,%s)",
                 (actor, action, target, space, Jsonb(details or {})))


def user_view(row):
    return {k: row[v] for k, v in {
        "id":"id","username":"username","displayName":"display_name","companyId":"company_id",
        "active":"active","superadmin":"superadmin","mustChangePassword":"must_change_password",
        "revision":"revision"}.items()}


def authenticate(pool, token):
    if not token or len(token) > 128:
        raise HTTPException(401, "请先登录")
    with pool.connection() as conn:
        row = conn.execute("""SELECT u.*, s.id AS session_id, s.csrf FROM auth_sessions s
          JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.revoked_at IS NULL
          AND s.expires_at>now() AND s.last_seen_at>now()-interval '8 hours' AND u.active
          FOR UPDATE OF s""", (digest(token),)).fetchone()
        if not row:
            raise HTTPException(401, "登录已失效，请重新登录")
        grants = {}
        for g in conn.execute("""SELECT g.space_id,p.actions FROM user_space_grants g
                                  JOIN permission_groups p ON p.id=g.group_id WHERE g.user_id=%s""", (row["id"],)):
            grants.setdefault(g["space_id"], set()).update(g["actions"])
        conn.execute("UPDATE auth_sessions SET last_seen_at=now() WHERE id=%s", (row["session_id"],))
    p = Principal(row["id"], row["session_id"], row["company_id"], row["superadmin"], grants, row["must_change_password"])
    return p, row


def login(pool, username, password, ip, user_agent):
    username = username.lower()
    key, ipkey = digest(username), digest(ip)
    # Database lock coordinates rate limiting across workers; hash work stays bounded
    # behind a global auth lock on this small internal deployment.
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(281001)")
        conn.execute("DELETE FROM auth_attempts WHERE attempted_at < now()-interval '15 minutes'")
        attempts = conn.execute("""SELECT count(*) FILTER(WHERE username_hash=%s) AS account,
                                     count(*) FILTER(WHERE ip_hash=%s) AS ip FROM auth_attempts""", (key,ipkey)).fetchone()
        if attempts["account"] >= 5 or attempts["ip"] >= 30:
            raise HTTPException(429, "尝试次数过多，请15分钟后重试")
        row = conn.execute("SELECT * FROM users WHERE username=%s FOR UPDATE", (username,)).fetchone()
        valid = verify(row["password_hash"] if row else DUMMY_HASH, password)
        if not row or not valid or not row["active"]:
            conn.execute("INSERT INTO auth_attempts(username_hash,ip_hash) VALUES(%s,%s)", (key,ipkey))
            result = None
        else:
            if HASHER.check_needs_rehash(row["password_hash"]):
                conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (HASHER.hash(password), row["id"]))
            token, csrf, sid = secrets.token_urlsafe(32), secrets.token_urlsafe(32), str(uuid4())
            conn.execute("""INSERT INTO auth_sessions(id,token_hash,csrf,user_id,expires_at,user_agent)
                            VALUES(%s,%s,%s,%s,now()+interval '7 days',%s)""",
                         (sid,digest(token),csrf,row["id"],user_agent[:200]))
            conn.execute("DELETE FROM auth_attempts WHERE username_hash=%s", (key,))
            audit(conn,row["id"],"auth.login",sid)
            result = (token, csrf, user_view(row))
    if result is None:
        raise HTTPException(401, "用户名或密码不正确，或账号不可用")
    return result


def identity_view(pool, principal, row):
    from app.features.assistant.auth import origins
    with pool.connection() as conn:
        spaces = conn.execute("SELECT id,name,kind,company_id FROM spaces ORDER BY id").fetchall()
        company = conn.execute("SELECT name FROM companies WHERE id=%s", (row["company_id"],)).fetchone()
    return {"user":user_view(row), "companyName":company["name"], "csrfToken":row["csrf"],
            "spaces":[s for s in spaces if principal.superadmin or s["id"] in principal.grants],
            "permissions":{s:sorted(actions) for s,actions in principal.grants.items()},
            "capabilities":{"review":True,"assistant":bool(origins())}}


def locked_user(conn, user_id, revision=None):
    conn.execute("SELECT pg_advisory_xact_lock(281002)")
    row = conn.execute("SELECT * FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    if revision is not None and revision != row["revision"]:
        raise HTTPException(409, "用户已被其他管理员修改，请刷新后重试")
    return row

