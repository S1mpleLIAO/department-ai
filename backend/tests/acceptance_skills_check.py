"""Explicit acceptance-only six-skill release checks; temporary actors are labelled test accounts."""
import argparse,base64,json,secrets
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import closing
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.features.identity.acceptance_import import ROOT,STATE,connection_info,private_json
from app.core.security import Principal
from app.features.identity.service import authenticate,audit
from app.features.assistant.resources import call as tool,revision
from identity_server import load_environment

assert Path.cwd()==ROOT
_,DSN=connection_info()
load_environment(str(STATE/"acceptance-preview.env"))
from app.main import app
ORIGIN="http://127.0.0.1:3181"
FILE=STATE/"six-skills-fixture.json"
REPORT=STATE/"six-skills-review-results.json"
NAMES={"baoxiao","contract-risk-review","test123","test456","testli","travel-reimbursement-cn"}
CHECKS=json.loads(REPORT.read_text()) if REPORT.exists() else []
with psycopg.connect(DSN,row_factory=dict_row,options="-c default_transaction_read_only=on") as conn:
    OWNER=conn.execute("SELECT id FROM users WHERE username='liao-admin' AND active AND superadmin").fetchone()["id"]
P=Principal(OWNER,"acceptance-harness-test","zkxk",True,{},False)
def check(name,ok=True):
    assert ok,name
    CHECKS.append(name);private_json(REPORT,CHECKS);print("PASS",name,flush=True)
def api(client,method,path,body=None,status=200,space="zkxk"):
    r=client.request(method,path,json=body,headers={"Origin":ORIGIN,"X-CSRF-Token":getattr(client,"csrf","owner-test"),"X-Department-Space":space})
    assert r.status_code==status,(method,path,r.status_code,r.text[:250])
    return r
def owner_api(client,*a,**kw):
    # Fixed author principal exists only in this TestClient process; runtime auth remains real.
    with patch("app.features.identity.access.authenticate",return_value=(P,{"csrf":"owner-test"})):
        return api(client,*a,**kw)
def login(client,user):
    r=api(client,"POST","/api/auth/login",{"username":user["username"],"password":user["password"]})
    client.csrf=r.json()["csrfToken"]
def get_principal(client):
    return authenticate(app.state.pool,client.cookies.get("department_session"))[0]
def denied(p,space,name,args,status):
    try:tool(app.state.pool,p,space,name,args)
    except HTTPException as e:assert e.status_code==status,(e.status_code,status)
    else:raise AssertionError("Unexpected tool access")
def actor(admin,role,company,group):
    pw=secrets.token_urlsafe(24);new=secrets.token_urlsafe(24)
    u=owner_api(admin,"POST","/api/admin/users",{"username":"skillcheck-"+role+"-"+uuid4().hex[:6],
        "displayName":"技能技术验收-"+role+"（临时）","companyId":company,"password":pw},201).json()
    with closing(TestClient(app,base_url=ORIGIN)) as c:
        login(c,{"username":u["username"],"password":pw})
        api(c,"POST","/api/me/password",{"currentPassword":pw,"password":new})
        login(c,{"username":u["username"],"password":new})
        info=api(c,"GET","/api/me").json()["user"]
        owner_api(admin,"PUT","/api/admin/users/"+u["id"]+"/grants",{"revision":info["revision"],
            "grants":[{"spaceId":company,"groupId":group}]})
        api(c,"POST","/api/auth/logout")
    return {"id":u["id"],"username":u["username"],"password":new,"company":company}
def prepare():

    with TestClient(app,base_url=ORIGIN) as admin:
        with psycopg.connect(DSN,row_factory=dict_row,options="-c default_transaction_read_only=on") as conn:
            rows=conn.execute("SELECT id,title,status FROM review_submissions WHERE kind='skills'").fetchall()
            assert {r["title"] for r in rows}==NAMES and all(r["status"] in ("draft","submitted") for r in rows)
            assert conn.execute("SELECT count(*) AS n FROM skill_publications").fetchone()["n"]==0
        if FILE.exists():
            f=json.loads(FILE.read_text());groups=f["groups"]
        else:
            groups=[]
            for role,actions in (("审核",["skills.source_read","skills.review","skills.publish","skills.archive"]),
                                 ("调用",["assistant.use","skills.use"])):
                g=owner_api(admin,"POST","/api/admin/permission-groups",{"name":"技能技术验收-"+role+"-"+uuid4().hex[:6],
                    "description":"独立环境临时技术验收；不代表人工业务审核","actions":actions},201).json()["id"]
                groups.append(g)
            f={"groups":groups,"drafts":{r["title"]:r["id"] for r in rows},"users":{}}
            private_json(FILE,f)
        for role,company,group in (("reviewer","zkxk",groups[0]),("reader","zkxk",groups[1]),("foreign","senyuan",groups[1])):
            if role not in f["users"]:
                f["users"][role]=actor(admin,role,company,group);private_json(FILE,f)
        with closing(TestClient(app,base_url=ORIGIN)) as reviewer,closing(TestClient(app,base_url=ORIGIN)) as reader,closing(TestClient(app,base_url=ORIGIN)) as foreign:
            for c,role in ((reviewer,"reviewer"),(reader,"reader"),(foreign,"foreign")):login(c,f["users"][role])
            p=get_principal(reader);fp=get_principal(foreign)
            check("all six drafts excluded from AI",tool(app.state.pool,p,"zkxk","department_skill_list",{})==[])
            for name,id in sorted(f["drafts"].items()):
                row=owner_api(admin,"GET","/api/reviews/"+id).json()
                owner_api(admin,"POST","/api/reviews/"+id+"/publish",{"revision":row["revision"]},409)
                denied(p,"zkxk","department_skill_get",{"id":name},404)
                if row["status"]=="draft":
                    row=owner_api(admin,"POST","/api/reviews/"+id+"/submit",{"revision":row["revision"]}).json()
                owner_api(admin,"POST","/api/reviews/"+id+"/approve",{"revision":row["revision"]},403)
                api(reader,"POST","/api/reviews/"+id+"/approve",{"revision":row["revision"]},status=404)
                api(reviewer,"POST","/api/reviews/"+id+"/approve",{"revision":row["revision"]-1},status=409)
                row=api(reviewer,"POST","/api/reviews/"+id+"/approve",{"revision":row["revision"],
                    "reason":"独立环境自动化技术验收：仅验证审核发布和AI授权链路；非人工业务审核。占位技能测试后停用。"}).json()
                denied(p,"zkxk","department_skill_get",{"id":name},404)
                row=api(reviewer,"POST","/api/reviews/"+id+"/publish",{"revision":row["revision"]}).json()
                assert row["status"]=="published" and row["published_id"]==name,row
                api(reviewer,"POST","/api/reviews/"+id+"/publish",{"revision":row["revision"]})
                value=tool(app.state.pool,p,"zkxk","department_skill_get",{"id":name})
                assert value["name"]==name
                with psycopg.connect(DSN,row_factory=dict_row,options="-c default_transaction_read_only=on") as conn:
                    data=conn.execute("SELECT data FROM skill_publications WHERE space_id='zkxk' AND id=%s",(name,)).fetchone()["data"]
                for item in data["resources"]:
                    args={"id":name,"resource":item["path"]}
                    if item["path"].startswith("scripts/"):
                        denied(p,"zkxk","department_skill_get",args,403)
                    result=tool(app.state.pool,P if item["path"].startswith("scripts/") else p,"zkxk","department_skill_get",args)
                    assert base64.b64decode(result["contentBase64"])==base64.b64decode(item["contentBase64"])
                denied(fp,"senyuan","department_skill_get",{"id":name},404)
                check(name+": submit / separate reviewer / publish / immutable resources / cross-company denial")
            check("AI lists exactly all six published skills",{s["id"] for s in tool(app.state.pool,p,"zkxk","department_skill_list",{})}==NAMES)
            api(reader,"GET","/api/skills",status=403)
            api(reader,"GET","/api/skills/travel-reimbursement-cn/resources/scripts/generate_documents.py",status=403)
            check("skills.use does not grant source API access")
            denied(Principal(p.user_id,p.session_id,"zkxk",False,{"zkxk":["assistant.use"]},False),"zkxk","department_skill_list",{},403)
            check("missing skills.use denies AI skill tools")
            check("other company AI list is empty",tool(app.state.pool,fp,"senyuan","department_skill_list",{})==[])
            for c in (reviewer,reader,foreign):api(c,"POST","/api/auth/logout")
        with psycopg.connect(DSN,row_factory=dict_row,options="-c default_transaction_read_only=on") as conn:
            for id in f["drafts"].values():
                row=conn.execute("SELECT status,approved_by,owner_id,version FROM review_submissions WHERE id=%s",(id,)).fetchone()
                assert row["approved_by"]!=row["owner_id"] and row["version"]==1
                assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action='review.published' AND target_id=%s",(id,)).fetchone()["n"]==1
        check("six immutable versions; distinct reviewer; idempotent publication audit")
def finalize():
    f=json.loads(FILE.read_text())
    with TestClient(app,base_url=ORIGIN) as reviewer,closing(TestClient(app,base_url=ORIGIN)) as reader:
        login(reviewer,f["users"]["reviewer"]);login(reader,f["users"]["reader"]);p=get_principal(reader)
        before=revision(app.state.pool,p,"zkxk")
        for name in sorted(NAMES-{"travel-reimbursement-cn"}):
            api(reviewer,"DELETE","/api/skills/"+name)
            denied(p,"zkxk","department_skill_get",{"id":name},404)
        check("five placeholders disabled; AI list contains reimbursement only",
              [s["id"] for s in tool(app.state.pool,p,"zkxk","department_skill_list",{})]==["travel-reimbursement-cn"])
        check("disabling changes active session content fingerprint",before!=revision(app.state.pool,p,"zkxk"))
        for c in (reviewer,reader):api(c,"POST","/api/auth/logout")
def cleanup():
    f=json.loads(FILE.read_text())
    with psycopg.connect(DSN,row_factory=dict_row) as conn:
        for u in f["users"].values():
            conn.execute("UPDATE users SET active=false,permission_version=permission_version+1,revision=revision+1 WHERE id=%s AND username=%s",(u["id"],u["username"]))
            conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(u["id"],))
            conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["id"],))
            audit(conn,OWNER,"acceptance.test_account_disabled",u["id"],details={"run":"six-skills-20261029"})
        for g in f["groups"]:
            conn.execute("DELETE FROM permission_groups WHERE id=%s AND NOT EXISTS(SELECT 1 FROM user_space_grants WHERE group_id=%s)",(g,g))
    check("temporary test users disabled, sessions revoked and temporary grants removed")
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","finalize","cleanup"))
    {"prepare":prepare,"finalize":finalize,"cleanup":cleanup}[parser.parse_args().action]()

