"""Native managed persona and context tool, synthetic model; isolated DB and container."""
import asyncio,json,os,socket
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import psycopg,uvicorn
from psycopg.types.json import Jsonb
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
from assistant_pool_probe import creds,STATE,rpc,until
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,PrivateSocketServer
from app.features.assistant.activity import activity

async def main():
 uid=str(uuid4());gid="persona-"+uid[:8];pw=uuid4().hex+"X1";captured=[]
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 manager=server=task=None
 try:
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'模式合成测试',%s,'zkxk',false)",(uid,gid,HASHER.hash(pw)))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
  token,_,_=login(db,gid,pw,"persona-test","persona-test");p=authenticate(db,token)[0]
  stub=FastAPI()
  @stub.post("/v1/chat/completions")
  async def model(request:Request):
   data=await request.json()
   main_request=any(t.get("function",{}).get("name")=="department_context_get" for t in data.get("tools",[]))
   if main_request:captured.append(data)
   number=len(captured) if main_request else 0
   async def stream():
    def chunk(delta,finish=None):
     return "data: "+json.dumps({"id":"persona-test","object":"chat.completion.chunk","created":0,"model":"department-test","choices":[{"index":0,"delta":delta,"finish_reason":finish}]})+"\n\n"
    yield chunk({"role":"assistant"})
    if main_request and number==1:
     yield chunk({"tool_calls":[{"index":0,"id":"context-call","type":"function","function":{"name":"department_context_get","arguments":"{}"}}]})
     yield chunk({},"tool_calls")
    else:
     yield chunk({"content":"部门助手合成验证完成。"});yield chunk({},"stop")
    yield "data: [DONE]\n\n"
   return StreamingResponse(stream(),media_type="text/event-stream")
  sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128)
  os.environ["DEPARTMENT_AI_MODEL_URL"]=f"http://127.0.0.1:{sock.getsockname()[1]}/v1"
  os.environ["DEPARTMENT_AI_MODEL_KEY"]="synthetic-local-only"
  server=PrivateSocketServer(uvicorn.Config(stub,log_level="error",access_log=False,lifespan="off"))
  task=asyncio.create_task(server.serve(sockets=[sock]));await until(lambda:server.started,5)
  with TemporaryDirectory(prefix="id-persona-") as folder:
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder;manager=Manager(db,["department-test"])
   try:
    async with manager.lease(p,"zkxk") as runtime:
     sid=(await rpc(runtime,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
     runtime.session_epoch(sid,create=True)
     await rpc(runtime,"session/prompt",{"request":{"sessionId":sid,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":"合成测试，读取部门工作规则。"}]}})
     await until(lambda:len(captured)>=2,60)
     async with asyncio.timeout(30):
      while any((await activity(runtime)).values()):await asyncio.sleep(.2)
     first=captured[0]
     prompt=json.dumps(first["messages"],ensure_ascii=False)
     expected=Path("harness/identity/persona.md").read_text().strip()
     assert json.dumps(expected,ensure_ascii=False)[1:-1] in prompt,"managed persona missing from native model request"
     names={x["function"]["name"] for x in first["tools"]}
     assert "department_context_get" in names
     assert names>={"department_context_get","department_processes","department_knowledge_search","department_document_get","department_skill_list","department_skill_get","department_uploaded_document_read","department_reimbursement_generate"},names
     assert {"bash","skill","ask_user_question","todo_write","read","write","edit","grep","glob"} <= names,names
     assert not any("mcp" in n for n in names),names
     print("TOOLS",sorted(names),flush=True)
     results=[m for m in captured[1]["messages"] if m.get("role")=="tool"]
     serialized=json.dumps(results,ensure_ascii=False)
     assert results, str(captured[1]["messages"])[-1200:]
     (STATE/"persona-synthetic-tool-result.json").write_text(serialized)
     assert all(x in serialized for x in ("defaultLanguage","principles","draftByDefault","部门助手","zkxk"))
     assert "skillDirectory" not in serialized and "siliconflow" not in serialized
     print("PASS native model receives complete managed persona")
     print("PASS native context tool call returns scoped business defaults")
     print("PASS restored native tools with authorized company bridge; no legacy MCP")
   finally:
    await manager.close();manager=None
  (STATE/"assistant-persona-live-results.json").write_text(json.dumps({"passed":True,"checks":3,"model":"synthetic","productionUnchanged":True}))
 finally:
  if manager:await manager.close()
  if server:server.should_exit=True
  if task:await task
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(uid,))
   c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  db.close()
if __name__=="__main__":asyncio.run(main())
