"""Fixed reimbursement execution; no arbitrary commands or shared business filesystem."""
import asyncio
import base64
from contextlib import suppress, asynccontextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import fcntl
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from app.core.config import get_settings
from app.core.security import ScopedPool
from app.features.documents.service import parse_document

MAX_FILE = 20 * 1024 * 1024
SKILL = "travel-reimbursement-cn"
BUCKETS = ("transport_items", "lodging_items", "airport_station_transport", "other_items")


def plain(value, label, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value)>limit or any(
        c in "/\\\x00" or ord(c)<32 for c in value) or value in (".", ".."):
        raise HTTPException(422, label+"不能为空，且不能包含路径或控制字符")
    return value.strip()


def inputs(args):
    try:
        job=json.loads(args["jobJson"]); profile=json.loads(args["profileJson"])
    except (ValueError,KeyError,TypeError):
        raise HTTPException(422,"jobJson 和 profileJson 必须是 JSON 对象")
    if not isinstance(profile,dict) or set(profile)!={"姓名","部门","职务","银行卡","开户行"}:
        raise HTTPException(422,"个人资料必须包含姓名、部门、职务、银行卡、开户行五项")
    profile={k:plain(v,k) for k,v in profile.items()}
    if not isinstance(job,dict) or not isinstance(job.get("trips"),list) or not 1<=len(job["trips"])<=10:
        raise HTTPException(422,"一次须包含 1 至 10 次出差")
    allowed={"form_date","trips","generation_timestamp"}
    if set(job)-allowed: raise HTTPException(422,"报销任务包含未知字段")
    try:
        job["form_date"]=date.fromisoformat(job.get("form_date",date.today().isoformat())).isoformat()
        for trip in job["trips"]:
            if not isinstance(trip,dict):raise ValueError()
            for key in ("project_name","city","visited_company","work_item","transport_type"):
                trip[key]=plain(trip.get(key),key,500 if key=="work_item" else 80)
            trip["folder_name"]=plain(trip.get("folder_name",trip["project_name"]),"folder_name",60)
            start,end=(date.fromisoformat(trip[k]) for k in ("start_date","end_date"))
            if not 0<=(end-start).days<=366:raise ValueError()
            for bucket in BUCKETS:
                items=trip.get(bucket)
                if not isinstance(items,list) or len(items)>{"transport_items":4,"lodging_items":3}.get(bucket,30):
                    raise ValueError("票据条目缺失或超过模板行数")
                for item in items:
                    if not isinstance(item,dict) or "amount" not in item:raise ValueError("票据金额缺失")
                    amount=Decimal(str(item["amount"]))
                    if not amount.is_finite() or not 0<=amount<10000000 or amount!=amount.quantize(Decimal(".01")):raise ValueError("金额无效")
                    count=item.get("receipt_count")
                    if type(count) is not int or not 0<=count<=1000:raise ValueError("票据张数缺失")
                    for key in ("start_date","end_date"):
                        if key in item:date.fromisoformat(item[key])
            participants=trip.get("participants",[])
            if isinstance(participants,str):plain(participants,"同行人员",500)
            elif isinstance(participants,list) and len(participants)<=30:
                for person in participants:plain(person,"同行人员",80)
            else:raise ValueError("同行人员无效")
    except (ValueError,KeyError,TypeError,InvalidOperation) as error:
        raise HTTPException(422,"出差日期、金额或票据明细不完整/无效，请核对后生成") from error
    job["generation_timestamp"]=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    return job,profile


def publication(runtime,p):
    p.require(runtime.space,"skills.use")
    with ScopedPool(runtime.manager.pool,p,runtime.space).connection() as conn:
        row=conn.execute("SELECT data FROM skill_publications WHERE id=%s AND enabled",(SKILL,)).fetchone()
    if not row:raise HTTPException(404,"当前空间没有可执行的已发布报销技能")
    return row["data"]


def uploaded_path(runtime,value):
    # Native dsh-v0.1.5 file attachment store: immutable digest/name aliases.
    if not isinstance(value,str):raise HTTPException(422,"缺少附件路径")
    match=re.fullmatch(r"/home/assistant/dsh/attachments/v1/files/([a-f0-9]{2})/([a-f0-9]{64})/([^/\\]+)",value)
    if not match or match[1]!=match[2][:2] or match[3] in (".",".."):
        raise HTTPException(403,"只允许读取本人当前公司上传的附件")
    path=runtime.root/"home"/PurePosixPath(value).relative_to("/home/assistant")
    try:
        if path.resolve(strict=True)!=path or not path.is_file() or path.stat().st_size>MAX_FILE:
            raise OSError()
    except (OSError,RuntimeError):
        raise HTTPException(404,"附件不存在或超过 20 MiB")
    return path


async def read_upload(runtime,args):
    await run_in_threadpool(runtime.validate)
    path=uploaded_path(runtime,args.get("path"))
    if path.suffix.lower() not in {".pdf",".docx",".xlsx",".pptx",".txt",".md",".csv",".json",".png",".jpg",".jpeg"}:
        raise HTTPException(422,"请上传 PDF、Office、图片或文本材料")
    try:
        # The existing parser owns its timeout; keep the lease until it finishes.
        text=await run_in_threadpool(parse_document,path.read_bytes(),path.name,
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",get_settings().docling_base_url)
    except Exception as error:
        raise HTTPException(502,"附件正文解析失败，请检查文件或稍后重试") from error
    await run_in_threadpool(runtime.validate)
    return {"name":path.name,"text":text[:80000],"truncated":len(text)>80000}


def materialize(data,folder):
    total=0
    for resource in data.get("resources",[]):
        name=resource["path"]; rel=PurePosixPath(name)
        if not rel.parts or "\x00" in name or rel.is_absolute() or any(p in (".","..") for p in name.split("/")) or "\\" in name or rel.parts[0] not in ("scripts","assets","references"):
            raise HTTPException(422,"已发布技能资源路径无效")
        content=base64.b64decode(resource["contentBase64"],validate=True);total+=len(content)
        if total>10*1024*1024:raise HTTPException(422,"报销技能资源超过限制")
        target=folder/rel;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content);target.chmod(0o644)  # Read-only mount; copy2 outputs must remain writable.
    for path in folder.rglob("*"):
        if path.is_dir():path.chmod(0o755)
    folder.chmod(0o755)


@asynccontextmanager
async def staging(runtime,job_id):
    if os.geteuid()==0:
        with TemporaryDirectory(prefix="reimbursement-",dir=runtime.root) as temporary:
            yield Path(temporary)
    else:
        from .runtime import docker
        await docker("prepare-job",runtime.key,job_id)
        try:yield runtime.root/("reimbursement-"+job_id)
        finally:await docker("cleanup-job",runtime.key,job_id)


async def generate(runtime,args):
    p=await run_in_threadpool(runtime.validate)
    data=await run_in_threadpool(publication,runtime,p)
    job,profile=inputs(args)
    from .runtime import ROOT
    if not (ROOT/".identity-state/reimbursement-fonts/extracted/usr/share/fonts/truetype/arphic/uming.ttc").is_file():
        raise HTTPException(503,"管理员尚未准备报销运行依赖，请运行独立环境 setup-reimbursement-runtime.sh")
    # ponytail: one generator across company gateways; use a worker queue if load demands it.
    lock_path=ROOT/".identity-state/reimbursement.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("a") as lock:
        os.chmod(lock_path,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise HTTPException(429,"另一份报销单正在生成，请稍后重试")
        if int(re.search(r"MemAvailable:\s+(\d+)",Path("/proc/meminfo").read_text())[1])<800*1024:
            raise HTTPException(503,"服务器内存不足，请稍后生成")
        job_id=uuid4().hex
        container="department-reimbursement-"+runtime.manager.namespace+"-"+job_id
        async with staging(runtime,job_id) as temporary:
            stage=Path(temporary);skill=stage/"skill";skill.mkdir(exist_ok=True)
            materialize(data,skill)
            input_dir=stage/"input";input_dir.mkdir(mode=0o755,exist_ok=True)
            (stage/"input/.department-disposable.json").write_text(json.dumps({"kind":"reimbursement-stage","version":1}))
            for name,value in (("job.json",job),("profile.json",profile)):
                target=input_dir/name;target.write_text(json.dumps(value,ensure_ascii=False));target.chmod(0o444)
            out=stage/"output";out.mkdir(mode=0o700,exist_ok=True);os.chown(out,10001,10001)
            from .recipes import reimbursement
            from .host_command import command
            argv=command(*reimbursement(runtime.manager.root,ROOT,stage,job_id))
            process=None
            try:
                with (stage/"worker.log").open("wb") as log:
                    process=await asyncio.create_subprocess_exec(*argv,stdout=log,stderr=log)
                    async with asyncio.timeout(180):
                        while process.returncode is None:
                            await asyncio.sleep(.5)
                            await run_in_threadpool(runtime.validate)
                    if process.returncode:
                        # Keep internal diagnostic outside downloadable workspace, never leak profile/logs.
                        (runtime.root/".control/reimbursement-last-error.txt").write_bytes((stage/"worker.log").read_bytes()[-8000:])
                        (runtime.root/".control/reimbursement-last-error.txt").chmod(0o600)
                        raise HTTPException(502,"报销生成失败，原材料已保留，请联系管理员检查执行日志")
                await run_in_threadpool(runtime.validate)
                # An immutable final directory is published only after successful complete output.
                report_path=out/"generation_report.json"
                files=list(out.rglob("*.docx"))
                if len(files)!=2*len(job["trips"])+1:raise HTTPException(502,"报销输出不完整")
                for file in files+[report_path]:
                    if file.resolve()!=file or not file.is_file() or file.stat().st_size>MAX_FILE:
                        raise HTTPException(502,"报销输出文件无效")
                from .storage import check
                await asyncio.to_thread(check,runtime,0,0)
                report=json.loads(report_path.read_text())
                destination=runtime.root/"home/workspace/reimbursements"/job_id
                if destination.parent.resolve()!=destination.parent:raise HTTPException(403,"输出目录无效")
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chown(destination.parent,10001,10001)
                destination.mkdir(mode=0o700);os.chown(destination,10001,10001)
                links=[]
                for file in files+[report_path]:
                    rel=file.relative_to(out);target=destination/rel
                    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    os.chown(target.parent,10001,10001)
                    file.rename(target);target.chmod(0o600);os.chown(target,10001,10001)
                    path="/home/assistant/workspace/reimbursements/"+job_id+"/"+rel.as_posix()
                    links.append({"name":rel.as_posix(),"path":path,"downloadUrl":"/api/file?path="+quote(path,safe="")+"&download=1"})
                return {"draft":True,"skill":SKILL,"total":report.get("total"),"report":report,
                        "files":links,"message":"已生成待人工核对的报销草稿，请下载检查后再报销。"}
            except TimeoutError:
                raise HTTPException(504,"报销生成超时，请重试；没有发布不完整文件")
            finally:
                if process is not None:
                    cleanup=await asyncio.create_subprocess_exec(*command("rm","-f",container),
                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
                    await cleanup.wait()
                    with suppress(TimeoutError):await asyncio.wait_for(process.wait(),5)
