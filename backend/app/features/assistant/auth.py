"""Department-owned tickets and live authorization; no Harness credentials here."""
import json
import os
import secrets
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.core.security import Principal
from app.features.identity.service import digest


def origins():
    values = json.loads(os.getenv("DEPARTMENT_AI_ORIGINS", "{}"))
    if not isinstance(values, dict):
        raise RuntimeError("AI origins must be a mapping")
    for space, value in values.items():
        u = urlsplit(value)
        if (space not in ("zkxk","senyuan","shared") or u.path or u.query or u.fragment
            or u.username or not u.netloc or
            not (u.scheme == "https" or u.scheme == "http" and (u.hostname == "127.0.0.1" or os.getenv("DEPARTMENT_INTRANET_HTTP") == "1"))):
            raise RuntimeError("Invalid AI origin")
    if len(set(values.values())) != len(values):
        raise RuntimeError("Each space needs its own origin")
    return values


def live_principal(pool, session_id, space):
    with pool.connection() as conn:
        row = conn.execute("""SELECT u.*,s.id AS session_id FROM auth_sessions s JOIN users u ON u.id=s.user_id
          WHERE s.id=%s AND s.revoked_at IS NULL AND s.expires_at>now()
          AND s.last_seen_at>now()-interval '8 hours' AND u.active AND NOT u.must_change_password""",
          (session_id,)).fetchone()
        if not row:
            raise HTTPException(401,"部门登录已失效，请重新登录")
        grants = {}
        for g in conn.execute("""SELECT g.space_id,p.actions FROM user_space_grants g
          JOIN permission_groups p ON p.id=g.group_id WHERE g.user_id=%s""",(row["id"],)):
            grants.setdefault(g["space_id"],set()).update(g["actions"])
    p = Principal(str(row["id"]),str(row["session_id"]),row["company_id"],row["superadmin"],grants,False)
    if space not in ("zkxk","senyuan","shared"):
        raise HTTPException(403,"此空间不能使用 AI")
    p.require(space,"assistant.use")
    return p


def issue(pool, principal, space):
    live_principal(pool,principal.session_id,space)
    target = origins().get(space)
    if not target:
        raise HTTPException(503,"此空间的个人 AI 服务尚未配置")
    token = secrets.token_urlsafe(32)
    with pool.connection() as conn:
        conn.execute("DELETE FROM assistant_tickets WHERE expires_at<=now()")
        conn.execute("INSERT INTO assistant_tickets(token_hash,session_id,space_id,origin) VALUES(%s,%s,%s,%s)",
                     (digest(token),principal.session_id,space,target))
    return {"action":target+"/bootstrap","ticket":token}


def redeem(pool, ticket, origin):
    if not isinstance(ticket,str) or len(ticket)>128:
        raise HTTPException(401,"入口票据无效")
    with pool.connection() as conn:
        row=conn.execute("""DELETE FROM assistant_tickets WHERE token_hash=%s AND origin=%s
          AND expires_at>now() RETURNING *""",(digest(ticket),origin)).fetchone()
        if not row:
            raise HTTPException(401,"入口已过期或已使用，请从部门系统重新打开")
    live_principal(pool,row["session_id"],row["space_id"])
    token=secrets.token_urlsafe(32)
    with pool.connection() as conn:
        conn.execute("DELETE FROM assistant_sessions WHERE expires_at<=now()")
        conn.execute("INSERT INTO assistant_sessions(token_hash,session_id,space_id,origin) VALUES(%s,%s,%s,%s)",
                     (digest(token),row["session_id"],row["space_id"],origin))
    return token


def gateway_identity(pool, token, origin):
    if not token or len(token)>128:
        raise HTTPException(401,"请从部门系统打开 AI 助手")
    with pool.connection() as conn:
        row=conn.execute("""SELECT * FROM assistant_sessions WHERE token_hash=%s AND origin=%s
          AND expires_at>now()""",(digest(token),origin)).fetchone()
    if not row:
        raise HTTPException(401,"AI 登录已失效，请从部门系统重新打开")
    return live_principal(pool,row["session_id"],row["space_id"]),row["space_id"]
