"""Opt-in persistence verification for this task's synthetic acceptance account."""
import asyncio,json,sys
from pathlib import Path
from uuid import uuid4
import httpx,psycopg,hashlib
from psycopg.types.json import Jsonb
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
PORTAL="http://127.0.0.1:3181";AI="http://127.0.0.1:3182"
async def main():
 phase=sys.argv[1];assert phase in ("before","after")
 f=json.loads((STATE/"hardening-live.private.json").read_text());u=f["users"][0]
 assert u["username"].startswith("hardening-")
 db=json.loads((STATE/"acceptance-db.json").read_text())["adminDsn"]
 assert db.endswith("/identity_acceptance_20261028")
 group="persist-"+u["id"];result=False
 if phase=="before":
  with psycopg.connect(db) as c:
   c.execute("UPDATE users SET active=true WHERE id=%s",(u["id"],))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(group,group,Jsonb(["assistant.use","skills.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(u["id"],group))
 try:
  async with httpx.AsyncClient(base_url=PORTAL,timeout=40) as portal,httpx.AsyncClient(base_url=AI,timeout=40) as ai:
   r=await portal.post("/api/auth/login",headers={"Origin":PORTAL},json={"username":u["username"],"password":u["password"]})
   assert r.status_code==200,r.status_code
   r=await portal.post("/api/assistant/entry",headers={"Origin":PORTAL,"X-CSRF-Token":r.json()["csrfToken"],"X-Department-Space":"zkxk"})
   assert r.status_code==200
   r=await ai.post("/bootstrap",headers={"Origin":PORTAL},data={"ticket":r.json()["ticket"]});assert r.status_code==303
   for _ in range(180):
    r=await ai.post("/ready",headers={"Origin":AI})
    if r.status_code==200:break
    assert r.status_code==202,r.text
    await asyncio.sleep(1)
   else:raise AssertionError("startup timed out")
   async def rpc(method,args):
    r=await ai.post("/api/"+method,headers={"Origin":AI},json={"type":"client-request","rpcId":str(uuid4()),"method":method,"payload":{"args":args}})
    assert r.status_code==200,r.text
    v=r.json()["result"];assert v["ok"],v;return v.get("value")
   rows=await rpc("session/list",{"_request":{}})
   assert f["sessionId"] in json.dumps(rows)
   assert not any(x.get("running",True) for x in rows["items"])
   r=await ai.get("/api/file",params={"path":f["downloadPath"],"download":"1"})
   assert r.status_code==200 and len(r.content)>100
   settings=Path("/root/liao/identity-ai-acceptance")/(u["id"]+"-zkxk")/"home/dsh/settings.yaml"
   if phase=="before":
    await rpc("settings/mutate",{"ns":"ui-theme","ops":[{"op":"set","path":["fontSize"],"value":17}]})
   digest=hashlib.sha256(settings.read_bytes()).hexdigest()
   expected=STATE/"hardening-settings-digest.txt"
   if phase=="before":expected.write_text(digest)
   else:assert digest==expected.read_text()
   result=True
   print("PASS",phase,"native session history, generated download and personal font setting",flush=True)
   if phase=="after":
    (STATE/"hardening-persistence-results.json").write_text(json.dumps({"passed":True,"nativeHistory":True,"generatedDownload":True,"personalSettings":True}))
 finally:
  if phase=="after" or not result:
   with psycopg.connect(db) as c:
    c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
    c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(u["id"],))
    c.execute("DELETE FROM user_space_grants WHERE group_id=%s",(group,))
    c.execute("DELETE FROM permission_groups WHERE id=%s",(group,))
if __name__=="__main__":asyncio.run(main())
