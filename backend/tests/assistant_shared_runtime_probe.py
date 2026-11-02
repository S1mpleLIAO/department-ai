"""Bounded native sharing feasibility probe; never routes real users to shared state.
Two synthetic principals, two independent clients, one disposable Harness runtime.
The bridge identity observation is instrumented (no real model/tool invocation).
"""
import asyncio,json,os,time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
import httpx,psycopg,websockets
from psycopg.types.json import Jsonb
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
creds=json.loads((STATE/"credentials.json").read_text())
assert "@127.0.0.1:15433/identity_test" in creds["appDsn"]
assert "@127.0.0.1:15433/identity_test" in creds["adminDsn"]
os.environ.update({k:v for k,v in dotenv_values(STATE/"app.env").items() if v is not None})
os.environ["DEPARTMENT_AI_RUNTIME_MODE"]="isolated"
os.environ.pop("DEPARTMENT_AI_MODEL_URL",None);os.environ.pop("DEPARTMENT_AI_MODEL_KEY",None)
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,docker
from app.features.assistant.gateway import bridge_app

results={"scope":"native shared runtime baseline, NOT a deployed multiuser gateway",
         "realModelCalled":False,"observations":{}}
def observe(name,value):
 results["observations"][name]=value
 print(name+": "+json.dumps(value,ensure_ascii=False),flush=True)
async def rpc(c,name,args):
 r=await c.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),"method":name,"payload":{"args":args}})
 r.raise_for_status();value=r.json()["result"]
 assert value["ok"],(name,value)
 return value.get("value")
async def main():
 users=[];gid="share-"+uuid4().hex[:8]
 pool=create_pool(creds["appDsn"]);pool.open(wait=True)
 try:
  with psycopg.connect(creds["adminDsn"]) as conn:
   conn.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   for company in ("zkxk","senyuan"):
    u={"id":str(uuid4()),"username":gid+"-"+company,"password":uuid4().hex+"X1","company":company}
    conn.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'共享探针临时用户',%s,%s,false)",(u["id"],u["username"],HASHER.hash(u["password"]),company))
    conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(u["id"],company,gid))
    users.append(u)
  principals=[]
  for u in users:
   token,_,_=login(pool,u["username"],u["password"],"probe","probe")
   principals.append(authenticate(pool,token)[0])
  with TemporaryDirectory(prefix="id-share-") as folder:
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
   manager=Manager(pool,["department-test"])
   runtime=None
   try:
    started=time.monotonic()
    runtime=await manager.get(principals[0],"zkxk")
    observe("startupSeconds",round(time.monotonic()-started,1))
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(runtime.socket)),base_url="http://runtime") as a,httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(runtime.socket)),base_url="http://runtime") as b:
     # These labels deliberately do not claim a production auth implementation.
     sessions=[]
     for c,label in ((a,"A"),(b,"B")):
      s=await rpc(c,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}})
      await rpc(c,"session/rename",{"request":{"sessionId":s["sessionId"],"title":"shared-probe-"+label}})
      sessions.append(s["sessionId"])
     rows=await rpc(b,"session/list",{"_request":{}})
     observe("BListsASession",sessions[0] in json.dumps(rows))
     await rpc(b,"session/rename",{"request":{"sessionId":sessions[0],"title":"B-edited-A"}})
     observe("BCanRenameASession","B-edited-A" in json.dumps(await rpc(a,"session/list",{"_request":{}})))
     await rpc(a,"settings/update",{"ns":"locale","patch":{"preference":"zh"}})
     before=await rpc(b,"settings/describe",{})
     await rpc(b,"settings/update",{"ns":"locale","patch":{"preference":"en"}})
     after=await rpc(a,"settings/describe",{})
     def locale(d):return next(n["value"] for n in d["namespaces"] if n["ns"]=="locale")
     observe("localeReadByBAfterAWrite",locale(before))
     observe("localeReadByAAfterBWrite",locale(after))
     async with websockets.unix_connect(str(runtime.socket),uri="ws://runtime/api/remote.mux") as ws:
      await ws.send(json.dumps({"type":"open","streamId":"foreign","endpoint":"session/follow","payload":{"args":{"request":{"address":{"kind":"session","sessionId":sessions[0]}}}}}))
      first=json.loads(await asyncio.wait_for(ws.recv(),15))
      observe("BSubscribesASession",{"frameType":first.get("type"),"containsASessionId":sessions[0] in json.dumps(first)})
     async with websockets.unix_connect(str(runtime.socket),uri="ws://runtime/api/remote.mux") as ws:
      await ws.send(json.dumps({"type":"open","streamId":"events","endpoint":"$events","payload":{"args":{}}}))
      await asyncio.sleep(.3)
      await rpc(a,"session/rename",{"request":{"sessionId":sessions[0],"title":"A-live-event-marker"}})
      seen=[];leaked=False
      try:
       async with asyncio.timeout(5):
        while True:
         msg=json.loads(await ws.recv());seen.append(msg.get("type"))
         if "A-live-event-marker" in json.dumps(msg) or sessions[0] in json.dumps(msg):
          leaked=True;break
      except TimeoutError:pass
      observe("BReceivesAEvent",{"observed":leaked,"frameTypes":seen[:8],"timeoutSeconds":5})
     (runtime.root/"home/workspace/A-private.txt").write_text("A synthetic private file")
     r=await b.get("/api/file",params={"path":"/home/assistant/workspace/A-private.txt"})
     observe("BCanDownloadAFile",r.status_code==200 and r.text=="A synthetic private file")
    # Use actual bridge authorization logic but capture dispatch instead of accessing data.
    def captured_call(pool,p,space,name,args):
     return {"principalIsA":p.user_id==principals[0].user_id,"space":space}
    with patch("app.features.assistant.gateway.call",side_effect=captured_call):
     async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge_app(runtime)),base_url="http://bridge") as c:
      x=await c.post("/tool/department_processes",json={})
      observe("sharedBridgeIdentityInstrumented",x.json())
    stats=json.loads(await docker("stats","--no-stream","--format","{{json .}}",runtime.name))
    observe("twoEmptySessionsResourceSnapshot",{k:stats[k] for k in ("MemUsage","CPUPerc","PIDs")})
    results["runtimeName"]=runtime.name
   finally:
    await manager.close()
   if runtime is not None:
    observe("temporaryContainerRemoved",not bool(await docker("ps","-aq","--filter","name=^/"+runtime.name+"$")))
 finally:
  with psycopg.connect(creds["adminDsn"]) as conn:
   for u in users:
    conn.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
    conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(u["id"],))
    conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["id"],))
   conn.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  pool.close()
  results["testAccountsDisabled"]=True
  (STATE/"assistant-shared-runtime-probe-results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print("Probe finished; temporary resources removed, no deployment changed",flush=True)
if __name__=="__main__":asyncio.run(main())

