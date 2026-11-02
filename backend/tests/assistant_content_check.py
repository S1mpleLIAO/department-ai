"""Approved resource projections through the same tool service used by Harness."""
import base64
import json
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
from identity_check import app,config,ORIGIN,call as api,login,me,check,CHECKS,STATE
from app.features.identity.service import authenticate
from app.features.assistant.resources import call,revision

def main():
    with TestClient(app,base_url=ORIGIN) as admin:
        login(admin,"admin",config["adminPassword"])
        prefix=uuid4().hex[:8]
        reviewer=api(admin,"POST","/api/admin/users",{"username":"air"+prefix,"displayName":"AI资料审核员",
          "companyId":"zkxk","password":"Reviewer-initial-123"},201).json()
        rc=TestClient(app,base_url=ORIGIN);login(rc,reviewer["username"],"Reviewer-initial-123")
        api(rc,"POST","/api/me/password",{"currentPassword":"Reviewer-initial-123","password":"Reviewer-personal-456"})
        login(rc,reviewer["username"],"Reviewer-personal-456")
        reviewer=me(rc)["user"]
        group=api(admin,"POST","/api/admin/permission-groups",{"name":"ai-review-"+prefix,
          "actions":["knowledge.read","knowledge.review","knowledge.publish","skills.source_read","skills.review","skills.publish"]},201).json()
        api(admin,"PUT","/api/admin/users/"+reviewer["id"]+"/grants",{"revision":reviewer["revision"],
          "grants":[{"spaceId":s,"groupId":group["id"]} for s in ("zkxk","senyuan","shared")]})
        login(rc,reviewer["username"],"Reviewer-personal-456")
        def publish(kind,data,space="zkxk",preview=None):
            body={"kind":kind,"data":data}
            if preview: body["previewId"]=preview
            row=api(admin,"POST","/api/reviews",body,201,space).json()
            for actor,action in ((admin,"submit"),(rc,"approve"),(rc,"publish")):
                with patch("app.features.documents.publication.embed_texts",return_value=[[.01]*1024]):
                    row=api(actor,"POST","/api/reviews/"+row["id"]+"/"+action,{"revision":row["revision"]},space=space).json()
            assert row["status"]=="published",row
            return row["published_id"]
        def skill(name,space="zkxk"):
            return publish("skills",{"skill":{"name":name,"description":"审核后的技能 "+name,"instructions":"这是已批准的部门规则"},
              "resources":[{"path":"references/check.txt","contentBase64":base64.b64encode(b"approved attachment").decode()}]},space)
        own=skill("own-"+prefix)
        foreign=skill("foreign-"+prefix,"senyuan")
        disabled=skill("disabled-"+prefix)
        api(admin,"DELETE","/api/skills/"+disabled)
        pending=api(admin,"POST","/api/reviews",{"kind":"skills","data":{"skill":{"name":"pending-"+prefix,
          "description":"未发布","instructions":"不得进入 AI"},"resources":[]}},201).json()
        preview=api(admin,"POST","/api/knowledge/preview",{"fileName":"approved.txt","mimeType":"text/plain",
          "fileBase64":base64.b64encode(("approved "+prefix).encode()).decode()}).json()["id"]
        doc=publish("knowledge",{"title":"approved "+prefix,"purposeId":"generation-template","templateFamily":"测试","chunks":[]},preview=preview)
        fixture=json.loads((STATE/"assistant-fixture.json").read_text())
        user=TestClient(app,base_url=ORIGIN);login(user,fixture["username"],fixture["password"])
        p,_=authenticate(app.state.pool,user.cookies.get("department_session"))
        skills=call(app.state.pool,p,"zkxk","department_skill_list",{})
        ids={s["id"] for s in skills}
        check("AI sees own approved skills, excludes other company/draft/disabled",own in ids and not {foreign,disabled,"pending-"+prefix}&ids)
        resource=call(app.state.pool,p,"zkxk","department_skill_get",{"id":own,"resource":"references/check.txt"})
        check("AI skill resource is the reviewed immutable payload",base64.b64decode(resource["contentBase64"])==b"approved attachment")
        for id in (foreign,disabled,"pending-"+prefix):
            try: call(app.state.pool,p,"zkxk","department_skill_get",{"id":id})
            except HTTPException as e: assert e.status_code==404
            else: raise AssertionError("unapproved content leaked")
        results=call(app.state.pool,p,"zkxk","department_knowledge_search",{"query":prefix})
        assert doc in {d["id"] for d in results}
        text=call(app.state.pool,p,"zkxk","department_document_get",{"id":doc})
        check("AI retrieves only the published document projection",text["parsed_text"]=="approved "+prefix)
        before=revision(app.state.pool,p,"zkxk")
        api(admin,"DELETE","/api/documents/"+doc)
        check("withdrawal changes runtime authorization fingerprint",before!=revision(app.state.pool,p,"zkxk"))
        try: call(app.state.pool,p,"zkxk","department_document_get",{"id":doc})
        except HTTPException as e: assert e.status_code==404
        else: raise AssertionError("withdrawn content leaked")
        check("withdrawn knowledge immediately unavailable to AI tool",True)
        fixture.update({"approvedSkill":own,"foreignSkill":foreign,"pendingSkill":"pending-"+prefix})
        (STATE/"assistant-fixture.json").write_text(json.dumps(fixture))
        user.close();rc.close()
    (STATE/"assistant-content-results.json").write_text(json.dumps(CHECKS,ensure_ascii=False))

if __name__=="__main__": main()
