"""Opt-in real Harness upload/parse/generate/download; synthetic receipts and model."""
import asyncio,base64,json,os,socket,subprocess
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
import httpx,psycopg,uvicorn
from psycopg.types.json import Jsonb
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import StreamingResponse
from dotenv import dotenv_values
from assistant_pool_probe import creds,STATE,rpc,until
from app.core.database import create_pool
from app.core.config import get_settings
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,PrivateSocketServer
from app.features.assistant.auth import issue,redeem
from app.features.assistant import gateway
from app.features.assistant.reimbursement import inputs,uploaded_path,publication
from app.features.assistant.resources import call

async def main():
 uid=str(uuid4());gid="reimbursement-"+uid[:8];pw=uuid4().hex+"X1"
 real=os.getenv("REIMBURSEMENT_REAL_MODEL")=="1"
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 manager=server=task=None;old=None;captured=[];outputs=[];checks=[]
 acceptance=json.loads((STATE/"acceptance-db.json").read_text())
 with psycopg.connect(acceptance["adminDsn"]) as c:
  skill=c.execute("SELECT data FROM skill_publications WHERE id='travel-reimbursement-cn' AND enabled").fetchone()[0]
 example=json.loads(base64.b64decode(next(r["contentBase64"] for r in skill["resources"] if r["path"]=="references/examples/input.example.json")))
 profile={"姓名":"验收测试员","部门":"技术部","职务":"工程师","银行卡":"0000000000000000","开户行":"测试银行"}
 settings=dotenv_values(STATE/"acceptance-preview.env")
 model_name=json.loads(settings.get("DEPARTMENT_AI_MODELS",'["department-test"]'))[0] if real else "department-test"
 os.environ["DOCLING_BASE_URL"]=settings.get("DOCLING_BASE_URL","http://127.0.0.1:15001")
 try:
  with psycopg.connect(creds["adminDsn"]) as c:
   old=c.execute("SELECT data,enabled,space_id,submission_id FROM skill_publications WHERE id='travel-reimbursement-cn'").fetchone()
   assert not old,"Test skill ID already exists; do not overwrite"
   c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'报销合成验收',%s,'zkxk',false)",(uid,gid,HASHER.hash(pw)))
   c.execute("INSERT INTO review_submissions(id,space_id,owner_id,kind,title,draft,status,published_id) VALUES(%s,'zkxk',%s,'skills','合成报销验收',%s,'published','travel-reimbursement-cn')",(gid,uid,Jsonb(skill)))
   c.execute("INSERT INTO skill_publications(id,space_id,submission_id,data,enabled) VALUES('travel-reimbursement-cn','zkxk',%s,%s,true)",(gid,Jsonb(skill)))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use","skills.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
  token,_,_=login(db,gid,pw,"reimbursement-test","reimbursement-test");p=authenticate(db,token)[0]
  stub=FastAPI(); uploaded=None
  @stub.post("/v1/chat/completions")
  async def model(request:Request):
   data=await request.json()
   main_request=any(t.get("function",{}).get("name")=="department_reimbursement_generate" for t in data.get("tools",[]))
   if main_request:captured.append(data)
   n=len(captured) if main_request else 0
   if main_request:
    for m in data["messages"]:
     if m.get("role")=="tool":outputs.append(m)
   if real:
    async def forward():
     async with httpx.AsyncClient(timeout=180) as client:
      async with client.stream("POST",settings["DEPARTMENT_AI_MODEL_URL"].rstrip("/")+"/chat/completions",
           headers={"Authorization":"Bearer "+settings["DEPARTMENT_AI_MODEL_KEY"]},json=data) as response:
       response.raise_for_status()
       async for chunk in response.aiter_bytes():yield chunk
    return StreamingResponse(forward(),media_type="text/event-stream")
   async def stream():
    def chunk(delta,finish=None):
     return "data: "+json.dumps({"id":"reimbursement-test","object":"chat.completion.chunk","created":0,"model":"department-test","choices":[{"index":0,"delta":delta,"finish_reason":finish}]})+"\n\n"
    yield chunk({"role":"assistant"})
    if n in (1,2):
     tool,args=("department_uploaded_document_read",{"path":uploaded}) if n==1 else ("department_reimbursement_generate",{"jobJson":json.dumps(example,ensure_ascii=False),"profileJson":json.dumps(profile,ensure_ascii=False)})
     yield chunk({"tool_calls":[{"index":0,"id":"call-"+str(n),"type":"function","function":{"name":tool,"arguments":json.dumps(args,ensure_ascii=False)}}]});yield chunk({},"tool_calls")
    else:
     yield chunk({"content":"测试生成完成，请下载核对。"});yield chunk({},"stop")
    yield "data: [DONE]\n\n"
   return StreamingResponse(stream(),media_type="text/event-stream")
  sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128)
  os.environ["DEPARTMENT_AI_MODEL_URL"]=f"http://127.0.0.1:{sock.getsockname()[1]}/v1"
  os.environ["DEPARTMENT_AI_MODEL_KEY"]="synthetic-local-only"
  server=PrivateSocketServer(uvicorn.Config(stub,log_level="error",access_log=False,lifespan="off"))
  task=asyncio.create_task(server.serve(sockets=[sock]));await until(lambda:server.started,5)
  with TemporaryDirectory(prefix="id-reimb-") as folder:
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder;manager=Manager(db,[model_name])
   try:
    async with manager.lease(p,"zkxk") as runtime:
     origin="http://127.0.0.1:3182"
     os.environ["DEPARTMENT_AI_ORIGINS"]=json.dumps({"zkxk":origin})
     gateway.app.state.manager=manager;gateway.app.state.pool=db
     gateway.app.state.origins={"zkxk":origin};gateway.app.state.settings=get_settings()
     cookie=redeem(db,issue(db,p,"zkxk")["ticket"],origin)
     async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url=origin,
           cookies={"department_ai_zkxk":cookie},headers={"Origin":origin},timeout=240) as browser:
      async def gw_rpc(name,args):
       response=await browser.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),"method":name,"payload":{"args":args}})
       assert response.status_code==200,response.text
       value=response.json()["result"];assert value["ok"],value
       return value.get("value")
      sid=(await gw_rpc("session/create",{"request":{"cwd":"/home/assistant/workspace"}}))["sessionId"]
      receipt=Path(folder)/"验收材料.docx"
      code="from docx import Document; import sys; d=Document(); d.add_paragraph('报销验收材料'); d.add_paragraph('重庆出差 2026-08-11 至 2026-08-12。机票630.00和1290.00，高铁38.00，住宿234.36。北京怀柔2026-08-14当日出差，无票据。'); d.save(sys.argv[1])"
      subprocess.run(["/usr/bin/python3","-c",code,str(receipt)],check=True)
      bad=await browser.post("/api/session/uploadFileBinary",params={"sessionId":"foreign","name":"test.docx"},content=receipt.read_bytes(),headers={"Content-Type":"application/octet-stream"})
      assert bad.status_code==409,bad.text
      response=await browser.post("/api/session/uploadFileBinary",params={"sessionId":sid,"name":receipt.name},content=receipt.read_bytes(),headers={"Content-Type":"application/octet-stream"})
      assert response.status_code==200,response.text
      value=response.json();assert value["ok"],value
      ref=value["value"]["file"];digest=ref["attachmentId"].split(":")[1]
      uploaded=f"/home/assistant/dsh/attachments/v1/files/{digest[:2]}/{digest}/{ref['name']}"
      checks.append("native authenticated upload and foreign session rejection");print("PASS",checks[-1],flush=True)
      try:call(db,p,"zkxk","department_skill_get",{"id":"travel-reimbursement-cn","resource":"scripts/generate_documents.py"})
      except HTTPException as e:assert e.status_code==403
      else:raise AssertionError("script source exposed")
      for bad_path in ("/etc/passwd","/home/assistant/dsh/settings.json",uploaded.replace("/files/","/files/../")):
       try:uploaded_path(runtime,bad_path)
       except HTTPException:pass
       else:raise AssertionError(bad_path)
      prompt="合成验收：读取上传报销材料，然后按确认的测试数据执行生成。"
      if real:
       prompt+="先读取部门规则和已发布报销技能说明，再读取附件正文，最后调用报销生成工具并返回下载链接。以下全部是合成测试资料，已由我确认，可以直接生成，无需再次询问。金额以附件为依据。个人资料："+json.dumps(profile,ensure_ascii=False)+"。已确认任务数据："+json.dumps(example,ensure_ascii=False)
      await gw_rpc("session/prompt",{"request":{"sessionId":sid,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":prompt},{"type":"file","receiptId":value["value"]["receiptId"]}]}})
      await until(lambda:any("downloadUrl" in json.dumps(m,ensure_ascii=False) for m in outputs),500 if real else 230)
      assert uploaded in json.dumps(captured[0]["messages"],ensure_ascii=False),"native file receipt not attached"
      from app.features.assistant.activity import activity
      async with asyncio.timeout(60):
       while any((await activity(runtime)).values()):await asyncio.sleep(.2)
      text=json.dumps(outputs,ensure_ascii=False)
      (STATE/"reimbursement-tool-results.private.json").write_text(text)
      (STATE/"reimbursement-tool-results.private.json").chmod(0o600)
      assert "234.36" in text and "重庆" in text,text[-2000:]
      # Native tools render structured output as a text block.
      result=None
      for message in outputs:
       content=message.get("content","")
       if not isinstance(content,str):content=json.dumps(content,ensure_ascii=False)
       if '"downloadUrl"' in content:
        try:result=json.loads(content)
        except ValueError:pass
        if result and "files" not in result and "text" in result:result=json.loads(result["text"])
      if not result:
       # Keep exact native evidence to diagnose serialization changes.
       raise AssertionError("generated tool payload missing: "+text[-3000:])
      assert len([f for f in result["files"] if f["name"].endswith(".docx")])==5,result
      evidence=STATE/"reimbursement-output";evidence.mkdir(exist_ok=True,mode=0o700)
      for file in result["files"]:
       response=await browser.get(file["downloadUrl"])
       assert response.status_code==200,(file,response.text[:300])
       assert "attachment" in response.headers.get("content-disposition","")
       if file["name"].endswith(".docx"):
        with ZipFile(BytesIO(response.content)) as archive:
         xml=ElementTree.fromstring(archive.read("word/document.xml"))
         words="".join(n.text or "" for n in xml.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        if "审批单" in file["name"]:assert "事前审批" in words and "部门负责人签字" in words
        if "创新创业报销单" in file["name"]:assert "2702.36" in words and "财务负责人" in words and "出纳" in words
       target=evidence/file["name"];target.parent.mkdir(parents=True,exist_ok=True)
       target.write_bytes(response.content);target.chmod(0o600)
      checks.append("native model tools parse actual DOCX via Docling and generate five DOCX");print("PASS",checks[-1],flush=True)
      checks.append("authenticated native download of all five DOCX and report");print("PASS",checks[-1],flush=True)
      denied=await browser.get("/api/file",params={"path":"/etc/passwd"});assert denied.status_code in (403,404)
      with psycopg.connect(creds["adminDsn"]) as c:c.execute("UPDATE permission_groups SET actions=%s WHERE id=%s",(Jsonb(["assistant.use"]),gid))
      denied=await browser.get(result["files"][0]["downloadUrl"]);assert denied.status_code in (403,409),denied.text
      checks.append("use without source access; private paths and revoked grant rejected");print("PASS",checks[-1],flush=True)
   finally:
    await manager.close();manager=None
  (STATE/("reimbursement-real-model-results.json" if real else "reimbursement-live-results.json")).write_text(json.dumps({"passed":True,"checks":checks,"model":model_name if real else "synthetic; actual native tools, parser and worker","productionUnchanged":True},ensure_ascii=False,indent=2))
 finally:
  if manager:await manager.close()
  if server:server.should_exit=True
  if task:await task
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(uid,))
   c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
   if not old:c.execute("DELETE FROM skill_publications WHERE id='travel-reimbursement-cn'")
   c.execute("DELETE FROM review_submissions WHERE id=%s",(gid,))
  db.close()
if __name__=="__main__":asyncio.run(main())
