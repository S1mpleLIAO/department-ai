"""Release startup/proxy checks on ephemeral ports and disposable identity only."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from http.cookies import SimpleCookie
import httpx,psycopg
from psycopg.types.json import Jsonb
from app.features.identity.service import HASHER
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
creds=json.loads((STATE/"credentials.json").read_text())
assert "@127.0.0.1:15433/identity_test" in creds["adminDsn"]
checks=[]
def check(name,ok=True):
 assert ok,name
 checks.append(name);print("PASS "+name,flush=True)
def free_port():
 with socket.socket() as sock:
  sock.bind(("127.0.0.1",0));return sock.getsockname()[1]
def cookies(response):
 parsed=SimpleCookie();parsed.load(response.headers["set-cookie"])
 return "; ".join(k+"="+v.value for k,v in parsed.items())
def main():
 uid=str(uuid4());gid="release-"+uid[:8];pw=uuid4().hex+"X1";process=None
 result={"passed":False,"checks":checks}
 try:
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'发布预检合成账号',%s,'zkxk',false)",(uid,gid,HASHER.hash(pw)))
   c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(gid,gid,Jsonb(["assistant.use"])))
   c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
  with TemporaryDirectory(prefix=".id-rel-",dir="/root") as folder:
   root=Path(folder);app_port=free_port();ai_port=free_port()
   assert app_port!=ai_port and not {app_port,ai_port}&{3080,3081,3181,3182,3183,3184}
   envfile=root/"release.env"
   config={"DEPARTMENT_AUTH_ORIGIN":"https://department.example.test","DEPARTMENT_PYTHON_PORT":str(app_port),
    "DEPARTMENT_AI_ORIGINS":json.dumps({"zkxk":"https://ai-zkxk.example.test","senyuan":"https://ai-senyuan.example.test"}),
    "DEPARTMENT_AI_RUNTIME_MODE":"production","DEPARTMENT_AI_STATE_DIR":folder,
    "DEPARTMENT_AI_GATEWAY_PORT":str(ai_port),"DEPARTMENT_AI_MAX_INSTANCES":"4","DEPARTMENT_AI_MODELS":'["department-test"]',
    "DEPARTMENT_AI_MODEL_URL":"https://model.invalid/v1","DEPARTMENT_AI_MODEL_KEY":"synthetic-not-called"}
   base=(STATE/"app.env").read_text()
   def write(settings):
    envfile.write_text(base+"\n"+"\n".join(k+"="+v for k,v in settings.items())+"\n");envfile.chmod(0o600)
   env={**os.environ,"PYTHONPATH":"backend","PYTHONDONTWRITEBYTECODE":"1"}
   def command(action):return [sys.executable,"backend/identity_server.py",action,"--env-file",str(envfile)]
   for changes in ({"DEPARTMENT_AI_MODEL_KEY":""},{"DEPARTMENT_AI_MAX_INSTANCES":"0"},{"DEPARTMENT_AI_STATE_DIR":"/tmp/invalid-prod-state"}):
    write({**config,**changes})
    r=subprocess.run(command("check"),env=env,capture_output=True,timeout=30)
    assert r.returncode!=0
   check("incomplete model, invalid limit and temporary production state fail preflight")
   write(config)
   r=subprocess.run(command("check"),env=env,capture_output=True,timeout=30)
   check("production-mode preflight succeeds with complete isolated configuration",r.returncode==0)
   with socket.socket() as busy:
    busy.bind(("127.0.0.1",app_port));busy.listen()
    r=subprocess.run(command("serve"),env=env,capture_output=True,timeout=30)
    check("occupied port refuses launch without killing its owner",r.returncode!=0 and busy.getsockname()[1]==app_port)
   with (root/"server.log").open("wb") as log:
    process=subprocess.Popen(command("serve"),env=env,stdout=log,stderr=log,start_new_session=True)
    try:
     with httpx.Client(base_url=f"http://127.0.0.1:{app_port}",headers={"Host":"department.example.test","Origin":"https://department.example.test","X-Forwarded-Proto":"https"},timeout=5) as portal,httpx.Client(base_url=f"http://127.0.0.1:{ai_port}",headers={"Host":"ai-zkxk.example.test","X-Forwarded-Proto":"https"},timeout=5) as ai:
      for _ in range(100):
       assert process.poll() is None,"candidate exited early"
       try:
        if portal.get("/health").status_code==200 and ai.get("/starting").status_code==401:break
       except httpx.HTTPError:pass
       time.sleep(.1)
      else:raise AssertionError("candidate did not become healthy")
      check("anonymous business API denied",portal.get("/api/state").status_code==401)
      response=portal.post("/api/auth/login",json={"username":gid,"password":pw})
      assert response.status_code==200
      check("trusted HTTPS proxy sets Secure and HttpOnly cookie","secure" in response.headers["set-cookie"].lower() and "httponly" in response.headers["set-cookie"].lower())
      portal.headers.update({"Cookie":cookies(response),"X-CSRF-Token":response.json()["csrfToken"],"X-Department-Space":"zkxk"})
      ticket=portal.post("/api/assistant/entry");assert ticket.status_code==200
      check("foreign bootstrap origin rejected",ai.post("/bootstrap",data={"ticket":ticket.json()["ticket"]},headers={"Origin":"https://evil.test"}).status_code==403)
      response=ai.post("/bootstrap",data={"ticket":ticket.json()["ticket"]},headers={"Origin":"https://department.example.test"})
      assert response.status_code==303
      ai.headers.update({"Cookie":cookies(response),"Origin":"https://ai-zkxk.example.test"})
      check("automatic AI entry under HTTPS forwarding",ai.get("/starting").status_code==200 and "secure" in response.headers["set-cookie"].lower())
      check("four-slot config active without starting a runtime",ai.post("/runtime-status").json()["capacity"]==4)
      check("cross-company host and protocol downgrade rejected",ai.get("/starting",headers={"Host":"ai-senyuan.example.test"}).status_code==401 and ai.get("/starting",headers={"X-Forwarded-Proto":"http"}).status_code==403)
      assert portal.post("/api/auth/logout").status_code==200
      check("logout revokes AI entry",ai.get("/starting").status_code==401)
    finally:
     process.terminate()
     try:process.wait(timeout=25)
     except subprocess.TimeoutExpired:process.kill();process.wait();raise
     process=None
   for port in (app_port,ai_port):
    with socket.socket() as sock:assert sock.connect_ex(("127.0.0.1",port))!=0
   check("only owned processes stopped and ephemeral ports released")
  result["passed"]=True
 finally:
  if process:
   process.terminate();process.wait(timeout=25)
  with psycopg.connect(creds["adminDsn"]) as c:
   c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(uid,))
   c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(uid,))
   c.execute("DELETE FROM permission_groups WHERE id=%s",(gid,))
  (STATE/"identity-release-check-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

