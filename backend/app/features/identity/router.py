from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request, Response, Query
from psycopg.errors import UniqueViolation, ForeignKeyViolation
from psycopg.types.json import Jsonb
from . import schemas as s
from .service import (COOKIE, HASHER, authenticate, audit, identity_view, login, locked_user,
                      user_view, verify)
from app.core.security import ACTIONS, ACTION_LABELS, MODULES, validate_actions

router = APIRouter(tags=["identity"])


@router.post("/api/auth/login")
def sign_in(data:s.Login, request:Request, response:Response):
    token, csrf, user = login(request.app.state.pool,data.username,data.password,
                             request.client.host if request.client else "unknown",
                             request.headers.get("user-agent",""))
    response.set_cookie(COOKIE,token,max_age=604800,httponly=True,samesite="lax",
                        secure=request.app.state.settings.auth_origin.startswith("https://"),path="/")
    return {"user":user,"csrfToken":csrf}


@router.post("/api/auth/logout")
def sign_out(request:Request,response:Response):
    p=request.state.principal
    with request.app.state.pool.connection() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE id=%s",(p.session_id,))
        audit(conn,p.user_id,"auth.logout",p.session_id)
    response.delete_cookie(COOKIE,path="/")
    return {"saved":True}


@router.get("/api/me")
def me(request:Request):
    return identity_view(request.app.state.pool,request.state.principal,request.state.identity_row)


@router.patch("/api/me")
def profile(data:s.Profile,request:Request):
    with request.app.state.pool.connection() as conn:
        conn.execute("UPDATE users SET display_name=%s,revision=revision+1 WHERE id=%s",
                     (data.displayName,request.state.principal.user_id))
        audit(conn,request.state.principal.user_id,"profile.update")
    return {"saved":True}


@router.post("/api/me/password")
def password(data:s.ChangePassword,request:Request,response:Response):
    p=request.state.principal
    with request.app.state.pool.connection() as conn:
        row=locked_user(conn,p.user_id)
        if not verify(row["password_hash"],data.currentPassword):
            raise HTTPException(400,"当前密码不正确")
        if data.password == data.currentPassword:
            raise HTTPException(422,"新密码不能与当前密码相同")
        conn.execute("UPDATE users SET password_hash=%s,must_change_password=false,revision=revision+1 WHERE id=%s",
                     (HASHER.hash(data.password),p.user_id))
        conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(p.user_id,))
        audit(conn,p.user_id,"password.change")
    response.delete_cookie(COOKIE,path="/")
    return {"saved":True,"loginRequired":True}


@router.get("/api/me/sessions")
def sessions(request:Request):
    p=request.state.principal
    with request.app.state.pool.connection() as conn:
        rows=conn.execute("""SELECT id,user_agent,created_at,last_seen_at FROM auth_sessions
                             WHERE user_id=%s AND revoked_at IS NULL AND expires_at>now()
                             AND last_seen_at>now()-interval '8 hours' ORDER BY created_at DESC""",(p.user_id,)).fetchall()
    return {"items":rows,"currentId":p.session_id}


@router.delete("/api/me/sessions/{session_id}")
def revoke(session_id:str,request:Request):
    p=request.state.principal
    with request.app.state.pool.connection() as conn:
        if not conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE id=%s AND user_id=%s RETURNING id",
                            (session_id,p.user_id)).fetchone():
            raise HTTPException(404,"登录设备不存在")
        audit(conn,p.user_id,"session.revoke",session_id)
    return {"saved":True}


@router.get("/api/admin/overview")
def overview(request:Request,page:int=Query(0,ge=0)):
    with request.app.state.pool.connection() as conn:
        users=[user_view(r) for r in conn.execute("SELECT * FROM users ORDER BY created_at DESC,id LIMIT 25 OFFSET %s",(page*25,))]
        total=conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]
        return {"users":users, "userTotal":total,"page":page,"pageSize":25,"groups":conn.execute("SELECT * FROM permission_groups ORDER BY name").fetchall(),
                "companies":conn.execute("SELECT * FROM companies ORDER BY id").fetchall(),
                "spaces":conn.execute("SELECT * FROM spaces WHERE kind<>'legacy' ORDER BY id").fetchall(),
                "grants":conn.execute("SELECT * FROM user_space_grants").fetchall(),
                "actions":[{"module":m,"name":MODULES[m],"items":[{"id":f"{m}.{a}","name":
                    ("使用已发布技能" if m=="skills" and a=="use" else "查看目录" if m=="catalog" and a=="read" else ACTION_LABELS[a])} for a in actions]}
                           for m,actions in ACTIONS.items()]}


@router.get("/api/admin/permission-groups/{group_id}/members")
def group_members(group_id:str,request:Request,page:int=Query(0,ge=0)):
    with request.app.state.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM permission_groups WHERE id=%s",(group_id,)).fetchone():
            raise HTTPException(404,"权限组不存在")
        rows=conn.execute("""SELECT u.id,u.display_name,u.username,s.name AS space_name
              FROM user_space_grants g JOIN users u ON u.id=g.user_id JOIN spaces s ON s.id=g.space_id
              WHERE g.group_id=%s ORDER BY u.display_name,u.id,s.id LIMIT 25 OFFSET %s""",(group_id,page*25)).fetchall()
        total=conn.execute("SELECT count(*) AS n FROM user_space_grants WHERE group_id=%s",(group_id,)).fetchone()["n"]
        return {"items":rows,"total":total,"pageSize":25}


@router.post("/api/admin/users",status_code=201)
def create_user(data:s.UserCreate,request:Request):
    uid=str(uuid4())
    try:
        with request.app.state.pool.connection() as conn:
            row=conn.execute("""INSERT INTO users(id,username,display_name,password_hash,company_id)
                               VALUES(%s,%s,%s,%s,%s) RETURNING *""",
                             (uid,data.username.lower(),data.displayName,HASHER.hash(data.password),data.companyId)).fetchone()
            # Default groups are editable policies, not hard-coded member roles.
            for space,group in [(data.companyId,"members"),("shared","readers")]:
                conn.execute("INSERT INTO user_space_grants VALUES(%s,%s,%s)",(uid,group,space))
            audit(conn,request.state.principal.user_id,"user.create",uid)
            return user_view(row)
    except UniqueViolation:
        raise HTTPException(409,"用户名已存在")
    except ForeignKeyViolation:
        raise HTTPException(422,"公司或默认权限组不存在")


@router.put("/api/admin/users/{user_id}")
def update_user(user_id:str,data:s.UserUpdate,request:Request):
    try:
        with request.app.state.pool.connection() as conn:
            old=locked_user(conn,user_id,data.revision)
            if old["superadmin"] and old["active"] and (not data.active or not data.superadmin):
                count=conn.execute("SELECT count(*) AS n FROM users WHERE active AND superadmin").fetchone()["n"]
                if count<=1:
                    raise HTTPException(409,"不能停用或降级最后一个超级管理员")
            if data.companyId != old["company_id"]:
                # Changing company must never retain the previous company's grants.
                conn.execute("DELETE FROM user_space_grants WHERE user_id=%s AND space_id<>'shared'",(user_id,))
                conn.execute("INSERT INTO user_space_grants VALUES(%s,'members',%s)",(user_id,data.companyId))
            row=conn.execute("""UPDATE users SET display_name=%s,company_id=%s,active=%s,superadmin=%s,
                                revision=revision+1,permission_version=permission_version+1 WHERE id=%s RETURNING *""",
                             (data.displayName,data.companyId,data.active,data.superadmin,user_id)).fetchone()
            conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(user_id,))
            audit(conn,request.state.principal.user_id,"user.update",user_id,
                  details={"active":data.active,"superadmin":data.superadmin,"companyId":data.companyId})
            return user_view(row)
    except ForeignKeyViolation:
        raise HTTPException(422,"公司不存在")


@router.post("/api/admin/users/{user_id}/reset-password")
def reset_password(user_id:str,data:s.ResetPassword,request:Request):
    with request.app.state.pool.connection() as conn:
        locked_user(conn,user_id)
        conn.execute("""UPDATE users SET password_hash=%s,must_change_password=true,revision=revision+1,
                        permission_version=permission_version+1 WHERE id=%s""",(HASHER.hash(data.password),user_id))
        conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(user_id,))
        audit(conn,request.state.principal.user_id,"password.reset",user_id)
    return {"saved":True}


@router.put("/api/admin/users/{user_id}/grants")
def grants(user_id:str,data:s.Grants,request:Request):
    try:
        with request.app.state.pool.connection() as conn:
            locked_user(conn,user_id,data.revision)
            conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(user_id,))
            for g in data.grants:
                if g.spaceId == "legacy":
                    raise HTTPException(422,"历史隔离空间不能授权")
                conn.execute("INSERT INTO user_space_grants VALUES(%s,%s,%s)",(user_id,g.groupId,g.spaceId))
            conn.execute("UPDATE users SET permission_version=permission_version+1,revision=revision+1 WHERE id=%s",(user_id,))
            audit(conn,request.state.principal.user_id,"grants.replace",user_id,
                  details={"grants":[g.model_dump() for g in data.grants]})
    except (ForeignKeyViolation,UniqueViolation):
        raise HTTPException(422,"授权空间/权限组不存在或重复")
    return {"saved":True}


def save_group(data,request,group_id=None):
    actions=validate_actions(data.actions)
    group_id=group_id or str(uuid4())
    try:
        with request.app.state.pool.connection() as conn:
            if data.revision is None:
                conn.execute("INSERT INTO permission_groups(id,name,description,actions) VALUES(%s,%s,%s,%s)",
                             (group_id,data.name,data.description,Jsonb(actions)))
            else:
                row=conn.execute("""UPDATE permission_groups SET name=%s,description=%s,actions=%s,revision=revision+1
                                     WHERE id=%s AND revision=%s RETURNING id""",
                                  (data.name,data.description,Jsonb(actions),group_id,data.revision)).fetchone()
                if not row:
                    raise HTTPException(409,"权限组已变更，请刷新后重试")
                conn.execute("""UPDATE users SET permission_version=permission_version+1 WHERE id IN
                                (SELECT user_id FROM user_space_grants WHERE group_id=%s)""",(group_id,))
            audit(conn,request.state.principal.user_id,"group.save",group_id,details={"actions":actions})
        return {"saved":True,"id":group_id}
    except UniqueViolation:
        raise HTTPException(409,"权限组名称已存在")


@router.post("/api/admin/permission-groups",status_code=201)
def create_group(data:s.Group,request:Request):
    if data.revision is not None:
        raise HTTPException(422,"创建权限组不接受修订号")
    return save_group(data,request)


@router.put("/api/admin/permission-groups/{group_id}")
def update_group(group_id:str,data:s.Group,request:Request):
    if data.revision is None:
        raise HTTPException(422,"修改权限组必须携带修订号")
    return save_group(data,request,group_id)


@router.delete("/api/admin/permission-groups/{group_id}")
def delete_group(group_id:str,request:Request):
    if group_id in ("members","readers"):
        raise HTTPException(409,"默认权限组可以修改，但不能删除")
    try:
        with request.app.state.pool.connection() as conn:
            if not conn.execute("DELETE FROM permission_groups WHERE id=%s RETURNING id",(group_id,)).fetchone():
                raise HTTPException(404,"权限组不存在")
            audit(conn,request.state.principal.user_id,"group.delete",group_id)
    except ForeignKeyViolation:
        raise HTTPException(409,"该权限组仍有成员授权，请先移除授权")
    return {"saved":True}


@router.get("/api/admin/audit")
def audit_list(request:Request,before:int | None=None):
    with request.app.state.pool.connection() as conn:
        return {"items":conn.execute("""SELECT a.id,a.actor_id,u.display_name,a.action,a.target_id,a.space_id,a.created_at
                  FROM audit_events a LEFT JOIN users u ON u.id=a.actor_id WHERE (%s::bigint IS NULL OR a.id<%s)
                  ORDER BY a.id DESC LIMIT 50""",(before,before)).fetchall()}

