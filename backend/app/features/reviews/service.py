"""New-content review: private drafts, immutable submissions and atomic publication."""
import base64
import binascii
import json
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg.types.json import Jsonb
from app.core.database import StoreError, ConflictError, NotFoundError, TransactionPool
from app.core.security import preview_directory
from app.features.identity.service import audit
from app.features.processes.schemas import ProcessInput
from app.features.processes.store import save_process
from app.features.skills.schemas import SkillInput
from app.features.skills.service import list_skills
from app.features.documents.service import read_preview, preview_source_path, delete_preview
from app.features.documents.publication import validate_metadata, publish_reviewed_document
from app.features.catalog.store import get_purpose
from app.features.settings.store import get_department_settings
from .edits import check_target, check_base
from app.features.skills.publications import lock_skills

KINDS = ("processes", "knowledge", "skills")


def require_read(request, kind):
    request.state.principal.require(request.state.space, kind + (".source_read" if kind=="skills" else ".read"))


def normalize(request, kind, data, pool=None):
    if len(json.dumps(data).encode()) > 30 * 1024 * 1024:
        raise StoreError("草稿内容过大")
    try:
        if kind == "processes":
            return ProcessInput.model_validate(data).model_dump()
        if kind == "knowledge":
            return validate_metadata(pool or request.state.pool, data)
        if set(data) - {"skill", "resources"}:
            raise StoreError("技能草稿包含不支持的字段")
        skill = SkillInput.model_validate(data.get("skill")).model_dump()
        resources, total, names = [], 0, set()
        raw = data.get("resources", [])
        if not isinstance(raw, list) or len(raw) > 30:
            raise StoreError("技能最多附带30个资源")
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"path", "contentBase64"}:
                raise StoreError("技能附件格式无效")
            name = item["path"]
            if not isinstance(name,str) or "\\" in name or len(name)>500:
                raise StoreError("技能附件路径无效")
            parts = name.split("/")
            if len(parts)<2 or parts[0] not in ("scripts","references","assets") or any(not p or p.startswith(".") for p in parts):
                raise StoreError("附件必须位于 scripts、references 或 assets 目录")
            if name in names:
                raise StoreError("技能附件路径重复")
            try:
                content = base64.b64decode(item["contentBase64"],validate=True)
            except (ValueError, TypeError, binascii.Error) as error:
                raise StoreError("附件编码无效") from error
            total += len(content)
            if total > request.state.settings.max_source_bytes:
                raise StoreError("技能附件总大小超过上传限制")
            names.add(name)
            resources.append({"path":name,"contentBase64":base64.b64encode(content).decode()})
        return {"skill":skill,"resources":resources}
    except ValidationError as error:
        raise StoreError("草稿字段无效，请检查必填内容和格式") from error


def title_of(kind, data):
    return data["name"] if kind=="processes" else data["metadata"]["title"] if kind=="knowledge" else data["skill"]["name"]


def visible(request, row):
    if not row:
        raise NotFoundError("提交不存在或没有访问权限")
    require_read(request, row["kind"])
    return row


def locked(conn, request, id, revision):
    row = visible(request, conn.execute("SELECT * FROM review_submissions WHERE id=%s FOR UPDATE", (id,)).fetchone())
    if row["revision"] != revision:
        raise ConflictError("内容或状态已变化，请刷新后重新操作")
    return row


def owner(request, row):
    if row["owner_id"] != request.state.principal.user_id:
        raise HTTPException(403, "只能编辑和提交自己的草稿")
    action = ".edit_any" if row["target_id"] else ".create"
    request.state.principal.require(request.state.space, row["kind"]+action)


def view(row, detail=False):
    result = {k:row[k] for k in ("id","kind","title","status","revision","version","feedback","publish_error","published_id","owner_id")}
    result.update(updatedAt=row["updated_at"].isoformat(), author=row.get("author",""))
    result["targetId"] = row["target_id"]
    if detail:
        result["data"] = row["draft"]
        result["base"] = row["base_payload"]
    return result


def create(request, body):
    p, pool = request.state.principal, request.state.pool
    p.require(request.state.space, body.kind+".create")
    require_read(request,body.kind)
    raw={**body.data}
    if body.kind=="processes" and "id" not in raw:
        raw["id"]=body.id
    if body.kind=="processes" and isinstance(raw.get("steps"),list):
        raw["steps"]=[{**step,"id":step.get("id") or str(uuid5(NAMESPACE_URL,body.id+":"+str(index)))}
                      if isinstance(step,dict) else step for index,step in enumerate(raw["steps"])]
    data = normalize(request,body.kind,raw)
    source = None
    key = body.previewId if body.kind=="knowledge" else body.id
    # Repeated upload/save after a lost response returns the original draft.
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     (request.state.space+":"+p.user_id+":"+key if key else body.id,))
        prior = conn.execute("SELECT * FROM review_submissions WHERE owner_id=%s AND source_key=%s", (p.user_id,key)).fetchone()
        if prior:
            previous=prior["draft"]["metadata"] if prior["kind"]=="knowledge" else prior["draft"]
            if prior["kind"]!=body.kind or previous!=data:
                raise ConflictError("这份草稿已经保存，请到提交与审核中查看或修改，不能重复覆盖")
            return view(prior)
        if body.kind=="knowledge":
            if not body.previewId:
                raise StoreError("请先上传并解析文档")
            preview = read_preview(preview_directory(request),body.previewId)
            content = preview_source_path(preview_directory(request),preview).read_bytes()
            if len(content)>request.state.settings.max_source_bytes:
                raise StoreError("原文件超过上传限制")
            purpose=get_purpose(TransactionPool(conn),data["purposeId"])
            source = (preview["fileName"],preview["mimeType"],content)
            data = {"metadata":data, "parsedText":preview["parsedText"], "fileName":preview["fileName"],
                    "mimeType":preview["mimeType"], "resourceId":str(uuid4()),
                    "purposeFlags":[purpose["canGenerateTemplate"],purpose["chunkBody"]],
                    "chunkSettings":preview.get("settings") or get_department_settings(TransactionPool(conn))["chunking"]}
        row = conn.execute("""INSERT INTO review_submissions(id,kind,title,draft,source_key)
                              VALUES(%s,%s,%s,%s,%s) RETURNING *""",
                           (body.id,body.kind,title_of(body.kind,data),Jsonb(data),key)).fetchone()
        if source:
            conn.execute("INSERT INTO review_sources(submission_id,name,mime,body) VALUES(%s,%s,%s,%s)",(body.id,*source))
        audit(conn,p.user_id,"review.draft_created",body.id,space=request.state.space)
        result=view(row)
    if source:
        try:
            delete_preview(preview_directory(request),body.previewId)
        except (OSError,StoreError):
            pass  # The committed private source is authoritative; cleanup may be retried separately.
    return result


def update(request, id, body):
    with request.state.pool.connection() as conn:
        row=locked(conn,request,id,body.revision)
        owner(request,row)
        if row["status"] not in ("draft","rejected"):
            raise ConflictError("只有草稿或已驳回内容可以修改")
        data=normalize(request,row["kind"],body.data,TransactionPool(conn))
        check_target(row,data)
        if row["kind"]=="knowledge":
            purpose=get_purpose(TransactionPool(conn),data["purposeId"])
            data={**row["draft"],"metadata":data,"purposeFlags":[purpose["canGenerateTemplate"],purpose["chunkBody"]]}
        result=conn.execute("""UPDATE review_submissions SET draft=%s,title=%s,status='draft',revision=revision+1,
                               approved_by=NULL,publish_error='',updated_at=now() WHERE id=%s RETURNING *""",
                            (Jsonb(data),title_of(row["kind"],data),id)).fetchone()
        audit(conn,request.state.principal.user_id,"review.draft_updated",id,space=request.state.space)
        return view(result)


def available_reviewer(conn, space, kind, owner_id):
    return conn.execute("""SELECT 1 FROM users u WHERE u.active AND NOT u.must_change_password
        AND u.id<>%s AND (u.superadmin OR EXISTS (
            SELECT 1 FROM user_space_grants g JOIN permission_groups pg ON pg.id=g.group_id
            WHERE g.user_id=u.id AND g.space_id=%s AND pg.actions ? %s)) LIMIT 1""",
        (owner_id,space,kind+".review")).fetchone() is not None


def transition(request, id, action, body):
    p=request.state.principal
    with request.state.pool.connection() as conn:
        row=locked(conn,request,id,body.revision)
        if action=="submit":
            owner(request,row)
            if row["status"] not in ("draft","rejected"):
                raise ConflictError("当前状态不能提交")
            if row["kind"]=="knowledge":
                validate_metadata(TransactionPool(conn),row["draft"]["metadata"])
            if row["target_id"]:
                check_base(request,conn,row)
            if not available_reviewer(conn,request.state.space,row["kind"],row["owner_id"]):
                raise HTTPException(409,"此空间的该类内容尚无可用审核人，请联系超级管理员配置；草稿已保留")
            conn.execute("""INSERT INTO review_versions(submission_id,number,payload,target_id,base_token,base_payload)
                            VALUES(%s,%s,%s,%s,%s,%s)""",
                         (id,row["version"]+1,Jsonb(row["draft"]),row["target_id"],row["base_token"],
                          Jsonb(row["base_payload"]) if row["base_payload"] is not None else None))
            result=conn.execute("""UPDATE review_submissions SET status='submitted',version=version+1,
                                  revision=revision+1,feedback='',approved_by=NULL,publish_error='',updated_at=now()
                                  WHERE id=%s RETURNING *""",(id,)).fetchone()
        else:
            p.require(request.state.space,row["kind"]+".review")
            if p.user_id==row["owner_id"]:
                raise HTTPException(403,"不能审核自己的提交，请由另一位审核员处理")
            allowed=("submitted","approved","publish_failed") if action=="reject" else ("submitted",)
            if row["status"] not in allowed:
                raise ConflictError("当前状态不能执行此审核操作")
            if action=="reject" and not body.reason.strip():
                raise StoreError("驳回必须填写原因")
            result=conn.execute("""UPDATE review_submissions SET status=%s,feedback=%s,approved_by=%s,
                                  revision=revision+1,publish_error='',updated_at=now() WHERE id=%s RETURNING *""",
                                ("approved" if action=="approve" else "rejected",body.reason.strip(),
                                 p.user_id if action=="approve" else None,id)).fetchone()
        audit(conn,p.user_id,"review."+action,id,space=request.state.space,
              details={"version":result["version"],"reason":body.reason.strip()})
        return view(result)


def publish(request,id,body):
    p=request.state.principal
    with request.state.pool.connection() as conn:
        row=visible(request,conn.execute("SELECT * FROM review_submissions WHERE id=%s FOR UPDATE",(id,)).fetchone())
        p.require(request.state.space,row["kind"]+".publish")
        if row["status"]=="published":
            return view(row)
        if row["revision"]!=body.revision:
            raise ConflictError("状态已变化，请刷新后重新操作")
        if row["status"] not in ("approved","publish_failed"):
            raise ConflictError("必须先通过审核才能发布")
        payload=conn.execute("SELECT payload FROM review_versions WHERE submission_id=%s AND number=%s",
                             (id,row["version"])).fetchone()["payload"]
        path=None
        try:
            with conn.transaction():
                pool=TransactionPool(conn)
                if row["target_id"]:
                    check_base(request,conn,row)
                conn.execute("SELECT set_config('department.user',%s,true)",(row["owner_id"],))
                if row["kind"]=="processes":
                    save_process(pool,payload,creating=not row["target_id"])
                    resource_id=payload["id"]
                elif row["kind"]=="skills":
                    lock_skills(conn)
                    resource_id=payload["skill"]["name"]
                    if not row["target_id"] and any(s["id"]==resource_id for s in list_skills(request.state.settings.skill_dir)):
                        raise ConflictError("同名技能已经存在")
                    if row["target_id"]:
                        conn.execute("""INSERT INTO skill_publications(id,submission_id,data,enabled) VALUES(%s,%s,%s,%s)
                                        ON CONFLICT(space_id,id) DO UPDATE SET submission_id=EXCLUDED.submission_id,
                                        data=EXCLUDED.data,enabled=EXCLUDED.enabled,updated_at=now()""",
                                     (resource_id,id,Jsonb(payload),payload["skill"]["enabled"]))
                    else:
                        conn.execute("INSERT INTO skill_publications(id,submission_id,data,enabled) VALUES(%s,%s,%s,%s)",
                                     (resource_id,id,Jsonb(payload),payload["skill"]["enabled"]))
                else:
                    resource_id=payload["resourceId"]
                    if row["target_id"]:
                        from app.features.documents.publication import publish_document_edit
                        publish_document_edit(pool,request.state.settings,payload,row["base_payload"])
                    else:
                        source=conn.execute("SELECT * FROM review_sources WHERE submission_id=%s",(id,)).fetchone()
                        directory=request.state.settings.data_dir / "reviewed-documents"
                        directory.mkdir(parents=True,exist_ok=True)
                        path=directory/(id+Path(source["name"]).suffix.lower())
                        # A previous interrupted publication may have left only this private source.
                        path.write_bytes(bytes(source["body"]))
                        publish_reviewed_document(pool,request.state.settings,payload,path)
                result=conn.execute("""UPDATE review_submissions SET status='published',published_id=%s,
                                      revision=revision+1,publish_error='',updated_at=now() WHERE id=%s RETURNING *""",
                                    (resource_id,id)).fetchone()
                audit(conn,p.user_id,"review.published",id,space=request.state.space,
                      details={"version":row["version"],"resourceId":resource_id})
        except Exception as error:
            if path:
                path.unlink(missing_ok=True)
            # Do not expose provider credentials or internal database exception text.
            message=str(error) if isinstance(error,StoreError) else "发布未完成，请检查服务状态或同名资料后重试"
            result=conn.execute("""UPDATE review_submissions SET status='publish_failed',publish_error=%s,
                                  revision=revision+1,updated_at=now() WHERE id=%s RETURNING *""",(message,id)).fetchone()
            audit(conn,p.user_id,"review.publish_failed",id,space=request.state.space,details={"version":row["version"]})
        return view(result)
