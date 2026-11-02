"""Opt-in disposable pool proof. Not imported by the gateway or deployed services.
Run on Aliyun in the identity worktree. One slot, accelerated 2s idle timer.
Real Harness; deterministic local model + blocking synthetic tool, no paid calls.
"""
import asyncio,json,os,socket,threading,time
from contextlib import asynccontextmanager,suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import httpx,psycopg,websockets
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb

ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
assert str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028")
creds=json.loads((STATE/"credentials.json").read_text())
assert all("@127.0.0.1:15433/identity_test" in creds[k] for k in ("adminDsn","appDsn"))
os.environ.update({k:v for k,v in dotenv_values(STATE/"app.env").items() if v is not None})
os.environ["DEPARTMENT_AI_RUNTIME_MODE"]="isolated"
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.auth import live_principal
from app.features.assistant.runtime import Manager,Runtime,PrivateSocketServer,docker
import uvicorn

async def rpc(runtime,name,args):
 r=await runtime.client.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),
        "method":name,"payload":{"args":args}})
 r.raise_for_status();result=r.json()["result"]
 assert result["ok"],(name,result)
 return result.get("value")

def control_busy(rows,baseline):
 if not isinstance(rows,dict) or not isinstance(rows.get("items"),list):raise ValueError("unknown session list")
 if not isinstance(baseline,dict) or baseline.get("type")!="baseline":raise ValueError("unknown control baseline")
 value=baseline["value"]
 for field in ("queues","jobs"):
  if not isinstance(value.get(field),dict) or any(not isinstance(x,list) for x in value[field].values()):
   raise ValueError("unknown "+field)
 if any(type(row.get("running")) is not bool for row in rows["items"]):raise ValueError("unknown running")
 running=any(row["running"] for row in rows["items"])
 queued=any(value["queues"].values())
 jobs=any(job.get("status") not in ("completed","killed","failed") for js in value["jobs"].values() for job in js)
 return {"running":running,"queued":queued,"jobs":jobs}

async def activity(runtime):
 # No browser needed: inspect actual engine state even after user disconnects.
 async with asyncio.timeout(10):
  rows=await rpc(runtime,"session/list",{"_request":{}})
  async with websockets.unix_connect(str(runtime.socket),uri="ws://runtime/api/remote.mux") as ws:
   await ws.send(json.dumps({"type":"open","streamId":"probe-control","endpoint":"session/control","payload":{"args":{}}}))
   first=json.loads(await ws.recv())
   if first.get("type")!="item":raise ValueError("missing control state")
   return control_busy(rows,first.get("value"))

class ProbePool(Manager):
 """Small experiment only: no public endpoints, multiworker use or UI queue contract."""
 def __init__(self,pool,models):
  super().__init__(pool,models)
  self.pending={};self.start_order=[];self.stops=[];self.failures=0
  self.slots=1;self.idle=2.;self.peak=0
 @asynccontextmanager
 async def lease(self,p,space):
  key=p.user_id+"-"+space;entry=None;runtime=None
  try:
   async with self.lock:
    entry=self.pending.setdefault(key,{"waiters":0})
    entry["waiters"]+=1
   while runtime is None:
    async with self.lock:
     live_principal(self.pool,p.session_id,space) # revoked queued logins do not start
     old=self.items.get(key)
     if old:
      old.validate()
      if old.session!=p.session_id:raise RuntimeError("login changed; do not kill active work")
      runtime=old
     elif next(iter(self.pending),None)==key and len(self.items)<self.slots:
      # ponytail: sequential cold starts in this one-slot probe; production needs
      # cancellable background startup rather than holding the admission lock.
      runtime=Runtime(self,p,space);self.items[key]=runtime
      runtime._leases=0;runtime._idle_since=None
      self.peak=max(self.peak,len(self.items))
      try:await runtime.start()
      except BaseException:
       await runtime.stop();self.items.pop(key,None);runtime=None;raise
      self.start_order.append(key)
     if runtime:
      runtime._leases+=1;runtime.last=time.monotonic();runtime._idle_since=None
      self.pending.pop(key,None)
    if runtime is None:await asyncio.sleep(.1)
   yield runtime
  finally:
   async with self.lock:
    if entry:
     entry["waiters"]-=1
     if not entry["waiters"] and self.pending.get(key) is entry:self.pending.pop(key,None)
    if runtime:
     runtime.last=time.monotonic();runtime._leases-=1
 async def reap_once(self):
  async with self.lock:
   for key,r in list(self.items.items()):
    if r._leases or not r.ready:continue
    try:
     r.validate()
     state=await activity(r)
    except Exception:
     # Unknown engine state must never count as proof that work has finished.
     self.failures+=1;r._idle_since=None;continue
    if any(state.values()):
     r._idle_since=None;continue
    now=time.monotonic()
    if r._idle_since is None:r._idle_since=now
    if now-max(r.last,r._idle_since)<self.idle:continue
    # All probe ingress takes the same lease lock: no prompt can race this stop.
    await r.stop();self.items.pop(key,None);self.stops.append(key)
 async def sweep(self):
  while True:
   await asyncio.sleep(.25);await self.reap_once()
 async def request(self,p,space,name,args):
  async with self.lease(p,space) as r:return await rpc(r,name,args)

checks=[]
def check(name,condition=True):
 assert condition,name
 checks.append(name);print("PASS "+name,flush=True)
async def until(predicate,seconds=120):
 async with asyncio.timeout(seconds):
  while not predicate():await asyncio.sleep(.1)

async def main():
 users=[];gid="pool-"+uuid4().hex[:8];db=create_pool(creds["appDsn"]);db.open(wait=True)
 tool_release=threading.Event();model_release=asyncio.Event();model_started=asyncio.Event();tool_started=asyncio.Event()
 server=None;server_task=None;manager=None;monitor=None;pending_tasks=[]
 loop=asyncio.get_running_loop()
 result={"mode":"probe only, one slot, 2-second idle; synthetic model/tool","checks":checks}
 try:
  # Pure policy cases supplement real model/tool runs; background jobs are disabled
  # in the managed preset, so do not pretend these are native job execution tests.
  empty={"items":[]}
  base=lambda queues={},jobs={}:{"type":"baseline","value":{"queues":queues,"jobs":jobs}}
  check("queued messages and running/stopping/unknown job states block idle",
    control_busy(empty,base({"s":[{}]}))["queued"] and all(
     control_busy(empty,base(jobs={"s":[{"status":x}]}))["jobs"] for x in ("running","stopping","unknown")))
  check("only completed/killed/failed jobs are terminal",not any(control_busy(empty,base(jobs={"s":[{"status":"completed"}]})).values()))
  try:control_busy({},base())
  except ValueError:check("malformed activity state is not treated as idle")
  else:raise AssertionError("malformed activity accepted")
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   for label,space in (("A","zkxk"),("B","senyuan"),("C","zkxk")):
    u={"id":str(uuid4()),"username":gid+"-"+label.lower(),"password":uuid4().hex+"X1","space":space}
    c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'实例池合成测试',%s,%s,false)",(u["id"],u["username"],HASHER.hash(u["password"]),space))
    c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(u["id"],space,gid))
    users.append(u)
  principals=[]
  for u in users:
   token,_,_=login(db,u["username"],u["password"],"pool-probe","pool-probe")
   principals.append(authenticate(db,token)[0])
  a,b,c=principals
  stub=FastAPI();calls=0
  @stub.post("/v1/chat/completions")
  async def model():
   nonlocal calls
   calls+=1;number=calls
   async def stream():
    def chunk(delta,finish=None):
     return "data: "+json.dumps({"id":"pool-probe","object":"chat.completion.chunk","created":0,"model":"department-test","choices":[{"index":0,"delta":delta,"finish_reason":finish}]})+"\n\n"
    yield chunk({"role":"assistant"})
    if number==1:
     model_started.set()
     await asyncio.wait_for(model_release.wait(),90)
     yield chunk({"tool_calls":[{"index":0,"id":"pool-tool","type":"function","function":{"name":"department_processes","arguments":"{}"}}]})
     yield chunk({},"tool_calls")
    else:
     yield chunk({"content":"POOL_COMPLETED_PERSISTENT_MARKER"})
     yield chunk({},"stop")
    yield "data: [DONE]\n\n"
   return StreamingResponse(stream(),media_type="text/event-stream")
  sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128)
  port=sock.getsockname()[1]
  os.environ["DEPARTMENT_AI_MODEL_URL"]=f"http://127.0.0.1:{port}/v1"
  os.environ["DEPARTMENT_AI_MODEL_KEY"]="synthetic-local-only"
  server=PrivateSocketServer(uvicorn.Config(stub,log_level="error",access_log=False,lifespan="off"))
  server_task=asyncio.create_task(server.serve(sockets=[sock]))
  await until(lambda:server.started,5)
  def slow_tool(pool,p,space,name,args):
   assert p.user_id==a.user_id and space=="zkxk" and name=="department_processes"
   loop.call_soon_threadsafe(tool_started.set)
   if not tool_release.wait(90):raise TimeoutError("probe tool not released")
   return {"items":[],"marker":"SYNTHETIC_TOOL_COMPLETED"}
  with TemporaryDirectory(prefix="id-pool-") as folder,patch("app.features.assistant.gateway.call",side_effect=slow_tool):
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
   manager=ProbePool(db,["department-test"])
   try:
    start=time.monotonic()
    async with manager.lease(a,"zkxk") as ar:
     sid=(await rpc(ar,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
     ar.session_epoch(sid,create=True)
     await rpc(ar,"session/rename",{"request":{"sessionId":sid,"title":"A-persisted-pool-session"}})
     await rpc(ar,"settings/update",{"ns":"locale","patch":{"preference":"zh"}})
     (ar.root/"home/workspace/persist.txt").write_text("A preserved")
     result["firstStartupSeconds"]=round(time.monotonic()-start,1)
     print("First Harness ready; starting long task",flush=True)
     await rpc(ar,"session/prompt",{"request":{"sessionId":sid,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":"合成验证：调用部门流程工具后回答。"}]}})
    await asyncio.wait_for(model_started.wait(),30)
    monitor=asyncio.create_task(manager.sweep())
    async def queued(p,space):
     async with manager.lease(p,space) as r:
      return {"runtime":r,"sessions":await rpc(r,"session/list",{"_request":{}})}
    bt=asyncio.create_task(queued(b,"senyuan"));pending_tasks.append(bt)
    await until(lambda:b.user_id+"-senyuan" in manager.pending,3)
    ct=asyncio.create_task(queued(c,"zkxk"));pending_tasks.append(ct)
    duplicate=asyncio.create_task(queued(b,"senyuan"));pending_tasks.append(duplicate)
    await until(lambda:len(manager.pending)==2 and manager.pending[b.user_id+"-senyuan"]["waiters"]==2,3)
    check("full pool queues FIFO; duplicate user has one queue position",list(manager.pending)==[b.user_id+"-senyuan",c.user_id+"-zkxk"])
    duplicate.cancel()
    with suppress(asyncio.CancelledError):await duplicate
    check("cancelling duplicate request retains original queue position",manager.pending[b.user_id+"-senyuan"]["waiters"]==1)
    await manager.request(a,"zkxk","session/prompt",{"request":{"sessionId":sid,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":"第二个排队的合成消息"}]}})
    state=await activity(ar)
    check("native pending message queue observed",state["queued"])
    await asyncio.sleep(3)
    state=await activity(ar)
    check("model execution survives idle threshold without browser connection",state["running"] and not ar.stopped and not bt.done())
    ct.cancel()
    with suppress(asyncio.CancelledError):await ct
    check("cancelled queued user removed without starting a container",c.user_id+"-zkxk" not in manager.pending and len(manager.start_order)==1)
    model_release.set();await asyncio.wait_for(tool_started.wait(),30)
    await asyncio.sleep(3)
    check("blocking tool survives idle threshold; next user still waits",not ar.stopped and not bt.done() and (await activity(ar))["running"])
    tool_release.set()
    # At least the tool-result continuation and the queued prompt must complete.
    await until(lambda:calls>=3,30)
    result_b=await asyncio.wait_for(bt,150)
    br=result_b["runtime"]
    check("completed A is reclaimed and B automatically admitted",ar.stopped and manager.start_order==[a.user_id+"-zkxk",b.user_id+"-senyuan"])
    check("reclaim retains A persisted directory and file",(ar.root/"home/workspace/persist.txt").read_text()=="A preserved")
    check("B cannot list A history",sid not in json.dumps(result_b["sessions"]))
    # Keep B leased while testing failed status reads and a blocked concurrent reaper.
    async with manager.lease(b,"senyuan") as br:
     desc=await rpc(br,"settings/describe",{})
     loc=next(x for x in desc["namespaces"] if x["ns"]=="locale")
     check("B personal locale does not inherit A",loc["value"].get("preference")!="zh")
     br.last=time.monotonic()-100
     await manager.reap_once()
     check("in-flight HTTP lease prevents reclamation",not br.stopped)
    monitor.cancel()
    with suppress(asyncio.CancelledError):await monitor
    monitor=None
    br.last=time.monotonic()-100;br._idle_since=time.monotonic()-100
    async def broken(_):raise TimeoutError("synthetic unavailable status")
    with patch(__name__+".activity",side_effect=broken):
     await manager.reap_once()
    check("unreadable engine status preserves instance",not br.stopped and manager.failures>0 and br._idle_since is None)
    monitor=asyncio.create_task(manager.sweep())
    # Revoke a queued user before admission; authentication must be rechecked.
    revoked=asyncio.create_task(queued(c,"zkxk"));pending_tasks.append(revoked)
    await until(lambda:c.user_id+"-zkxk" in manager.pending,3)
    with psycopg.connect(creds["adminDsn"]) as conn:
     conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE id=%s",(c.session_id,))
    try:await asyncio.wait_for(revoked,5)
    except Exception as e:
     check("revoked waiting login rejected without consuming slot",getattr(e,"status_code",None)==401 and c.user_id+"-zkxk" not in manager.pending)
    else:raise AssertionError("revoked user admitted")
    again=asyncio.create_task(queued(a,"zkxk"));pending_tasks.append(again)
    await asyncio.wait_for(again,150)
    async with manager.lease(a,"zkxk") as ar2:
     check("A restart restores original session",sid in json.dumps(await rpc(ar2,"session/list",{"_request":{}})))
     ar2.session_epoch(sid)
     desc=await rpc(ar2,"settings/describe",{})
     check("A restart restores personal settings and authorization binding",next(x for x in desc["namespaces"] if x["ns"]=="locale")["value"]["preference"]=="zh")
     async with websockets.unix_connect(str(ar2.socket),uri="ws://runtime/api/remote.mux") as ws:
      await ws.send(json.dumps({"type":"open","streamId":"history","endpoint":"session/follow","payload":{"args":{"request":{"address":{"kind":"session","sessionId":sid}}}}}))
      first=json.loads(await asyncio.wait_for(ws.recv(),15))
      check("completed task output persists after recycle", "POOL_COMPLETED_PERSISTENT_MARKER" in json.dumps(first))
     stats=json.loads(await docker("stats","--no-stream","--format","{{json .}}",ar2.name))
     result["resourceSnapshot"]={k:stats[k] for k in ("MemUsage","CPUPerc","PIDs")}
     check("never more than one active personal instance",manager.peak==1 and len(manager.items)==1)
     result["startCount"]=len(manager.start_order);result["recycleCount"]=len(manager.stops)
     result["namespace"]=manager.namespace
   finally:
    model_release.set();tool_release.set()
    for t in pending_tasks:
     if not t.done():t.cancel()
    await asyncio.gather(*pending_tasks,return_exceptions=True)
    if monitor:
     monitor.cancel()
     with suppress(asyncio.CancelledError):await monitor
    await manager.close()
   left=await docker("ps","-aq","--filter","name=department-id-ai-"+manager.namespace+"-")
   check("temporary containers cleaned",not left)
  check("temporary runtime directory cleaned",not Path(folder).exists())
  result["passed"]=True
 finally:
  model_release.set();tool_release.set()
  if server:
   server.should_exit=True
   if server_task:await server_task
  with psycopg.connect(creds["adminDsn"]) as conn:
   for u in users:
    conn.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
    conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(u["id"],))
    conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["id"],))
   conn.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  db.close()
  result["testAccountsDisabled"]=True
  (STATE/"assistant-pool-probe-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print("Pool proof complete; no deployed runtime modified",flush=True)
if __name__=="__main__":asyncio.run(main())

