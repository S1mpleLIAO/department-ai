"""Department auth + gateway + live DB authorization; never touches production."""
import json
import os
from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4
from dataclasses import replace
from unittest.mock import patch as mock_patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from identity_check import app,config,ORIGIN,call as api,login,me,check,CHECKS,STATE
from app.features.assistant.auth import gateway_identity
from app.features.assistant.resources import call,revision
from app.features.assistant.policy import rpc,frame
from app.features.assistant.gateway import app as gateway
from app.features.assistant.runtime import Runtime

AI="http://127.0.0.1:3182"
os.environ["DEPARTMENT_AI_ORIGINS"]=json.dumps({"zkxk":AI,"senyuan":"http://127.0.0.1:3183","shared":"http://127.0.0.1:3184"})

def denied(fn,status=403):
    try: fn()
    except HTTPException as e: assert e.status_code==status,e;return
    raise AssertionError("unexpected grant")

def main():
    with TestClient(app,base_url=ORIGIN) as admin,TestClient(gateway,base_url=AI) as ai:
        login(admin,"admin",config["adminPassword"])
        prefix=uuid4().hex[:8]
        u=api(admin,"POST","/api/admin/users",{"username":"ai"+prefix,"displayName":"AI权限测试",
          "companyId":"zkxk","password":"Ai-initial-123456"},201).json()
        member=TestClient(app,base_url=ORIGIN)
        login(member,u["username"],"Ai-initial-123456")
        api(member,"POST","/api/me/password",{"currentPassword":"Ai-initial-123456","password":"Ai-personal-456789"})
        login(member,u["username"],"Ai-personal-456789")
        api(member,"POST","/api/assistant/entry",status=403)
        check("default member has no implicit AI permission",True)
        g=api(admin,"POST","/api/admin/permission-groups",{"name":"AI-"+prefix,
          "actions":["assistant.use","knowledge.read","skills.use"]},201).json()
        u=me(member)["user"]
        api(admin,"PUT","/api/admin/users/"+u["id"]+"/grants",{"revision":u["revision"],
          "grants":[{"spaceId":"zkxk","groupId":g["id"]}]})
        login(member,u["username"],"Ai-personal-456789")
        ticket=api(member,"POST","/api/assistant/entry").json()
        assert ticket["action"]==AI+"/bootstrap"
        check("department entry accepts skills use without source edit permission",True)
        api(member,"POST","/api/assistant/entry",status=403,space="senyuan")
        assert ai.post("/bootstrap",data={"ticket":ticket["ticket"]},headers={"Origin":"https://foreign.test"}).status_code==403
        assert ai.post("http://127.0.0.1:3183/bootstrap",data={"ticket":ticket["ticket"]},headers={"Origin":ORIGIN}).status_code==401
        response=ai.post("/bootstrap",data={"ticket":ticket["ticket"]},headers={"Origin":ORIGIN},follow_redirects=False)
        assert response.status_code==303 and "httponly" in response.headers["set-cookie"].lower()
        assert "token" not in response.headers["location"] and "dsh-auth" not in response.headers["set-cookie"]
        check("one-time POST bridge origin binding and server-only Harness credential",True)
        assert ai.post("/bootstrap",data={"ticket":ticket["ticket"]},headers={"Origin":ORIGIN}).status_code==401
        p,space=gateway_identity(app.state.pool,ai.cookies.get("department_ai_zkxk"),AI)
        denied(lambda:gateway_identity(app.state.pool,ai.cookies.get("department_ai_zkxk"),"http://127.0.0.1:3183"),401)
        check("ticket replay and cross-space gateway cookie rejected",True)
        with mock_patch.object(gateway.state.manager,"available_mib",return_value=0):
            assert ai.post("/ready",headers={"Origin":"https://foreign.test"}).status_code==403
            r=ai.post("/ready",headers={"Origin":AI})
            assert r.status_code==202 and r.json()["state"]=="queued" and r.json()["position"]==1
            assert ai.post("/ready",headers={"Origin":AI}).json()["position"]==1
            assert ai.post("/runtime-status",headers={"Origin":AI}).json()["state"]=="queued"
            assert ai.post("/waiting/cancel",headers={"Origin":AI}).json()["cancelled"]
            assert ai.post("/runtime-status",headers={"Origin":AI}).json()["state"]=="idle"
            check("authenticated queue status, deduplication, cancellation and origin guard",True)
        # Formal skill projection vs pending/foreign/disabled content.
        sid="approved-"+prefix
        with app.state.pool.connection() as conn:
            conn.execute("SELECT set_config('department.space','zkxk',true),set_config('department.user',%s,true)",(p.user_id,))
            # Existing review tests leave approved skills; create through full review below instead of bypassing FK.
        a=api(member,"POST","/api/assistant/entry").json()
        before=revision(app.state.pool,p,space)
        denied(lambda:call(app.state.pool,p,space,"department_processes",{}))
        denied(lambda:call(app.state.pool,p,space,"document_read",{"file_path":"/etc/passwd"}))
        denied(lambda:call(app.state.pool,p,space,"department_document_get",{"id":"unpublished-"+prefix}),404)
        assert isinstance(call(app.state.pool,p,space,"department_skill_list",{}),list)
        denied(lambda:call(app.state.pool,replace(p,grants={space:{"assistant.use"}}),space,"department_skill_list",{}))
        check("tools require live per-module grants and never accept raw filesystem paths",True)
        context=call(app.state.pool,p,space,"department_context_get",{})
        assert context["mode"]=="部门助手" and context["spaceId"]==space
        assert "department_processes" not in context["availableTools"]
        assert "department_skill_get" in context["availableTools"]
        assert set(context)=={"role","principles","defaultLanguage","draftByDefault","askWhenMissing","mode","spaceId","availableTools"}
        with mock_patch("app.features.assistant.resources.get_department_settings",return_value={"assistant":{
            "role":"最新定位","principles":["先确认模板"],"defaultLanguage":"en",
            "draftByDefault":False,"askWhenMissing":True,"skillDirectory":"/private/secret"}}):
            fresh=call(app.state.pool,p,space,"department_context_get",{})
            assert fresh["role"]=="最新定位" and fresh["defaultLanguage"]=="en"
            assert "skillDirectory" not in fresh
        denied(lambda:call(app.state.pool,replace(p,grants={}),space,"department_context_get",{}))
        check("context uses latest business settings only and preserves permission boundaries",True)
        candidate={k:"模板属性" for k in ("id","title","summary","documentType","documentPurpose","templateFamily","templateVariant","version","applicableScenario","updatedAt")}
        candidate.update(id="fixture",version="2.0",parsedText="not before confirmation",source_path="/private")
        with mock_patch("app.features.assistant.resources.keyword_reference_documents",return_value=[]), mock_patch("app.features.assistant.resources.keyword_template_candidates",return_value=[candidate]):
            hit=call(app.state.pool,p,space,"department_knowledge_search",{"query":"合同"})[0]
            assert hit["version"]=="2.0" and hit["templateVariant"]=="模板属性"
            assert "parsedText" not in hit and "source_path" not in hit
        check("template candidates retain version and variant without full text or paths",True)


        for method,args in [("settings/update",{"ns":"llm-pi-ai","patch":{}}),
                            ("settings/update",{"ns":"permission","patch":{}}),
                            ("session/create",{"request":{"cwd":"/root"}}),
                            ("session/create",{"request":{"agentPreset":"preset-creator"}}),
                            ("session/create",{"request":{"sessionId":"old-session"}}),
                            ("credentials/set",{}),("agentPresets/select",{}),
                            ("session/selectModel",{"request":{"provider":"department","model":"unknown"}})]:
            denied(lambda:rpc(method,{"type":"client-request","method":method,"payload":{"args":args}},["department-test"]))
        denied(lambda:frame({"type":"open","streamId":"x","endpoint":"shell/exec","payload":{"args":{}}}))
        frame({"type":"open","streamId":"x","endpoint":"session/follow","payload":{"args":{}}})
        check("HTTP and mux deny unknown managed models, arbitrary presets, permission/plugin bypasses",True)
        for ns,patch in (("ui-theme",{"preference":"dark","fontSize":15}),
                         ("ui-chat",{"transcriptView":"normal"}),("ui-conversation",{"busyEnter":"queue"})):
            rpc("settings/update",{"type":"client-request","method":"settings/update","payload":{"args":{"ns":ns,"patch":patch}}},["department-test"])
        for patch in ({"fontSize":1000},{"provider":"evil"},{"preference":"external-theme"}):
            denied(lambda:rpc("settings/update",{"type":"client-request","method":"settings/update",
                    "payload":{"args":{"ns":"ui-theme","patch":patch}}},["department-test"]))
        def mutate(ns,ops):
            return rpc("settings/mutate",{"type":"client-request","method":"settings/mutate",
                       "payload":{"args":{"ns":ns,"ops":ops,"expectedRevision":0}}},["department-test"])
        mutate("ui-theme",[{"op":"set","path":["fontSize"],"value":15}])
        for ns,ops in (("permission",[{"op":"set","path":["mode"],"value":"full"}]),
                       ("ui-theme",[{"op":"set","path":[],"value":{"fontSize":15}}]),
                       ("ui-theme",[{"op":"set","path":["fontSize"],"value":1000}]),
                       ("ui-theme",[{"op":"unset","path":["fontSize"]}])):
            denied(lambda:mutate(ns,ops))
        response=ai.post("/api/session/create",json={"type":"client-request","method":"credentials/set","payload":{"args":{}}},
                         headers={"Origin":AI})
        assert response.status_code==403
        check("gateway rejects mismatched RPC envelope before creating runtime",True)
        for path in ("/assets/%2e%2e/api/settings", "/assets/%252e%252e/api/settings", "/plugins/??../../secret&rev=ab"):
            assert ai.get(path).status_code==403
        check("static resource routing cannot bypass RPC authorization",True)
        with TemporaryDirectory() as folder:
            runtime=object.__new__(Runtime);runtime.root=Path(folder);runtime.fingerprint="old permissions"
            (runtime.root/".control").mkdir()
            runtime.session_epoch("old-session",create=True)
            runtime.session_epoch("old-session")
            runtime.fingerprint="new permissions or publications"
            denied(lambda:runtime.session_epoch("old-session"),409)
            runtime.session_epoch("new-session",create=True)
            runtime.session_epoch("new-session")
        check("changed authorization prevents old model context reuse",True)
        api(member,"POST","/api/auth/logout")
        assert ai.get("/starting").status_code==401
        denied(lambda:gateway_identity(app.state.pool,ai.cookies.get("department_ai_zkxk"),AI),401)
        check("department logout immediately revokes existing AI login",True)
        member.close()
    (STATE/"assistant-check-results.json").write_text(json.dumps(CHECKS,ensure_ascii=False))

if __name__=="__main__": main()
