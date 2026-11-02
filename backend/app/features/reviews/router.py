import base64
from typing import Literal
from fastapi import APIRouter, Request, Query
from fastapi.responses import Response
from app.core.database import NotFoundError
from .schemas import DraftInput, DraftUpdate, Transition, EditInput
from . import service

router=APIRouter(prefix="/api/reviews",tags=["reviews"])


@router.get("")
def listing(request:Request, page:int=Query(default=0,ge=0), mode:str=Query(default="mine",pattern="^(mine|pending|all)$")):
    p,space=request.state.principal,request.state.space
    kinds=[k for k in service.KINDS if p.allowed(space,k+(".source_read" if k=="skills" else ".read"))]
    clauses=["s.kind=ANY(%s)"]; args=[kinds]
    if mode=="mine":
        clauses.append("s.owner_id=%s"); args.append(p.user_id)
    elif mode=="pending":
        review=[k for k in kinds if p.allowed(space,k+".review") or p.allowed(space,k+".publish")]
        clauses.extend(["s.kind=ANY(%s)","s.status IN ('submitted','approved','publish_failed')","s.owner_id<>%s"])
        args.extend([review,p.user_id])
    where=" AND ".join(clauses)
    with request.state.pool.connection() as conn:
        total=conn.execute("SELECT count(*) AS n FROM review_submissions s WHERE "+where,args).fetchone()["n"]
        page=min(page,max(0,(total-1)//20))
        rows=conn.execute("""SELECT s.*,u.display_name AS author FROM review_submissions s
                             JOIN users u ON u.id=s.owner_id WHERE """+where+
                          " ORDER BY s.updated_at DESC,s.id LIMIT 20 OFFSET %s",[*args,page*20]).fetchall()
    return {"items":[service.view(row) for row in rows],"total":total,"page":page,"pageSize":20}


@router.post("",status_code=201)
def create(request:Request,body:DraftInput):
    return service.create(request,body)


@router.get("/{id}")
def detail(id:str,request:Request):
    with request.state.pool.connection() as conn:
        row=service.visible(request,conn.execute("""SELECT s.*,u.display_name AS author FROM review_submissions s
                            JOIN users u ON u.id=s.owner_id WHERE s.id=%s""",(id,)).fetchone())
        result=service.view(row,True)
        result["history"]=conn.execute("""SELECT v.number,v.created_at FROM review_versions v
                                         WHERE submission_id=%s ORDER BY number DESC LIMIT 20""",(id,)).fetchall()
    return result


@router.post("/edits",status_code=201)
def create_edit(request:Request,body:EditInput):
    from .edits import create_edit
    return create_edit(request,body)


@router.put("/{id}")
def update(id:str,request:Request,body:DraftUpdate):
    return service.update(request,id,body)


@router.get("/{id}/source")
def source(id:str,request:Request):
    request.state.principal.require(request.state.space,"knowledge.source_download")
    with request.state.pool.connection() as conn:
        service.visible(request,conn.execute("SELECT * FROM review_submissions WHERE id=%s",(id,)).fetchone())
        row=conn.execute("SELECT * FROM review_sources WHERE submission_id=%s",(id,)).fetchone()
        if not row:
            raise NotFoundError("原文件不存在")
    from urllib.parse import quote
    return Response(bytes(row["body"]),media_type=row["mime"],headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(row["name"])})


@router.get("/{id}/resources/{path:path}")
def resource(id:str,path:str,request:Request,version:Literal["draft","base"]="draft"):
    with request.state.pool.connection() as conn:
        row=service.visible(request,conn.execute("SELECT * FROM review_submissions WHERE id=%s",(id,)).fetchone())
    if row["kind"]=="skills":
        data = row["base_payload"] if version=="base" else row["draft"]
        for item in (data or {}).get("resources",[]):
            if item["path"]==path:
                return Response(base64.b64decode(item["contentBase64"]),media_type="application/octet-stream")
    raise NotFoundError("附件不存在")


@router.post("/{id}/submit")
def submit(id:str,request:Request,body:Transition):
    return service.transition(request,id,"submit",body)


@router.post("/{id}/approve")
def approve(id:str,request:Request,body:Transition):
    return service.transition(request,id,"approve",body)


@router.post("/{id}/reject")
def reject(id:str,request:Request,body:Transition):
    return service.transition(request,id,"reject",body)


@router.post("/{id}/publish")
def publish(id:str,request:Request,body:Transition):
    return service.publish(request,id,body)
