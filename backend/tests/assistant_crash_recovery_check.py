"""Crash only an owned synthetic worker; verify native orphan recovery and persistence."""
import asyncio,json,os,sys,time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import httpx,psycopg
from psycopg.types.json import Jsonb
from assistant_pool_probe import creds,STATE,rpc,until
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,docker
from app.features.assistant.config import pool_limits

async def worker(path):
 data=json.loads(Path(path).read_text())
 os.environ["DEPARTMENT_AI_STATE_DIR"]=data["root"]
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 token,_,_=login(db,data["username"],data["password"],"crash-worker","crash-worker")
 p=authenticate(db,token)[0];m=Manager(db,["department-test"])
 try:
  await m.recover()
  async with m.lease(p,"zkxk") as r:
   sid=(await rpc(r,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
   r.session_epoch(sid,create=True)
   await rpc(r,"session/rename",{"request":{"sessionId":sid,"title":"CRASH_RECOVERY_SESSION"}})
   await rpc(r,"settings/update",{"ns":"locale","patch":{"preference":"zh"}})
   (r.root/"home/workspace/marker.txt").write_text("CRASH_RETAINED")
  print(json.dumps({"session":sid,"name":r.name}),flush=True)
  await asyncio.Event().wait()
 finally:await m.close();db.close()

checks=[]
def check(name,ok=True):
 assert ok,name
 checks.append(name);print("PASS "+name,flush=True)

async def main():
 result={"passed":False,"checks":checks}
 uid=str(uuid4());gid="crash-"+uid[:8];pw=uuid4().hex+"X1"
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 child=None;m=None;name=None
 endpoints=((3080,"/",401),(3081,"/health",200),(3181,"/health",200))
 async def health():
  async with httpx.AsyncClient(timeout=4) as client:
   assert all([ (await client.get(f"http://127.0.0.1:{p}{path}")).status_code==code for p,path,code in endpoints])
 try:
  await health()
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'异常恢复合成测试',%s,'zkxk',false)",(uid,gid,HASHER.hash(pw)))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
  with TemporaryDirectory(prefix="id-crash-") as folder:
   root=Path(folder);fixture=root/"fixture.json"
   fixture.write_text(json.dumps({"username":gid,"password":pw,"root":folder}));fixture.chmod(0o600)
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
   with (root/"worker.log").open("wb") as log:
    child=await asyncio.create_subprocess_exec(sys.executable,__file__,"--worker",str(fixture),stdout=asyncio.subprocess.PIPE,stderr=log)
    line=await asyncio.wait_for(child.stdout.readline(),150)
    assert line,"worker failed before ready; inspect its private log"
    record=json.loads(line);name=record["name"]
    try:Manager(db,["department-test"])
    except RuntimeError:check("second supervisor rejected while worker owns lock")
    else:raise AssertionError("duplicate supervisor allowed")
    # The test owns this exact Process handle, not a PID selected from production.
    child.kill();await child.wait()
    check("SIGKILL leaves real owned container",await docker("inspect","--format","{{.State.Running}}",name)=="true")
    m=Manager(db,["department-test"])
    try:
     async def unknown(_):raise TimeoutError("synthetic probe unavailable")
     with patch("app.features.assistant.pool.activity",side_effect=unknown):
      try:await m.recover()
      except RuntimeError:check("unknown orphan state blocks startup without deleting container",await docker("inspect","--format","{{.State.Running}}",name)=="true")
      else:raise AssertionError("unknown orphan deleted")
     async def busy(_):return {"running":True}
     with patch("app.features.assistant.pool.activity",side_effect=busy):
      try:await m.recover()
      except RuntimeError:check("busy orphan blocks startup without deleting container",await docker("inspect","--format","{{.State.Running}}",name)=="true")
      else:raise AssertionError("busy orphan deleted")
     check("native idle orphan safely reconciled",await m.recover()==1)
     check("reconciliation preserves workspace",(root/(uid+"-zkxk")/"home/workspace/marker.txt").read_text()=="CRASH_RETAINED")
     token,_,_=login(db,gid,pw,"crash-recovery","crash-recovery")
     p=authenticate(db,token)[0]
     async with m.lease(p,"zkxk") as r:
      check("fresh runtime restores crashed worker session",record["session"] in json.dumps(await rpc(r,"session/list",{"_request":{}})))
      r.session_epoch(record["session"])
      desc=await rpc(r,"settings/describe",{})
      check("personal settings and authorization epoch retained",next(x for x in desc["namespaces"] if x["ns"]=="locale")["value"]["preference"]=="zh")
      response=await r.client.get("/")
      check("native automatic authentication recovered",response.status_code==200 and "authentication required" not in response.text)
    finally:await m.close();m=None
   check("test containers cleaned",not await docker("ps","-aq","--filter","name=^/"+name+"$"))
  check("synthetic crash directory cleaned",not root.exists())
  for key,value in (("DEPARTMENT_AI_MAX_INSTANCES","0"),("DEPARTMENT_AI_IDLE_SECONDS","bad"),("DEPARTMENT_AI_MIN_AVAILABLE_MIB","10")):
   with patch.dict(os.environ,{key:value}):
    try:pool_limits()
    except RuntimeError:pass
    else:raise AssertionError("invalid limit accepted: "+key)
  check("incomplete or invalid limits reject startup")
  await health();check("production and acceptance health unchanged")
  result["passed"]=True
 finally:
  if child and child.returncode is None:child.kill();await child.wait()
  if m:await m.close()
  if name:
   # This exact random name was returned by our own worker; no broad Docker cleanup.
   remaining=await docker("ps","-aq","--filter","name=^/"+name+"$")
   if remaining:await docker("rm","-f",name)
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(uid,))
   c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  db.close();result["testAccountDisabled"]=True
  (STATE/"assistant-crash-recovery-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":
 asyncio.run(worker(sys.argv[2]) if len(sys.argv)>1 and sys.argv[1]=="--worker" else main())

