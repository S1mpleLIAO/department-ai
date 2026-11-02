"""Isolated HTTP/DB regression for revisions of published records."""
import base64
import json
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import psycopg
from identity_check import app,config,STATE,ORIGIN,call,login,me,check,CHECKS
from app.core.database import StoreError


def main():
    with TestClient(app,base_url=ORIGIN) as admin, TestClient(app,base_url=ORIGIN) as editor:
        login(admin,"admin",config["adminPassword"])
        name="edit"+uuid4().hex[:8]
        call(admin,"POST","/api/admin/users",{"username":name,"displayName":"修改审核测试员",
             "companyId":"zkxk","password":"Revision-initial-123"},201)
        login(editor,name,"Revision-initial-123")
        call(editor,"POST","/api/me/password",{"currentPassword":"Revision-initial-123","password":"Revision-personal-456"})
        login(editor,name,"Revision-personal-456")
        user=me(editor)["user"]
        def api(c,method,path,body=None,status=200,space="zkxk"):
            return call(c,method,path,body,status,space).json()
        def transition(row,action,c=admin,reason=""):
            return api(c,"POST","/api/reviews/"+row["id"]+"/"+action,{"revision":row["revision"],"reason":reason})
        def draft(kind,target,id=None):
            return api(editor,"POST","/api/reviews/edits",{"id":id or str(uuid4()),"kind":kind,"targetId":target},201)
        def save(row,data):
            result=api(editor,"PUT","/api/reviews/"+row["id"],{"revision":row["revision"],"data":data})
            return api(editor,"GET","/api/reviews/"+result["id"])
        def approve(row):
            return transition(transition(row,"submit",editor),"approve")
        def process(id):
            return next(p for p in api(admin,"GET","/api/processes") if p["id"]==id)
        p={"id":str(uuid4()),"name":"正式返修流程"+name,"description":"旧说明",
           "steps":[{"id":str(uuid4()),"name":"旧步骤","objective":"核对旧要求"}]}
        api(admin,"POST","/api/processes",p,201)
        api(editor,"POST","/api/reviews/edits",{"kind":"processes","targetId":p["id"]},403)
        check("create-only member cannot acquire edit capability",True)
        actions=[m+"."+a for m in ("processes","knowledge","skills")
                 for a in (["source_read","edit_any"] if m=="skills" else ["read","edit_any"])]
        group=call(admin,"POST","/api/admin/permission-groups",{"name":name,"actions":actions},201).json()
        call(admin,"PUT","/api/admin/users/"+user["id"]+"/grants",
             {"revision":user["revision"],"grants":[{"spaceId":"zkxk","groupId":group["id"]}]})
        login(editor,name,"Revision-personal-456")
        key=str(uuid4()); row=draft("processes",p["id"],key)
        check("edit creation retry keeps one baseline",draft("processes",p["id"],key)["id"]==row["id"] and row["base"]==row["data"])
        api(editor,"POST","/api/reviews/edits",{"kind":"processes","targetId":p["id"]},403,space="senyuan")
        api(admin,"POST","/api/reviews/edits",{"kind":"processes","targetId":p["id"]},404,space="senyuan")
        check("edit baseline cannot read another company",True)
        data=deepcopy(row["data"]);data["description"]="新说明";data["steps"][0]["name"]="新步骤"
        api(editor,"PUT","/api/reviews/"+row["id"],{"revision":row["revision"],"data":{**data,"id":"forged-id"}},400)
        row=save(row,data)
        check("saving edit leaves live record untouched",process(p["id"])["description"]=="旧说明")
        row=transition(row,"submit",editor)
        row=transition(row,"reject",reason="补充异常处理")
        row=save(row,{**data,"description":"新说明及异常处理"})
        row=approve(row)
        check("approved edit still serves old content",process(p["id"])["description"]=="旧说明")
        with psycopg.connect(config["adminDsn"]) as conn:
            versions=conn.execute("SELECT number,base_payload,payload FROM review_versions WHERE submission_id=%s ORDER BY number",(row["id"],)).fetchall()
            check("rejected edit retains both immutable versions and original baseline",
                  len(versions)==2 and versions[0][1]["description"]=="旧说明" and versions[0][2]["description"]=="新说明")
        row=transition(row,"publish")
        check("edit publishes under same process ID and is idempotent",row["status"]=="published" and
              process(p["id"])["description"]=="新说明及异常处理" and transition(row,"publish")["published_id"]==p["id"])
        # Two independent editors/drafts must not overwrite each other's publication.
        first=draft("processes",p["id"]);second=draft("processes",p["id"])
        first=approve(save(first,{**first["data"],"description":"先发布"}))
        second=approve(save(second,{**second["data"],"description":"后到旧稿"}))
        transition(first,"publish");second=transition(second,"publish")
        check("stale approved revision cannot overwrite newer publication",second["status"]=="publish_failed" and process(p["id"])["description"]=="先发布")
        late=draft("processes",p["id"])
        api(admin,"PUT","/api/processes/"+p["id"],{**process(p["id"]),"description":"管理员直接更新"})
        api(editor,"POST","/api/reviews/"+late["id"]+"/submit",{"revision":late["revision"]},409)
        archived=approve(draft("processes",p["id"]));api(admin,"DELETE","/api/processes/"+p["id"])
        check("direct edit or archival invalidates baseline",transition(archived,"publish")["status"]=="publish_failed")
        # Knowledge profile-only edits preserve source, chunk IDs and existing chunk vectors.
        preview=api(admin,"POST","/api/knowledge/preview",{"fileName":"revision.txt","mimeType":"text/plain",
                    "fileBase64":base64.b64encode(b"Original source retained").decode()})
        meta={"title":"修改测试知识"+name,"purposeId":"reference-knowledge","chunks":[{"content":"old searchable chunk","enabled":True}]}
        def vectors(texts,*args):return [[0.01]*1024 for _ in texts]
        with patch("app.features.documents.router.embed_texts",side_effect=vectors):
            docid=api(admin,"POST","/api/knowledge/previews/"+preview["id"]+"/index",meta,201)["id"]
        def doc():return api(admin,"GET","/api/documents/"+docid)
        old=doc(); old_ids=[c["id"] for c in old["chunks"]]
        row=draft("knowledge",docid);data={**row["data"]["metadata"],"title":"新版标题"+name}
        row=approve(save(row,data))
        with patch("app.features.documents.publication.embed_texts",side_effect=StoreError("模拟向量失败")):
            row=transition(row,"publish")
        check("failed document edit retains old title and chunks",row["status"]=="publish_failed" and doc()["title"]==old["title"] and [c["id"] for c in doc()["chunks"]]==old_ids)
        with patch("app.features.documents.publication.embed_texts",side_effect=vectors) as embedding:
            row=transition(row,"publish")
            check("metadata edit embeds profile only",row["status"]=="published" and len(embedding.call_args.args[0])==1)
        check("metadata edit retains document identity source creator time and chunks",
              doc()["id"]==docid and doc()["originalPath"]==old["originalPath"] and doc()["createdAt"]==old["createdAt"] and [c["id"] for c in doc()["chunks"]]==old_ids)
        category=api(admin,"POST","/api/categories",{"name":"修改归档目录"+name},201)["category"]
        row=draft("knowledge",docid);row=approve(save(row,{**row["data"]["metadata"],"categoryId":category["id"]}))
        with patch("app.features.documents.publication.embed_texts",side_effect=AssertionError("must not embed")) as embedding:
            row=transition(row,"publish")
            check("category-only edit calls no embedding",row["status"]=="published" and not embedding.called and doc()["categoryId"]==category["id"])
        row=draft("knowledge",docid);data=deepcopy(row["data"]["metadata"]);data["chunks"][0]["content"]="new searchable chunk"
        row=approve(save(row,data))
        with patch("app.features.documents.publication.embed_texts",side_effect=vectors) as embedding:
            row=transition(row,"publish")
            check("chunk edit replaces only body vectors atomically",row["status"]=="published" and embedding.call_args.args[0]==["new searchable chunk"] and doc()["chunks"][0]["content"]=="new searchable chunk")
        check("document original remains downloadable",call(admin,"GET","/api/documents/"+docid+"/source",space="zkxk").content==b"Original source retained")
        # File-backed skill -> reviewed record, then another reviewed edit.
        skillid="edit-skill-"+name
        skill={"name":skillid,"description":"旧技能说明","instructions":"旧规则","enabled":True}
        api(admin,"POST","/api/skills",skill,201)
        def concurrent_write(index):
            client=TestClient(app,base_url=ORIGIN)
            try:
                client.cookies.update(admin.cookies);client.csrf=admin.csrf
                return api(client,"PUT","/api/skills/"+skillid+"/resources/references/concurrent-"+str(index)+".txt",{"contentBase64":"b2s="})
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=6) as executor:
            results=list(executor.map(concurrent_write,range(6)))
        check("concurrent legacy skill writes do not exhaust the connection pool",all(r["saved"] for r in results))
        for index in range(6):
            api(admin,"DELETE","/api/skills/"+skillid+"/resources/references/concurrent-"+str(index)+".txt")
        api(admin,"PUT","/api/skills/"+skillid+"/resources/references/note.txt",{"contentBase64":base64.b64encode(b"old attachment").decode()})
        row=draft("skills",skillid);data=deepcopy(row["data"]);data["skill"]["instructions"]="新规则"
        data["resources"][0]["contentBase64"]=base64.b64encode(b"new attachment").decode()
        row=save(row,data)
        check("review exposes correct old and new attachments",
              call(admin,"GET","/api/reviews/"+row["id"]+"/resources/references/note.txt?version=base",space="zkxk").content==b"old attachment" and
              call(admin,"GET","/api/reviews/"+row["id"]+"/resources/references/note.txt",space="zkxk").content==b"new attachment")
        check("unpublished skill edit keeps old attachment live",call(admin,"GET","/api/skills/"+skillid+"/resources/references/note.txt",space="zkxk").content==b"old attachment")
        row=transition(approve(row),"publish")
        matches=[s for s in api(admin,"GET","/api/skills") if s["id"]==skillid]
        check("legacy skill becomes one reviewed record with approved resources",row["status"]=="published" and len(matches)==1 and matches[0]["instructions"]=="新规则" and
              call(admin,"GET","/api/skills/"+skillid+"/resources/references/note.txt",space="zkxk").content==b"new attachment")
        api(admin,"PUT","/api/skills/"+skillid,skill,409)
        row=draft("skills",skillid);data=deepcopy(row["data"]);data["resources"]=[];data["skill"]["instructions"]="第二版规则"
        row=transition(approve(save(row,data)),"publish")
        check("reviewed skill can publish next revision and remove attachment",row["status"]=="published" and next(s for s in api(admin,"GET","/api/skills") if s["id"]==skillid)["instructions"]=="第二版规则")
        api(admin,"GET","/api/skills/"+skillid+"/resources/references/note.txt",status=404)
        row=approve(draft("skills",skillid));api(admin,"DELETE","/api/skills/"+skillid)
        check("disabled skill cannot be reenabled by an old approved draft",transition(row,"publish")["status"]=="publish_failed")
        # Retain a real-browser fixture, then revoke editor permission on a separate group check.
        browser_process={"id":str(uuid4()),"name":"浏览器验收：配件返修跟踪","description":"修改前：登记后联系供应商",
                         "steps":[{"name":"登记故障","objective":"核对数量和保修期"}]}
        api(admin,"POST","/api/processes",browser_process,201)
        (STATE/"edit-browser.json").write_text(json.dumps({"username":name,"password":"Revision-personal-456","processId":browser_process["id"]}))
        (STATE/"edit-browser.json").chmod(0o600)
        (STATE/"review-edit-check-results.json").write_text(json.dumps(CHECKS,ensure_ascii=False,indent=2))
        print(f"review-edit-check: {len(CHECKS)} checks passed")


if __name__=="__main__":
    main()
