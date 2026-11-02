"""Real private Harness directory operations via authenticated gateway; synthetic DB only."""
import json,os,time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from contextlib import ExitStack
import psycopg
from psycopg.types.json import Jsonb
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from app.features.identity.service import HASHER
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
config=json.loads((STATE/"credentials.json").read_text())
assert "@127.0.0.1:15433/identity_test" in config["adminDsn"]
os.environ.update({k:v for k,v in dotenv_values(STATE/"app.env").items() if v is not None})
os.environ["DEPARTMENT_AI_ORIGINS"]=json.dumps({"zkxk":"http://127.0.0.1:3182","senyuan":"http://127.0.0.1:3183"})
os.environ["DEPARTMENT_AI_MODELS"]='["department-test"]'
from app.main import app
from app.features.assistant.gateway import app as gateway
ORIGIN="http://127.0.0.1:3181";AI="http://127.0.0.1:3182";WORK="/home/assistant/workspace"
checks=[];users=[];gid="dir-"+uuid4().hex[:8]
def check(name,ok=True):
 assert ok,name
 checks.append(name);print("PASS",name,flush=True)
def dept(c,method,path,body=None,space="zkxk"):
 r=c.request(method,path,json=body,headers={"Origin":ORIGIN,"X-CSRF-Token":getattr(c,"csrf",""),"X-Department-Space":space})
 assert r.status_code==200,(path,r.status_code,r.text[:200])
 return r.json()
def rpc(c,name,args,status=200):
 r=c.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),"method":name,"payload":{"args":args}},headers={"Origin":str(c.base_url).rstrip("/")})
 assert r.status_code==status,(name,r.status_code,r.text[:200])
 if status!=200:return
 result=r.json()["result"];assert result["ok"],result
 return result.get("value")
def enter(c,ai,space="zkxk"):
 ticket=dept(c,"POST","/api/assistant/entry",space=space)["ticket"]
 r=ai.post("/bootstrap",data={"ticket":ticket},headers={"Origin":ORIGIN})
 assert r.status_code==303,(r.status_code,r.text[:100])
 for attempt in range(150):
  r=ai.post("/ready",headers={"Origin":str(ai.base_url).rstrip("/")})
  if r.status_code==200:return
  if r.status_code!=202:break
  time.sleep(1)
 raise AssertionError(("ready",r.status_code,r.text[:200]))
try:
 with psycopg.connect(config["adminDsn"]) as conn:
  conn.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
  for n in range(2):
   u={"id":str(uuid4()),"username":gid+"-"+str(n),"password":uuid4().hex+"X1"}
   conn.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'目录隔离临时测试',%s,'zkxk',false)",(u["id"],u["username"],HASHER.hash(u["password"])))
   for space in ("zkxk","senyuan"):
    conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(u["id"],space,gid))
   users.append(u)
 with TemporaryDirectory(prefix="id-dir-") as folder,ExitStack() as stack:
  os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
  portal=stack.enter_context(TestClient(app,base_url=ORIGIN))
  ai=stack.enter_context(TestClient(gateway,base_url=AI,follow_redirects=False))
  # These additional clients share the one lifespan, never start/close another manager.
  second=TestClient(app,base_url=ORIGIN);stack.callback(second.close)
  bi=TestClient(gateway,base_url=AI,follow_redirects=False);bi.portal=ai.portal;stack.callback(bi.close)
  ci=TestClient(gateway,base_url="http://127.0.0.1:3183",follow_redirects=False);ci.portal=ai.portal;stack.callback(ci.close)
  for c,u in ((portal,users[0]),(second,users[1])):
   c.csrf=dept(c,"POST","/api/auth/login",{"username":u["username"],"password":u["password"]})["csrfToken"]
  enter(portal,ai)
  listing=rpc(ai,"directoryPicker/list",{})
  check("personal root listing",listing["path"]==WORK)
  path=rpc(ai,"directoryPicker/createDirectory",{"path":WORK,"name":"liao 验收"})
  check("create real Chinese/spaced directory",path==WORK+"/liao 验收")
  nested=rpc(ai,"directoryPicker/createDirectory",{"path":path,"name":"子目录"})
  listing=rpc(ai,"directoryPicker/list",{"path":path})
  check("browse newly created directory and nested child",listing["path"]==path and "子目录" in json.dumps(listing,ensure_ascii=False))
  workspace=rpc(ai,"workspace/create",{"request":{"path":nested}})
  # Native UI uses workspaceId; also cover explicitly supplied cwd.
  wid=workspace["workspace"]["workspaceId"]
  session=rpc(ai,"session/create",{"request":{"workspaceId":wid}})
  explicit=rpc(ai,"session/create",{"request":{"cwd":nested}})
  check("open new directory as workspace and create sessions",bool(session["sessionId"] and explicit["sessionId"]))
  duplicate=ai.post("/api/directoryPicker/createDirectory",json={"type":"client-request","rpcId":str(uuid4()),"method":"directoryPicker/createDirectory","payload":{"args":{"path":WORK,"name":"liao 验收"}}},headers={"Origin":AI})
  check("duplicate folder returns structured failure without overwrite",duplicate.status_code==200 and not duplicate.json()["result"]["ok"])
  for bad in ("/etc","/home/assistant/dsh",WORK+"/../dsh"):
   rpc(ai,"directoryPicker/createDirectory",{"path":bad,"name":"bad"},403)
   rpc(ai,"directoryPicker/list",{"path":bad},403)
   rpc(ai,"workspace/create",{"request":{"path":bad}},403)
   rpc(ai,"session/create",{"request":{"cwd":bad}},403)
  for name in ("../escape","a/b","a\\b","..",""):
   rpc(ai,"directoryPicker/createDirectory",{"path":WORK,"name":name},403)
  check("external paths, traversal and invalid names denied by live gateway")
  base=Path(folder)/(users[0]["id"]+"-zkxk")/"home/workspace"
  (base/"escape").symlink_to("/home/assistant/dsh",target_is_directory=True)
  for method,args in (
    ("directoryPicker/createDirectory",{"path":WORK+"/escape","name":"bad"}),
    ("directoryPicker/list",{"path":WORK+"/escape"}),
    ("workspace/create",{"request":{"path":WORK+"/escape"}}),
    ("session/create",{"request":{"cwd":WORK+"/escape"}})):
   rpc(ai,method,args,403)
  check("symbolic-link directory operations denied by live gateway")
  enter(second,bi)
  listing=rpc(bi,"directoryPicker/list",{})
  check("second user cannot see first user folder","liao 验收" not in json.dumps(listing,ensure_ascii=False))
  own=rpc(bi,"directoryPicker/createDirectory",{"path":WORK,"name":"liao 验收"})
  check("same directory name belongs to a different user storage",(Path(folder)/(users[1]["id"]+"-zkxk")/"home/workspace/liao 验收").is_dir() and own==path)
  dept(second,"POST","/api/auth/logout")
  time.sleep(3)
  enter(portal,ci,"senyuan")
  listing=rpc(ci,"directoryPicker/list",{})
  check("same user in another company cannot see first company folder","liao 验收" not in json.dumps(listing,ensure_ascii=False))
  dept(portal,"POST","/api/auth/logout")
finally:
 with psycopg.connect(config["adminDsn"]) as conn:
  for u in users:
   conn.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["id"],))
   conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(u["id"],))
   conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["id"],))
  conn.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
(STATE/"assistant-directory-live-results.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print("Real Harness directory workflow complete; temporary runtimes stopped, test accounts disabled",flush=True)

