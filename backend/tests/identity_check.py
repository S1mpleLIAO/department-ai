"""Real HTTP + PostgreSQL authorization regression; synthetic isolated DB only."""
import json
import base64
import os
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values
import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/".identity-state"
config=json.loads((STATE/"credentials.json").read_text())
assert "@127.0.0.1:15433/identity_test" in config["adminDsn"]
os.environ.update({k:v for k,v in dotenv_values(STATE/"app.env").items() if v is not None})

from fastapi.testclient import TestClient
from app.main import app
from app.features.identity.manage import migrate
from app.core.security import ScopedPool, validate_actions
from app.features.identity.service import authenticate
from app.features.documents.store import save_document
from app.features.search.store import keyword_template_candidates

ORIGIN="http://127.0.0.1:3181"
CHECKS=[]
def check(name,condition):
    assert condition,name
    CHECKS.append(name)
    print("PASS",name,flush=True)

def call(client,method,path,body=None,status=200,space=None):
    headers={"Origin":ORIGIN}
    if getattr(client,"csrf",None): headers["X-CSRF-Token"]=client.csrf
    if space: headers["X-Department-Space"]=space
    r=client.request(method,path,json=body,headers=headers)
    assert r.status_code==status,(method,path,r.status_code,r.text[:400])
    return r

def login(client,name,password):
    r=call(client,"POST","/api/auth/login",{"username":name,"password":password})
    client.csrf=r.json()["csrfToken"]
    return r

def me(client):
    return call(client,"GET","/api/me").json()


def main():
    # Repeat migration validates checksum + idempotence, never against production.
    with psycopg.connect(config["adminDsn"],row_factory=dict_row) as conn:
        migrate(conn)
    with psycopg.connect(config["adminDsn"],row_factory=dict_row) as conn:
        conn.execute("UPDATE permission_groups SET actions='[\"knowledge.read\"]' WHERE id='readers'")
        migrate(conn)
        check("repeated migration preserves administrator-customized groups",conn.execute("SELECT actions FROM permission_groups WHERE id='readers'").fetchone()["actions"]==["knowledge.read"])
        check("new permission templates have valid dependencies",all(validate_actions(r["actions"]) for r in conn.execute("SELECT actions FROM permission_groups WHERE id IN ('knowledge-reviewers','business-managers')")))
        conn.rollback()
    with TestClient(app,base_url=ORIGIN) as admin:
        check("anonymous business APIs denied",call(admin,"GET","/api/state",status=401).status_code==401)
        r=login(admin,"admin",config["adminPassword"])
        check("HttpOnly SameSite session cookie", "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"])
        if me(admin)["user"]["mustChangePassword"]:
            call(admin,"GET","/api/state",status=403)
            new=uuid4().hex
            call(admin,"POST","/api/me/password",{"currentPassword":config["adminPassword"],"password":new})
            config["adminPassword"]=new
            (STATE/"credentials.json").write_text(json.dumps(config))
            login(admin,"admin",new)
        check("first-password gate and reauthentication",not me(admin)["user"]["mustChangePassword"])
        prefix=uuid4().hex[:8]
        users=[]
        for company in ("zkxk","senyuan"):
            user=call(admin,"POST","/api/admin/users",{"username":prefix+company,"displayName":company+"成员","companyId":company,"password":"Test-initial-password-123"},201).json()
            users.append(user)
        clients=[]
        for user in users:
            client=TestClient(app,base_url=ORIGIN)
            login(client,user["username"],"Test-initial-password-123")
            call(client,"POST","/api/me/password",{"currentPassword":"Test-initial-password-123","password":"Test-personal-password-456"})
            login(client,user["username"],"Test-personal-password-456")
            clients.append(client)
        a,b=clients
        check("members see only own company and shared", {s["id"] for s in me(a)["spaces"]}=={"zkxk","shared"})
        call(a,"GET","/api/admin/overview",status=403)
        call(a,"GET","/api/admin/permission-groups/members/members",status=403)
        members=call(admin,"GET","/api/admin/permission-groups/members/members").json()
        check("group members endpoint is admin-only paginated and contains no credentials",
              members["total"]>=2 and len(members["items"])<=25 and
              all(set(x)=={"id","display_name","username","space_name"} for x in members["items"]))
        call(a,"GET","/api/state",status=403,space="senyuan")
        check("client company and forged user headers cannot grant access",
              a.get("/api/state",headers={"X-Department-Space":"senyuan","X-User-Id":me(admin)["user"]["id"]}).status_code==403)
        check("CSRF required",admin.post("/api/categories",json={"name":"bad"},headers={"Origin":ORIGIN}).status_code==403)
        check("untrusted Origin rejected",admin.post("/api/categories",json={"name":"bad"},headers={"Origin":"https://evil.invalid","X-CSRF-Token":admin.csrf}).status_code==403)
        check("member create does not imply direct publication",call(a,"POST","/api/processes",{"name":"不可发布"},status=403,space="zkxk").status_code==403)
        ca=call(admin,"POST","/api/categories",{"name":"同名目录"+prefix},201,"zkxk").json()["category"]
        cb=call(admin,"POST","/api/categories",{"name":"同名目录"+prefix},201,"senyuan").json()["category"]
        call(admin,"POST","/api/categories",{"name":"越空间子目录","parentId":cb["id"]},404,"zkxk")
        pa=call(admin,"POST","/api/processes",{"name":"A流程"+prefix,"steps":[{"name":"A步骤","objective":"隔离验证"}]},201,"zkxk").json()["process"]
        pb=call(admin,"POST","/api/processes",{"name":"B流程"+prefix,"steps":[{"name":"B步骤","objective":"隔离验证"}]},201,"senyuan").json()["process"]
        al=call(a,"GET","/api/state",space="zkxk").json()
        check("aggregate state and counts scoped before SQL results",pa["id"] in {p["id"] for p in al["processes"]} and pb["id"] not in {p["id"] for p in al["processes"]} and cb["id"] not in {x["id"] for x in al["categories"]})
        check("same IDs in other space cannot be changed",call(admin,"PUT","/api/processes/"+pb["id"],pb,status=404,space="zkxk").status_code==404)
        # Persist fixtures through the real scoped stores, then test HTTP and retrieval.
        principal,_=authenticate(app.state.pool,admin.cookies.get("department_session"))
        ids={}
        for space,category in [("zkxk",ca["id"]),("senyuan",cb["id"]),("shared",None)]:
            docid=uuid4().hex; ids[space]=docid
            directory=STATE/"data"/"spaces"/space/"documents";directory.mkdir(parents=True,exist_ok=True)
            source=directory/(docid+".txt");source.write_text("仅属于"+space)
            doc={"id":docid,"title":"searchfixture"+prefix,"categoryId":category,"originalName":"test.txt",
                 "originalPath":str(source),"mimeType":"text/plain","status":"effective","purposeId":"generation-template",
                 "isGenerationTemplate":True,"isReferenceKnowledge":False,"documentType":"测试","keywords":[],
                 "outline":[],"templateFamily":"测试","templateVariant":"","version":"1","applicableProcessId":"",
                 "applicableStepId":"","applicableScenario":"","summary":"测试","parsedText":"仅属于"+space,"chunkSettings":{}}
            save_document(ScopedPool(app.state.pool,principal,space),doc,[],[0.01]*1024,"test")
        call(a,"GET","/api/documents/"+ids["senyuan"],status=404,space="zkxk")
        call(a,"GET","/api/documents/"+ids["senyuan"]+"/source",status=404,space="zkxk")
        check("authorized file download",call(a,"GET","/api/documents/"+ids["zkxk"]+"/source",space="zkxk").text=="仅属于zkxk")
        check("shared access explicit",call(a,"GET","/api/documents/"+ids["shared"],space="shared").status_code==200)
        result=keyword_template_candidates(ScopedPool(app.state.pool,principal,"zkxk"),["searchfixture"+prefix],20)
        check("retrieval cannot return other-company candidates",{x["id"] for x in result}=={ids["zkxk"]})
        with app.state.pool.connection() as conn:
            check("unscoped database access fails closed",conn.execute("SELECT count(*) AS n FROM knowledge_documents").fetchone()["n"]==0)
        # File previews belong to both a company and the uploader.
        preview=call(a,"POST","/api/knowledge/preview",{"fileName":"isolation.txt","mimeType":"text/plain","fileBase64":base64.b64encode(b"synthetic preview").decode()},space="zkxk").json()["id"]
        call(admin,"POST","/api/knowledge/previews/"+preview+"/analyze",status=404,space="zkxk")
        call(b,"DELETE","/api/knowledge/previews/"+preview,status=404,space="senyuan")
        call(a,"DELETE","/api/knowledge/previews/"+preview,space="zkxk")
        check("preview files isolated by company and uploader",True)
        skill=call(admin,"POST","/api/skills",{"name":"isolation-"+prefix,"description":"synthetic","instructions":"private instructions","enabled":True},201,"zkxk").json()["skill"]
        call(admin,"PUT","/api/skills/"+skill["id"]+"/resources/references/test.txt",{"contentBase64":base64.b64encode(b"private resource").decode()},space="zkxk")
        call(a,"GET","/api/skills/"+skill["id"]+"/resources/references/test.txt",space="zkxk")
        call(b,"GET","/api/skills/"+skill["id"]+"/resources/references/test.txt",status=404,space="senyuan")
        check("skill resources isolated by company",True)
        other_session=call(b,"GET","/api/me/sessions").json()["currentId"]
        call(a,"DELETE","/api/me/sessions/"+other_session,status=404)
        check("cannot revoke another user's login",True)
        call(admin,"DELETE","/api/documents/"+ids["zkxk"],space="zkxk")
        check("archive preserves source while removing active retrieval",call(a,"GET","/api/documents/"+ids["zkxk"]+"/source",space="zkxk").status_code==200 and not keyword_template_candidates(ScopedPool(app.state.pool,principal,"zkxk"),["searchfixture"+prefix],20))
        call(admin,"DELETE","/api/processes/"+pa["id"],space="zkxk")
        check("process archive removes active listing",pa["id"] not in {p["id"] for p in call(a,"GET","/api/processes",space="zkxk").json()})
        # Narrow group, live revocation, optimistic locking and dependency validation.
        group=call(admin,"POST","/api/admin/permission-groups",{"name":"临时读取"+prefix,"actions":["processes.read"]},201).json()["id"]
        overview=call(admin,"GET","/api/admin/overview").json()
        target=next(u for u in overview["users"] if u["id"]==users[0]["id"])
        call(admin,"PUT","/api/admin/users/"+target["id"]+"/grants",{"revision":target["revision"],"grants":[{"spaceId":"zkxk","groupId":group}]})
        call(a,"GET","/api/documents",status=403,space="zkxk")
        check("permission change effective on existing session",call(a,"GET","/api/state",space="zkxk").json()["documents"]==[])
        call(admin,"PUT","/api/admin/users/"+target["id"]+"/grants",{"revision":target["revision"],"grants":[]},409)
        call(admin,"POST","/api/admin/permission-groups",{"name":"bad","actions":["processes.edit_any"]},422)
        call(admin,"POST","/api/admin/permission-groups",{"name":"bad","actions":["system.superadmin"]},422)
        check("unknown permissions, missing dependencies, stale revisions rejected",True)
        group2=call(admin,"POST","/api/admin/permission-groups",{"name":"知识读取"+prefix,"actions":["knowledge.read"]},201).json()["id"]
        call(admin,"PUT","/api/admin/users/"+target["id"]+"/grants",{"revision":target["revision"]+1,"grants":[{"spaceId":"zkxk","groupId":group},{"spaceId":"zkxk","groupId":group2},{"spaceId":"shared","groupId":group}]})
        call(a,"GET","/api/documents",space="zkxk")
        call(a,"GET","/api/processes",space="zkxk")
        call(a,"GET","/api/documents",status=403,space="shared")
        check("permission union stays inside each granted space",True)
        sa=me(admin)["user"]
        call(admin,"PUT","/api/admin/users/"+sa["id"],{"displayName":sa["displayName"],"companyId":sa["companyId"],"active":False,"superadmin":True,"revision":sa["revision"]},409)
        check("last active superadmin protected",True)
        call(admin,"POST","/api/admin/users/"+users[1]["id"]+"/reset-password",{"password":"Reset-initial-password-789"})
        call(b,"GET","/api/me",status=401)
        check("reset revokes existing sessions",True)
        login(b,users[1]["username"],"Reset-initial-password-789")
        call(b,"GET","/api/state",status=403,space="senyuan")
        check("reset forces password change before business access",me(b)["user"]["mustChangePassword"])
        blocked=me(b)["user"]
        call(admin,"PUT","/api/admin/users/"+blocked["id"],{"displayName":blocked["displayName"],"companyId":"senyuan","active":False,"superadmin":False,"revision":blocked["revision"]})
        call(b,"GET","/api/me",status=401)
        call(b,"POST","/api/auth/login",{"username":blocked["username"],"password":"Reset-initial-password-789"},401)
        check("disabled accounts lose sessions and cannot log in",True)
        with psycopg.connect(config["adminDsn"]) as conn:
            conn.execute("UPDATE auth_sessions SET last_seen_at=now()-interval '9 hours' WHERE user_id=%s",(target["id"],))
        call(a,"GET","/api/me",status=401)
        login(a,users[0]["username"],"Test-personal-password-456")
        check("idle expiry requires fresh login",True)
        check("shared MCP entry closed",a.get("/mcp").status_code==403)
        call(a,"POST","/api/auth/logout")
        call(a,"GET","/api/me",status=401)
        for n in range(5):
            call(a,"POST","/api/auth/login",{"username":"missing"+prefix,"password":"incorrect"},401)
        call(a,"POST","/api/auth/login",{"username":"missing"+prefix,"password":"incorrect"},429)
        check("logout and login rate limit",True)
        check("audit records produced",len(call(admin,"GET","/api/admin/audit").json()["items"])>0)
        for client in clients:client.close()
    (STATE/"identity-check-results.json").write_text(json.dumps(CHECKS,ensure_ascii=False,indent=2))
    print(f"identity-check: {len(CHECKS)} checks passed")

if __name__=="__main__": main()
