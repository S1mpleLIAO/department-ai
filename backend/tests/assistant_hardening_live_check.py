"""Opt-in deployed acceptance regression, synthetic users/material only."""
import asyncio,base64,json,os,subprocess,time
from pathlib import Path
from uuid import uuid4
import httpx,psycopg
from psycopg.types.json import Jsonb
from app.features.identity.service import HASHER
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
AI="http://127.0.0.1:3182";PORTAL="http://127.0.0.1:3181"
R=Path("/root/liao/identity-ai-acceptance");WORK="/home/assistant/workspace"
async def main():
 db=json.loads((STATE/"acceptance-db.json").read_text())["adminDsn"]
 assert db.endswith("/identity_acceptance_20261028")
 gid="hardening-"+uuid4().hex[:8];users=[];checks=[];clients=[]
 def passed(s):checks.append(s);print("PASS",s,flush=True)
 try:
  with psycopg.connect(db) as c:
   skill=c.execute("SELECT data FROM skill_publications WHERE id='travel-reimbursement-cn' AND enabled").fetchone()[0]
   job=json.loads(base64.b64decode(next(x["contentBase64"] for x in skill["resources"] if x["path"]=="references/examples/input.example.json")))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use","skills.use"])))
   for n in range(2):
    u={"id":str(uuid4()),"username":gid+"-"+str(n),"password":uuid4().hex+"X1"};users.append(u)
    c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'宿主收敛合成验收',%s,'zkxk',false)",(u["id"],u["username"],HASHER.hash(u["password"])))
    for space in ("zkxk","senyuan"):c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(u["id"],space,gid))
  async def enter(u,space="zkxk"):
   portal=httpx.AsyncClient(base_url=PORTAL,timeout=30);clients.append(portal)
   r=await portal.post("/api/auth/login",headers={"Origin":PORTAL},json={"username":u["username"],"password":u["password"]})
   assert r.status_code==200,r.text;csrf=r.json()["csrfToken"]
   r=await portal.post("/api/assistant/entry",headers={"Origin":PORTAL,"X-CSRF-Token":csrf,"X-Department-Space":space})
   assert r.status_code==200,r.text
   ai=httpx.AsyncClient(base_url=AI if space=="zkxk" else "http://127.0.0.1:3183",timeout=40,follow_redirects=False)
   clients.append(ai)
   r=await ai.post("/bootstrap",headers={"Origin":PORTAL},data={"ticket":r.json()["ticket"]});assert r.status_code==303,r.text
   for _ in range(180):
    r=await ai.post("/ready",headers={"Origin":str(ai.base_url).rstrip("/")})
    if r.status_code==200:break
    assert r.status_code==202,r.text
    await asyncio.sleep(1)
   else:raise AssertionError("runtime startup timed out")
   return ai
  async def rpc(ai,name,args,expected=200):
   r=await ai.post("/api/"+name,headers={"Origin":str(ai.base_url).rstrip("/")},json={"type":"client-request","rpcId":str(uuid4()),"method":name,"payload":{"args":args}})
   assert r.status_code==expected,(name,r.status_code,r.text[:300])
   if expected!=200:return
   v=r.json()["result"];assert v["ok"],v;return v.get("value")
  (STATE/"hardening-live-current.private.json").write_text(json.dumps({"users":users,"group":gid}))
  (STATE/"hardening-live-current.private.json").chmod(0o600)
  ai=await enter(users[0]);passed("non-root deployed gateway starts native Harness through fixed broker")
  sid=(await rpc(ai,"session/create",{"request":{"cwd":WORK}}))["sessionId"]
  receipt=STATE/"hardening-test-material.docx"
  code="from docx import Document;import sys;d=Document();d.add_paragraph('报销合成验收材料');d.add_paragraph('重庆出差2026-08-11至2026-08-12。机票630.00和1290.00，高铁38.00，住宿234.36。北京怀柔2026-08-14当日出差，无票据。');d.save(sys.argv[1])"
  subprocess.run(["/usr/bin/python3","-c",code,str(receipt)],check=True)
  r=await ai.post("/api/session/uploadFileBinary",params={"sessionId":sid,"name":receipt.name},
                  headers={"Origin":AI,"Content-Type":"application/octet-stream"},content=receipt.read_bytes())
  assert r.status_code==200,r.text;upload=r.json();assert upload["ok"],upload
  profile={"姓名":"宿主验收测试员","部门":"技术部","职务":"工程师","银行卡":"0000000000000000","开户行":"测试银行"}
  prompt="这是已确认的合成报销验收。请依次读取部门规则、已发布报销技能、上传附件正文，然后调用 department_reimbursement_generate 一次，返回下载链接。所有信息均已确认，不需要再次询问。任务数据："+json.dumps(job,ensure_ascii=False)+"。个人资料："+json.dumps(profile,ensure_ascii=False)
  await rpc(ai,"session/prompt",{"request":{"sessionId":sid,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":prompt},{"type":"file","receiptId":upload["value"]["receiptId"]}]}})
  home=R/(users[0]["id"]+"-zkxk")/"home/workspace"
  for attempt in range(600):
   reports=list(home.glob("reimbursements/*/generation_report.json"))
   if reports:break
   if attempt>30 and attempt%10==0:
    rows=await rpc(ai,"session/list",{"_request":{}})
    own=next((item for item in rows["items"] if item.get("id",item.get("sessionId"))==sid),None)
    if own is not None and own.get("running") is False:
     raise AssertionError("Model stopped without reimbursement output; inspect isolated service log")
   await asyncio.sleep(1)
  else:raise AssertionError("real model reimbursement output timed out")
  folder=reports[0].parent;report=json.loads(reports[0].read_text())
  assert str(report["total"])=="2702.36",report["total"]
  docs=list(folder.rglob("*.docx"));assert len(docs)==5
  paths=[WORK+"/"+p.relative_to(home).as_posix() for p in docs+[reports[0]]]
  for path in paths:
   r=await ai.get("/api/file",params={"path":path,"download":"1"});assert r.status_code==200,(path,r.status_code)
   assert len(r.content)>10 and "attachment" in r.headers["content-disposition"]
  passed("real model native attachment parsing, approved reimbursement execution and six authenticated downloads")
  bi,ci=await asyncio.gather(enter(users[1]),enter(users[0],"senyuan"))
  for other in (bi,ci):
   r=await other.get("/api/file",params={"path":paths[0],"download":"1"});assert r.status_code in (403,404),r.text
  passed("other user and other company cannot download the generated file")
  # Sparse synthetic quota marker: no pre-existing data touched, no large file contents written.
  quota=home/".synthetic-quota-test"
  with quota.open("wb") as f:f.truncate(513*1024*1024)
  try:
   await rpc(ai,"directoryPicker/createDirectory",{"path":WORK,"name":"over-quota"},507)
   r=await ai.get("/api/file",params={"path":paths[0],"download":"1"});assert r.status_code==200
   await rpc(bi,"directoryPicker/createDirectory",{"path":WORK,"name":"other-user-ok"})
  finally:quota.unlink()
  passed("over-quota writes rejected; existing downloads preserved; another user unaffected")
  # Keep a private fixture for post-restart persistence verification before disabling users.
  for _ in range(90):
   rows=await rpc(ai,"session/list",{"_request":{}})
   if not any(item.get("running",True) for item in rows["items"]):break
   await asyncio.sleep(1)
  else:raise AssertionError("Synthetic model task is still running; do not restart service")
  saved={"users":users,"group":gid,"sessionId":sid,"downloadPath":paths[0],"files":len(docs)+1,"checks":checks}
  (STATE/"hardening-live.private.json").write_text(json.dumps(saved));(STATE/"hardening-live.private.json").chmod(0o600)
  (STATE/"hardening-live-results.json").write_text(json.dumps({"passed":True,"checks":checks,"total":str(report["total"])},ensure_ascii=False,indent=2))
 finally:
  for client in clients:await client.aclose()
  with psycopg.connect(db) as c:
   for u in users:
    c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
    c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(u["id"],))
   c.execute("DELETE FROM user_space_grants WHERE group_id=%s",(gid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
if __name__=="__main__":asyncio.run(main())
