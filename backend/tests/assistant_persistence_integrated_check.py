"""Real idle recycle/restart persistence with production Manager; synthetic identity."""
import asyncio,json,os,time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
from assistant_pool_probe import creds,STATE,rpc
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,docker
checks=[]
def check(name,value=True):
 assert value,name
 checks.append(name);print("PASS "+name,flush=True)
async def main():
 db=create_pool(creds["appDsn"]);db.open(wait=True)
 uid=str(uuid4());gid="persist-"+uid[:8];password=uuid4().hex+"X1"
 result={"passed":False,"checks":checks}
 try:
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'回收持久化临时验证',%s,'zkxk',false)",(uid,gid,HASHER.hash(password)))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
  token,_,_=login(db,gid,password,"persistence-check","persistence-check");p=authenticate(db,token)[0]
  with TemporaryDirectory(prefix="id-keep-") as folder:
   os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
   m=Manager(db,["department-test"]);m.limits=replace(m.limits,capacity=1,idle_seconds=1)
   try:
    async with m.lease(p,"zkxk") as r:
     sid=(await rpc(r,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
     r.session_epoch(sid,create=True)
     await rpc(r,"session/rename",{"request":{"sessionId":sid,"title":"PERSISTENT_SESSION_CHECK"}})
     await rpc(r,"settings/update",{"ns":"locale","patch":{"preference":"zh"}})
     (r.root/"home/workspace/keep.txt").write_text("synthetic persistent file")
    r.last=r.idle_since=time.monotonic()-10
    await m.reap_once()
    check("native idle runtime reclaimed",r.stopped and not m.items)
    check("recycle retains persistent workspace",(r.root/"home/workspace/keep.txt").read_text()=="synthetic persistent file")
    async with m.lease(p,"zkxk") as restored:
     check("restarted runtime restores session",sid in json.dumps(await rpc(restored,"session/list",{"_request":{}})))
     restored.session_epoch(sid)
     desc=await rpc(restored,"settings/describe",{})
     check("personal locale retained",next(x for x in desc["namespaces"] if x["ns"]=="locale")["value"]["preference"]=="zh")
     check("authorization binding retained")
   finally:await m.close()
   check("owned test containers removed",not await docker("ps","-aq","--filter","name=department-id-ai-"+m.namespace+"-"))
  check("synthetic state directory removed",not Path(folder).exists())
  result["passed"]=True
 finally:
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(uid,))
   c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  db.close();(STATE/"assistant-persistence-integrated-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":asyncio.run(main())

