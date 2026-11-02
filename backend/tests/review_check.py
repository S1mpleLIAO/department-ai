"""Real HTTP/PostgreSQL review regressions. Isolated synthetic data only."""
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import base64
import json
import psycopg
from fastapi.testclient import TestClient
from identity_check import app, config, STATE, ORIGIN, call, login, me, check, CHECKS
from app.core.database import StoreError
from app.features.identity.service import authenticate
from app.core.security import ScopedPool
from app.features.search.store import keyword_template_candidates
from app.features.reviews.service import available_reviewer


def main():
    with TestClient(app,base_url=ORIGIN) as admin:
        login(admin,"admin",config["adminPassword"])
        prefix=uuid4().hex[:8]
        people=[]
        for suffix,company in [("author","zkxk"),("peer","zkxk"),("other","senyuan"),("reviewer","zkxk")]:
            user=call(admin,"POST","/api/admin/users",{"username":prefix+suffix,"displayName":"审核测试"+suffix,
                      "companyId":company,"password":"Review-initial-pass-123"},201).json()
            client=TestClient(app,base_url=ORIGIN)
            login(client,user["username"],"Review-initial-pass-123")
            call(client,"POST","/api/me/password",{"currentPassword":"Review-initial-pass-123","password":"Review-personal-pass-456"})
            login(client,user["username"],"Review-personal-pass-456")
            people.append((user,client))
        (au,a),(pu,peer),(ou,other),(ru,reviewer)=people
        ru=me(reviewer)["user"]
        actions=[k+"."+v for k in ("processes","knowledge","skills") for v in
                 (["source_read","review","publish"] if k=="skills" else ["read","review","publish"])]
        group=call(admin,"POST","/api/admin/permission-groups",{"name":"审核发布"+prefix,"actions":actions},201).json()
        call(admin,"PUT","/api/admin/users/"+ru["id"]+"/grants",
             {"revision":ru["revision"],"grants":[{"spaceId":"zkxk","groupId":group["id"]}]})
        login(reviewer,ru["username"],"Review-personal-pass-456")
        def api(client,method,path,body=None,status=200,space="zkxk"):
            return call(client,method,path,body,status,space).json()
        def move(client,row,action,reason=""):
            return api(client,"POST","/api/reviews/"+row["id"]+"/"+action,{"revision":row["revision"],"reason":reason})
        process={"name":"待审核流程"+prefix,"steps":[{"name":"检查","objective":"人工确认"}]}
        draft_id=str(uuid4())
        row=api(a,"POST","/api/reviews",{"id":draft_id,"kind":"processes","data":process},201)
        same=api(a,"POST","/api/reviews",{"id":draft_id,"kind":"processes","data":process},201)
        check("draft creation retry is idempotent",row["id"]==same["id"])
        check("private draft absent from live processes",not any(p["name"]==process["name"] for p in api(a,"GET","/api/processes")))
        api(peer,"GET","/api/reviews/"+row["id"],status=404)
        api(other,"GET","/api/reviews/"+row["id"],status=404,space="senyuan")
        check("same-company peers and other-company readers cannot see drafts",True)
        api(a,"POST","/api/reviews/"+row["id"]+"/approve",{"revision":row["revision"]},403)
        api(a,"POST","/api/reviews/"+row["id"]+"/publish",{"revision":row["revision"]},403)
        api(a,"PUT","/api/reviews/"+row["id"],{"revision":row["revision"],"data":process,"status":"published"},422)
        check("ordinary member cannot approve publish or forge status",True)
        with psycopg.connect(config["adminDsn"]) as conn:
            # Roll back all temporary account changes; no account is left disabled.
            conn.execute("UPDATE users SET active=false WHERE id<>%s",(au["id"],))
            check("no reviewer excludes the author and disabled accounts",not available_reviewer(conn,"zkxk","processes",au["id"]))
            conn.execute("UPDATE users SET active=true WHERE id=%s",(ru["id"],))
            check("reviewer availability respects module and space",available_reviewer(conn,"zkxk","processes",au["id"]) and not available_reviewer(conn,"senyuan","processes",au["id"]))
            conn.execute("UPDATE users SET must_change_password=true WHERE id=%s",(ru["id"],))
            check("incomplete reviewer account is not available",not available_reviewer(conn,"zkxk","processes",au["id"]))
            conn.rollback()
        with patch("app.features.reviews.service.available_reviewer",return_value=False):
            api(a,"POST","/api/reviews/"+row["id"]+"/submit",{"revision":row["revision"]},409)
        check("missing reviewer leaves draft editable",api(a,"GET","/api/reviews/"+row["id"])["status"]=="draft")
        row=move(a,row,"submit")
        api(a,"PUT","/api/reviews/"+row["id"],{"revision":row["revision"],"data":process},409)
        api(reviewer,"POST","/api/reviews/"+row["id"]+"/publish",{"revision":row["revision"]},409)
        api(reviewer,"POST","/api/reviews/"+row["id"]+"/reject",{"revision":row["revision"]},400)
        check("submitted content locked and approval required",True)
        row=move(reviewer,row,"reject","请补充执行说明")
        updated={**process,"description":"驳回后补充"}
        row=api(a,"PUT","/api/reviews/"+row["id"],{"revision":row["revision"],"data":updated})
        row=move(a,row,"submit")
        check("rejection can be edited and resubmitted as a new version",row["version"]==2)
        with psycopg.connect(config["adminDsn"]) as conn:
            old=conn.execute("SELECT payload FROM review_versions WHERE submission_id=%s AND number=1",(row["id"],)).fetchone()[0]
            check("previous submission snapshot retained",old.get("description")=="")
            try:
                with conn.transaction():
                    conn.execute("UPDATE review_versions SET payload='{}' WHERE submission_id=%s",(row["id"],))
                raise AssertionError("immutable trigger absent")
            except psycopg.errors.RaiseException:
                check("database prevents editing submitted versions",True)
        stale=row["revision"]
        row=move(reviewer,row,"approve")
        api(reviewer,"POST","/api/reviews/"+row["id"]+"/approve",{"revision":stale},409)
        check("stale review prevented and approval alone is not publication",not any(p["name"]==process["name"] for p in api(a,"GET","/api/processes")))
        row=move(reviewer,row,"publish")
        result=move(reviewer,row,"publish")
        matches=[p for p in api(a,"GET","/api/processes") if p["name"]==process["name"]]
        check("reviewer can publish without direct-write permission; retry creates one record",row["status"]=="published" and result["published_id"]==row["published_id"] and len(matches)==1)
        # Even superadmin cannot approve their own draft.
        own=api(admin,"POST","/api/reviews",{"kind":"processes","data":process},201)
        own=move(admin,own,"submit")
        api(admin,"POST","/api/reviews/"+own["id"]+"/approve",{"revision":own["revision"]},403)
        check("self-approval denied including superadmin",True)
        # File is frozen before deleting the temporary preview.
        preview=api(a,"POST","/api/knowledge/preview",{"fileName":"review.txt","mimeType":"text/plain",
                    "fileBase64":base64.b64encode(b"synthetic review source").decode()})["id"]
        title="reviewsearch"+prefix
        metadata={"title":title,"purposeId":"generation-template","templateFamily":"测试合同","chunks":[]}
        doc=api(a,"POST","/api/reviews",{"kind":"knowledge","previewId":preview,"data":metadata},201)
        api(a,"DELETE","/api/knowledge/previews/"+preview,status=404)
        check("draft source survives preview cleanup",call(a,"GET","/api/reviews/"+doc["id"]+"/source",space="zkxk").content==b"synthetic review source")
        api(peer,"GET","/api/reviews/"+doc["id"]+"/source",status=404)
        p,_=authenticate(app.state.pool,admin.cookies.get("department_session"))
        pool=ScopedPool(app.state.pool,p,"zkxk")
        check("unpublished knowledge excluded from retrieval",not keyword_template_candidates(pool,[title],20))
        doc=move(a,doc,"submit");doc=move(reviewer,doc,"approve")
        with patch("app.features.documents.publication.embed_texts",side_effect=StoreError("测试向量服务暂不可用")):
            doc=move(reviewer,doc,"publish")
        check("embedding failure preserves approval and publishes nothing",doc["status"]=="publish_failed" and not keyword_template_candidates(pool,[title],20))
        with patch("app.features.documents.publication.embed_texts",return_value=[[0.01]*1024]):
            doc=move(reviewer,doc,"publish")
        check("retry publishes reviewed knowledge with searchable vector",doc["status"]=="published" and len(keyword_template_candidates(pool,[title],20))==1)
        check("published original is downloadable",call(a,"GET","/api/documents/"+doc["published_id"]+"/source",space="zkxk").content==b"synthetic review source")
        # Skills and all attachments publish atomically through a DB record.
        skill={"skill":{"name":"review-skill-"+prefix,"description":"测试技能","instructions":"只读检查","enabled":True},
               "resources":[{"path":"references/note.txt","contentBase64":base64.b64encode(b"reviewed resource").decode()}]}
        bad={**skill,"resources":[{"path":"assets/../secret","contentBase64":"YQ=="}]}
        api(a,"POST","/api/reviews",{"kind":"skills","data":bad},400)
        sk=api(a,"POST","/api/reviews",{"kind":"skills","data":skill},201)
        check("draft skill absent from available skills",not any(s["id"]==skill["skill"]["name"] for s in api(a,"GET","/api/skills")))
        sk=move(a,sk,"submit");sk=move(reviewer,sk,"approve")
        def parallel_publish(_):
            c=TestClient(app,base_url=ORIGIN);c.cookies.update(reviewer.cookies);c.csrf=reviewer.csrf
            return move(c,sk,"publish")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(parallel_publish,[0,1]))
        check("concurrent skill publication creates exactly one live skill",
              all(r["status"]=="published" for r in results) and len([s for s in api(a,"GET","/api/skills") if s["id"]==skill["skill"]["name"]])==1)
        check("approved skill attachment downloadable",call(a,"GET","/api/skills/"+skill["skill"]["name"]+"/resources/references/note.txt",space="zkxk").content==b"reviewed resource")
        api(other,"GET","/api/skills/"+skill["skill"]["name"]+"/resources/references/note.txt",status=404,space="senyuan")
        api(a,"PUT","/api/skills/"+skill["skill"]["name"],skill["skill"],403)
        api(admin,"DELETE","/api/skills/"+skill["skill"]["name"])
        check("archiving reviewed skill retains source and disables use",next(s for s in api(a,"GET","/api/skills") if s["id"]==skill["skill"]["name"])["enabled"] is False)
        # Remove reviewer capabilities; the old session must lose access immediately.
        group=next(g for g in call(admin,"GET","/api/admin/overview").json()["groups"] if g["id"]==group["id"])
        call(admin,"PUT","/api/admin/permission-groups/"+group["id"],
             {"name":"审核发布"+prefix,"actions":["processes.read"],"revision":group["revision"]})
        api(reviewer,"GET","/api/reviews/"+own["id"],status=404)
        check("permission removal takes effect on existing reviewer session",True)
        check("review list is paginated",len(api(admin,"GET","/api/reviews?mode=all")["items"])<=20)
        (STATE/"review-check-results.json").write_text(json.dumps(CHECKS,ensure_ascii=False,indent=2))
        browser=STATE/"review-browser.json"
        browser.write_text(json.dumps({"username":au["username"],"password":"Review-personal-pass-456"}))
        browser.chmod(0o600)
        print(f"review-check: {len(CHECKS)} checks passed")


if __name__=="__main__":
    main()
