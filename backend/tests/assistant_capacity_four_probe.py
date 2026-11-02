"""Four-instance capacity probe. Synthetic data/model, never deploys pool changes.
Reuse one-slot proof's manager to expose both capacity and admission-lock limits.
"""
import asyncio,json,os,re,socket,time,statistics
import websockets
from contextlib import suppress,asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import httpx,psycopg,uvicorn
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from assistant_pool_probe import ROOT,STATE,creds,ProbePool,activity,rpc,until
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import PrivateSocketServer,docker,Runtime
from app.features.assistant.auth import live_principal


RESULT_PATH=STATE/"assistant-capacity-four-results.json"

class NonblockingProbePool(ProbePool):
 """Capacity experiment: reserve slots under lock, start containers outside it."""
 def __init__(self,*args):
  super().__init__(*args);self.starting={}
 @asynccontextmanager
 async def lease(self,p,space):
  key=p.user_id+"-"+space;entry=None;runtime=None
  try:
   async with self.lock:
    entry=self.pending.setdefault(key,{"waiters":0});entry["waiters"]+=1
   while runtime is None:
    startup=None;candidate=None
    async with self.lock:
     live_principal(self.pool,p.session_id,space)
     old=self.items.get(key)
     if old:
      old.validate()
      if old.session!=p.session_id:raise RuntimeError("login changed")
      if old.ready:runtime=old
      else:startup=self.starting[key];candidate=old
     elif next(iter(self.pending),None)==key and len(self.items)<self.slots:
      candidate=Runtime(self,p,space);candidate._leases=0;candidate._idle_since=None
      self.items[key]=candidate;self.peak=max(self.peak,len(self.items))
      startup=asyncio.create_task(candidate.start());self.starting[key]=startup
      self.pending.pop(key,None)
     if runtime:
      runtime._leases+=1;runtime.last=time.monotonic();runtime._idle_since=None
      self.pending.pop(key,None)
    if startup:
     try:await asyncio.shield(startup)
     except asyncio.CancelledError:raise
     except Exception:
      async with self.lock:
       if self.items.get(key) is candidate:
        await candidate.stop();self.items.pop(key,None)
       self.starting.pop(key,None)
      raise
     else:
      async with self.lock:
       if self.starting.get(key) is startup:
        self.starting.pop(key,None);self.start_order.append(key)
    elif runtime is None:await asyncio.sleep(.1)
   yield runtime
  finally:
   async with self.lock:
    if entry:
     entry["waiters"]-=1
     if not entry["waiters"] and self.pending.get(key) is entry:self.pending.pop(key,None)
    if runtime:runtime.last=time.monotonic();runtime._leases-=1
 async def close(self):
  for task in self.starting.values():task.cancel()
  await asyncio.gather(*self.starting.values(),return_exceptions=True)
  self.starting.clear()
  await super().close()

result={"passed":False,"mode":"4 containers; synthetic streaming + department tool; no real provider/OCR/script load",
 "checks":[],"hostSamples":[],"startupSeconds":[],"httpLatencySeconds":[],"snapshots":{}}
def check(name,value=True):
 assert value,name
 result["checks"].append(name);print("PASS "+name,flush=True)
def host():
 m={k:int(v) for k,v in re.findall(r"^(\w+):\s+(\d+)",Path("/proc/meminfo").read_text(),re.M)}
 c=list(map(int,Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
 return {"availableMiB":round(m["MemAvailable"]/1024,1),"totalMiB":round(m["MemTotal"]/1024,1),
         "load":list(map(float,Path("/proc/loadavg").read_text().split()[:3])),
         "cpuTotal":sum(c),"cpuIdle":c[3]+c[4]}
async def snapshot(label,manager):
 names=[r.name for r in manager.items.values() if r.ready and not r.stopped]
 rows=[json.loads(x) for x in (await docker("stats","--no-stream","--format","{{json .}}",*names)).splitlines()]
 result["snapshots"][label]=[{"memory":x["MemUsage"],"cpu":x["CPUPerc"],"tasks":x["PIDs"]} for x in rows]
 print("SNAPSHOT "+label+" "+json.dumps(result["snapshots"][label]),flush=True)
async def history(runtime,sid):
 async with websockets.unix_connect(str(runtime.socket),uri="ws://runtime/api/remote.mux") as ws:
  await ws.send(json.dumps({"type":"open","streamId":"verify-history","endpoint":"session/follow",
    "payload":{"args":{"request":{"address":{"kind":"session","sessionId":sid}}}}}))
  first=json.loads(await asyncio.wait_for(ws.recv(),15))
  assert first.get("type")=="item"
  return json.dumps(first)
async def main():
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 users=[];gid="capacity-"+uuid4().hex[:8];tasks=[];watcher=None;server=None;server_task=None;manager=None
 started=[asyncio.Event() for _ in range(5)];release=[asyncio.Event() for _ in range(5)]
 tool_calls=[];main_task=asyncio.current_task()
 endpoints=[(3080,"/",401),(3081,"/health",200),(3181,"/health",200)]
 async def watch():
  previous=None;bad=0
  async with httpx.AsyncClient(timeout=4,follow_redirects=False) as client:
   while True:
    sample=host();sample["time"]=round(time.monotonic(),1)
    if previous:
     total=sample["cpuTotal"]-previous["cpuTotal"];idle=sample["cpuIdle"]-previous["cpuIdle"]
     sample["hostCpuPercent"]=round(100*(1-idle/max(total,1)),1)
    previous=sample
    statuses={}
    for port,path,expected in endpoints:
     at=time.monotonic()
     try:
      response=await client.get(f"http://127.0.0.1:{port}{path}")
      statuses[str(port)]={"status":response.status_code,"seconds":round(time.monotonic()-at,3)}
     except httpx.HTTPError:
      statuses[str(port)]={"status":0,"seconds":round(time.monotonic()-at,3)}
    sample["health"]=statuses;result["hostSamples"].append(sample)
    bad=bad+1 if any(statuses[str(p)]["status"]!=e for p,_,e in endpoints) else 0
    if sample["availableMiB"]<1200 or bad>=2:
     result["aborted"]="host reserve below 1200 MiB or consecutive health failures"
     print("ABORT "+result["aborted"],flush=True);main_task.cancel();return
    await asyncio.sleep(5)
 try:
  assert host()["availableMiB"]>3000,"not enough initial headroom for four-instance test"
  with psycopg.connect(creds["adminDsn"]) as conn:
   conn.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   for n in range(5):
    space="zkxk" if n%2==0 else "senyuan"
    u={"id":str(uuid4()),"username":gid+"-"+str(n),"password":uuid4().hex+"X1","space":space}
    conn.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'四实例容量合成账号',%s,%s,false)",(u["id"],u["username"],HASHER.hash(u["password"]),space))
    conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(u["id"],space,gid));users.append(u)
  principals=[]
  for u in users:
   token,_,_=login(db,u["username"],u["password"],"capacity-probe","capacity-probe")
   principals.append(authenticate(db,token)[0])
  stub=FastAPI()
  @stub.post("/v1/chat/completions")
  async def model(request:Request):
   data=await request.json()
   matches=re.findall(r"CAP4_USER_(\d)",json.dumps(data.get("messages",[])))
   assert matches,"missing synthetic user marker"
   n=int(matches[-1]);has_tool=any(m.get("role")=="tool" for m in data.get("messages",[]))
   async def stream():
    def chunk(delta,finish=None):
     return "data: "+json.dumps({"id":"capacity","object":"chat.completion.chunk","created":0,
       "model":"department-test","choices":[{"index":0,"delta":delta,"finish_reason":finish}]})+"\n\n"
    yield chunk({"role":"assistant"})
    if not has_tool:
     started[n].set()
     async with asyncio.timeout(240):
      while not release[n].is_set():
       yield chunk({"content":f"CAP4_{n}_STREAM "})
       try:await asyncio.wait_for(release[n].wait(),2)
       except TimeoutError:pass
     yield chunk({"tool_calls":[{"index":0,"id":"cap-tool-"+str(n),"type":"function",
            "function":{"name":"department_processes","arguments":"{}"}}]})
     yield chunk({},"tool_calls")
    else:
     yield chunk({"content":f"CAP4_{n}_COMPLETE"});yield chunk({},"stop")
    yield "data: [DONE]\n\n"
   return StreamingResponse(stream(),media_type="text/event-stream")
  sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128)
  os.environ["DEPARTMENT_AI_MODEL_URL"]=f"http://127.0.0.1:{sock.getsockname()[1]}/v1"
  os.environ["DEPARTMENT_AI_MODEL_KEY"]="synthetic-local-only"
  server=PrivateSocketServer(uvicorn.Config(stub,log_level="error",access_log=False,lifespan="off"))
  server_task=asyncio.create_task(server.serve(sockets=[sock]));await until(lambda:server.started,5)
  def synthetic_tool(pool,p,space,name,args):
   n=next(i for i,u in enumerate(users) if u["id"]==p.user_id)
   assert space==users[n]["space"] and name=="department_processes"
   tool_calls.append(n);return {"marker":f"CAP4_{n}_TOOL","items":[]}
  with TemporaryDirectory(prefix="id-cap4-") as folder,patch("app.features.assistant.gateway.call",side_effect=synthetic_tool):
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
   manager=NonblockingProbePool(db,["department-test"]);manager.slots=4;manager.idle=2.
   result["namespace"]=manager.namespace
   watcher=asyncio.create_task(watch())
   runtimes=[None]*4;sessions=[None]*4
   try:
    async def start_user(n):
     at=time.monotonic()
     async with manager.lease(principals[n],users[n]["space"]) as r:
      sid=(await rpc(r,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
      await rpc(r,"session/rename",{"request":{"sessionId":sid,"title":f"CAP4_USER_{n}"}})
      await rpc(r,"settings/update",{"ns":"locale","patch":{"preference":"zh" if n%2==0 else "en"}})
      r.session_epoch(sid,create=True);runtimes[n]=r;sessions[n]=sid
     elapsed=round(time.monotonic()-at,1);result["startupSeconds"].append(elapsed)
     print(f"READY {n+1}/4 startup={elapsed}s available={host()['availableMiB']}MiB",flush=True)
    await asyncio.gather(*(start_user(n) for n in range(4)))
    check("four real personal instances simultaneously ready",len(manager.items)==4)
    await snapshot("fourReady",manager)
    async def measured_read(n,through_pool=True):
     at=time.monotonic()
     if through_pool:
      rows=await manager.request(principals[n],users[n]["space"],"session/list",{"_request":{}})
     else:rows=await rpc(runtimes[n],"session/list",{"_request":{}})
     elapsed=time.monotonic()-at
     assert sessions[n] in json.dumps(rows)
     assert not any(s in json.dumps(rows) for i,s in enumerate(sessions) if i!=n)
     return elapsed
    for _ in range(3):
     result["httpLatencySeconds"].extend(await asyncio.gather(*(measured_read(n) for n in range(4))))
    check("four users concurrent history reads preserve isolation")
    for n in range(4):
     await manager.request(principals[n],users[n]["space"],"session/prompt",
       {"request":{"sessionId":sessions[n],"requestId":str(uuid4()),"mode":"queue",
                   "content":[{"type":"text","text":f"CAP4_USER_{n} 合成测试，等待后调用部门流程工具。"}]}})
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in started[:4])),30)
    states=await asyncio.gather(*(activity(r) for r in runtimes))
    check("four concurrent native streaming tasks running",all(s["running"] for s in states))
    async def fifth():
     async with manager.lease(principals[4],users[4]["space"]) as r:
      result["fifthRuntime"]=r.name
      return r
    waiter=asyncio.create_task(fifth());tasks.append(waiter)
    await until(lambda:principals[4].user_id+"-"+users[4]["space"] in manager.pending,5)
    for _ in range(3):
     await asyncio.sleep(5);await manager.reap_once()
    check("fifth waits; four running tasks survive idle threshold",not waiter.done() and len(manager.items)==4 and not any(r.stopped for r in runtimes))
    await snapshot("fourStreaming",manager)
    result["streamingReadSeconds"]=await asyncio.gather(*(measured_read(n) for n in range(4)))
    # Release A only, preserving the other three active streams during E's startup.
    release[0].set()
    async with asyncio.timeout(30):
     while any((await activity(runtimes[0])).values()):await asyncio.sleep(.25)
    a_history=await history(runtimes[0],sessions[0])
    check("completed A output visible through native history", "CAP4_0_COMPLETE" in a_history)
    await manager.reap_once();await asyncio.sleep(2.2);await manager.reap_once()
    await until(lambda:len(manager.items)==4 and any(not r.ready for r in manager.items.values()),5)
    at=time.monotonic();warm_read=asyncio.create_task(measured_read(1));tasks.append(warm_read)
    result["directReadDuringColdStartSeconds"]=round(await measured_read(2,False),3)
    await asyncio.sleep(3)
    result["admissionLockBlocksWarmRequest"]=not warm_read.done()
    print("Cold start lock blocks existing user's pool request: "+str(not warm_read.done()),flush=True)
    await asyncio.wait_for(waiter,150)
    result["warmReadDuringColdStartSeconds"]=round(await warm_read,3)
    check("cold startup no longer blocks existing user request",not result["admissionLockBlocksWarmRequest"] and result["warmReadDuringColdStartSeconds"]<3)
    result["fifthAdmissionAfterSlotReleaseSeconds"]=round(time.monotonic()-at,1)
    check("fifth starts only after completed A recycled",runtimes[0].stopped and len(manager.items)==4 and manager.peak==4)
    states=await asyncio.gather(*(activity(r) for r in runtimes[1:]))
    check("other three tasks remain running during replacement",all(s["running"] for s in states))
    for event in release:event.set()
    async with asyncio.timeout(45):
     while any(any(s.values()) for s in await asyncio.gather(*(activity(r) for r in runtimes[1:]))):await asyncio.sleep(.5)
    check("all four model/tool tasks completed with correct identity",sorted(tool_calls)==list(range(4)))
    for n in range(1,4):
     check(f"user {n} completed output visible through native history",
           f"CAP4_{n}_COMPLETE" in await history(runtimes[n],sessions[n]))
    await snapshot("replacementReady",manager)
    inspect=json.loads(await docker("inspect",*(r.name for r in manager.items.values())))
    check("no test container reports OOM",all(not x["State"]["OOMKilled"] for x in inspect))
    result["capacityPassed"]=True
   finally:
    for event in release:event.set()
    for t in tasks:
     if not t.done():t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await manager.close()
    if watcher:
     watcher.cancel()
     with suppress(asyncio.CancelledError):await watcher
     watcher=None
   check("temporary containers removed",not bool(await docker("ps","-aq","--filter","name=department-id-ai-"+manager.namespace+"-")))
  check("temporary directory removed",not Path(folder).exists())
  result["passed"]=True
 finally:
  for event in release:event.set()
  if watcher:
   watcher.cancel()
   with suppress(asyncio.CancelledError):await watcher
  if server:
   server.should_exit=True
   if server_task:await server_task
  with psycopg.connect(creds["adminDsn"]) as conn:
   for u in users:
    conn.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
    conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(u["id"],))
    conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["id"],))
   conn.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  db.close();result["testAccountsDisabled"]=True
  if result["hostSamples"]:
   result["minAvailableMiB"]=min(s["availableMiB"] for s in result["hostSamples"])
   result["peakSampledHostCpuPercent"]=max(s.get("hostCpuPercent",0) for s in result["hostSamples"])
   result["healthFailures"]=[s for s in result["hostSamples"] if any(s["health"][str(p)]["status"]!=e for p,_,e in endpoints)]
  RESULT_PATH.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print("Four-instance experiment complete; online services unchanged",flush=True)
if __name__=="__main__":asyncio.run(main())

