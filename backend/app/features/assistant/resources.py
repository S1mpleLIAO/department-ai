"""Read approved/live projections only, through the caller's current space."""
import json
from fastapi import HTTPException
from app.core.security import ScopedPool
from app.features.processes.store import list_processes
from app.features.search.store import keyword_reference_documents, keyword_template_candidates
from app.features.search.service import search_keywords
from app.features.settings.store import get_department_settings


def revision(pool, p, space):
    # A changed grant or live publication invalidates the active runtime, not its history.
    scoped=ScopedPool(pool,p,space)
    with scoped.connection() as conn:
        marks=conn.execute("""SELECT
          (SELECT md5(coalesce(string_agg(id||updated_at::text||status,',' ORDER BY id),'')) FROM knowledge_documents) AS documents,
          (SELECT md5(coalesce(string_agg(id||updated_at::text||archived::text,',' ORDER BY id),'')) FROM business_processes) AS processes,
          (SELECT md5(coalesce(string_agg(id||updated_at::text||enabled::text,',' ORDER BY id),'')) FROM skill_publications) AS skills""").fetchone()
    return json.dumps([p.superadmin,sorted(p.grants.get(space,())),marks],sort_keys=True,default=str)


def call(pool,p,space,name,args):
    p.require(space,"assistant.use")
    scoped=ScopedPool(pool,p,space)
    if name=="department_context_get":
        assistant = get_department_settings(scoped)["assistant"]
        # Return only business guidance, never the legacy host skillDirectory or service settings.
        return {**{key: assistant[key] for key in
                   ("role", "principles", "defaultLanguage", "draftByDefault", "askWhenMissing")},
                "mode": "部门助手", "spaceId": space,
                "availableTools": ["department_context_get", "department_uploaded_document_read"] + [
                    tool for tool, action in (
                        ("department_processes", "processes.read"),
                        ("department_knowledge_search", "knowledge.read"),
                        ("department_document_get", "knowledge.read"),
                        ("department_skill_list", "skills.use"),
                        ("department_skill_get", "skills.use"),
                        ("department_reimbursement_generate", "skills.use")) if p.allowed(space, action)]}
    if name=="department_processes":
        p.require(space,"processes.read")
        return list_processes(scoped)
    if name=="department_knowledge_search":
        p.require(space,"knowledge.read")
        query=args.get("query","")
        if not isinstance(query,str) or not 1<=len(query)<=500:
            raise HTTPException(422,"请输入不超过500字的查询")
        terms=search_keywords(query,[])
        items=keyword_reference_documents(scoped,terms,10)+keyword_template_candidates(scoped,terms,10)
        return list({x["id"]:{k:x[k] for k in ("id","title","summary","documentType","documentPurpose","templateFamily","templateVariant","version","applicableScenario","updatedAt")} for x in items}.values())
    if name=="department_document_get":
        p.require(space,"knowledge.read")
        with scoped.connection() as conn:
            row=conn.execute("""SELECT id,title,summary,parsed_text FROM knowledge_documents
              WHERE id=%s AND status='effective'""",(args.get("id"),)).fetchone()
        if not row: raise HTTPException(404,"找不到可用的已发布文档")
        return {**row,"parsed_text":row["parsed_text"][:80000]}
    if name in ("department_skill_list","department_skill_get","department_skill_prepare"):
        p.require(space,"skills.use")
        with scoped.connection() as conn:
            if name.endswith("_list"):
                return [{"id":x["id"],"name":x["data"]["skill"]["name"],
                         "description":x["data"]["skill"]["description"]} for x in conn.execute(
                         "SELECT id,data FROM skill_publications WHERE enabled ORDER BY id")]
            row=conn.execute("SELECT data FROM skill_publications WHERE id=%s AND enabled",
                             (args.get("id"),)).fetchone()
        if not row: raise HTTPException(404,"找不到可用的已发布技能")
        if name=="department_skill_prepare":
            # Local editable resources imply source access; use-only reimbursement stays in its worker.
            p.require(space,"skills.source_read")
            return row["data"]
        resource=args.get("resource")
        if resource:
            found=next((r for r in row["data"].get("resources",[]) if r["path"]==resource),None)
            if not found: raise HTTPException(404,"技能资源不存在")
            if found["path"].startswith("scripts/"):
                p.require(space,"skills.source_read")
            return found
        return {**row["data"]["skill"],"resources":[r["path"] for r in row["data"].get("resources",[])]}
    raise HTTPException(403,"此部门工具未授权")
