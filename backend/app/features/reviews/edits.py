"""Copy live content into a private edit; compare its baseline under the live lock."""
import base64
import hashlib
import json
from pathlib import Path
from psycopg.types.json import Jsonb
from app.core.database import ConflictError, NotFoundError, StoreError
from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.store import get_document
from app.features.processes.store import list_processes
from app.features.skills.schemas import SkillInput
from app.features.skills.service import list_skills, read_skill_resource
from app.features.skills.publications import lock_skills
from app.features.identity.service import audit


def snapshot(request, conn, kind, target):
    from .service import TransactionPool
    pool = TransactionPool(conn)
    source = None
    if kind == "processes":
        live = conn.execute("SELECT updated_at,archived FROM business_processes WHERE id=%s FOR UPDATE", (target,)).fetchone()
        if not live or live["archived"]:
            raise NotFoundError("流程不存在或已归档，请从正式资料重新起草")
        data = next(p for p in list_processes(pool) if p["id"] == target)
    elif kind == "knowledge":
        live = conn.execute("SELECT updated_at,status,original_path FROM knowledge_documents WHERE id=%s FOR UPDATE", (target,)).fetchone()
        if not live or live["status"] != "effective":
            raise NotFoundError("文档不存在或已废止，请从有效资料重新起草")
        doc = get_document(pool, target)
        indices = {c["id"]: i for i,c in enumerate(doc["chunks"])}
        metadata = {k:doc[k] for k in KnowledgeIndexInput.model_fields if k in doc}
        metadata["chunks"] = [{"content":c["content"],"enabled":c["enabled"],"sectionPath":c["sectionPath"],
                               "parentIndex":indices.get(c["parentChunkId"])} for c in doc["chunks"]]
        metadata = KnowledgeIndexInput.model_validate(metadata).model_dump()
        data = {"metadata":metadata,"parsedText":doc["parsedText"],"fileName":doc["originalName"],
                "mimeType":doc["mimeType"],"resourceId":target,"chunkSettings":doc["chunkSettings"],
                "purposeFlags":[doc["isGenerationTemplate"],doc["isReferenceKnowledge"]]}
        source = Path(live["original_path"]).resolve()
        if not source.is_relative_to(request.state.settings.data_dir.resolve()):
            raise StoreError("原文件不在受管理目录中，无法保存修改稿")
    else:
        lock_skills(conn)
        live = conn.execute("SELECT * FROM skill_publications WHERE id=%s FOR UPDATE", (target,)).fetchone()
        if live:
            data = {**live["data"],"skill":{**live["data"]["skill"],"enabled":live["enabled"]}}
        else:
            skill = next((s for s in list_skills(request.state.settings.skill_dir) if s["id"] == target), None)
            if not skill:
                raise NotFoundError("技能不存在")
            if not skill["valid"]:
                raise StoreError("技能内容损坏，请先由管理员修复后再起草")
            resources = []
            total = 0
            for item in skill["resources"]:
                path = read_skill_resource(request.state.settings.skill_dir,target,item["path"])
                total += path.stat().st_size
                if total > request.state.settings.max_source_bytes:
                    raise StoreError("技能附件超过修改稿大小限制")
                resources.append({"path":item["path"],"contentBase64":base64.b64encode(path.read_bytes()).decode()})
            data = {"skill":SkillInput.model_validate({k:skill[k] for k in SkillInput.model_fields}).model_dump(),
                    "resources":resources}
            live = {"updated_at":skill["updatedAt"]}
    token = hashlib.sha256(json.dumps([str(live["updated_at"]),data],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return data, token, source


def create_edit(request, body):
    from .service import view, title_of, require_read
    p = request.state.principal
    p.require(request.state.space, body.kind+".edit_any")
    require_read(request,body.kind)
    with request.state.pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(request.state.space+":"+p.user_id+":"+body.id,))
        prior = conn.execute("SELECT * FROM review_submissions WHERE id=%s",(body.id,)).fetchone()
        if prior:
            if prior["owner_id"]!=p.user_id or prior["kind"]!=body.kind or prior["target_id"]!=body.targetId:
                raise ConflictError("起草请求已被使用，请刷新")
            return view(prior,True)
        data, token, source = snapshot(request,conn,body.kind,body.targetId)
        row = conn.execute("""INSERT INTO review_submissions(id,kind,title,draft,source_key,target_id,base_token,base_payload)
                              VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                           (body.id,body.kind,title_of(body.kind,data),Jsonb(data),body.id,body.targetId,token,Jsonb(data))).fetchone()
        if source:
            if not source.is_file() or source.stat().st_size>request.state.settings.max_source_bytes:
                raise StoreError("原文件不存在或超过大小限制，无法保存修改稿")
            conn.execute("INSERT INTO review_sources(submission_id,name,mime,body) VALUES(%s,%s,%s,%s)",
                         (body.id,data["fileName"],data["mimeType"],source.read_bytes()))
        audit(conn,p.user_id,"review.edit_created",body.id,space=request.state.space,details={"target":body.targetId})
        return view(row,True)


def check_target(row, data):
    if not row["target_id"]:
        return
    target = data["id"] if row["kind"]=="processes" else data["skill"]["name"] if row["kind"]=="skills" else data["id"]
    if target != row["target_id"]:
        raise StoreError("修改稿不能改变正式资料的标识或技能名称")


def check_base(request, conn, row):
    data, token, source = snapshot(request,conn,row["kind"],row["target_id"])
    if token != row["base_token"]:
        raise ConflictError("正式资料已更新，本次修改不能覆盖新版本。请返回正式资料重新发起修改，原稿保留供对照")
    return data, source
