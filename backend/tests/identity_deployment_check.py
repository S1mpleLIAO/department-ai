"""Read-only DB preflight plus configuration/process checks, isolated Aliyun only."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from identity_server import load_environment, database_check, preflight
from app.core.config import get_settings
from app.features.assistant.config import runtime_config, gateway_bindings
from app.features.assistant.runtime import Manager

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/".identity-state"
if not str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028"):
    raise SystemExit("isolated worktree required")


def rejected(fn):
    try:fn()
    except (RuntimeError,ValueError):return
    raise AssertionError("expected a configuration rejection")


def proxy_check():
    """Exercise trusted proxy headers on real sockets, without claiming a TLS/browser test."""
    import httpx
    from http.cookies import SimpleCookie
    directory=Path("/root/.dai-stage-20261028")
    directory.mkdir(mode=0o700,exist_ok=True)
    envfile=STATE/"deployment-proxy-check.env"
    settings={"DEPARTMENT_AUTH_ORIGIN":"https://department.example.test","DEPARTMENT_PYTHON_PORT":"3181",
      "DEPARTMENT_AI_ORIGINS":json.dumps({"zkxk":"https://ai-zkxk.example.test","senyuan":"https://ai-senyuan.example.test"}),
      "DEPARTMENT_AI_RUNTIME_MODE":"production","DEPARTMENT_AI_STATE_DIR":str(directory),
      "DEPARTMENT_AI_GATEWAY_PORT":"3182","DEPARTMENT_AI_MODELS":'["department-test"]',
      "DEPARTMENT_AI_MODEL_URL":"https://model.invalid/v1","DEPARTMENT_AI_MODEL_KEY":"synthetic-not-called"}
    envfile.write_text((STATE/"app.env").read_text()+"\n"+"\n".join(k+"="+v for k,v in settings.items())+"\n")
    envfile.chmod(0o600)
    command=[sys.executable,"backend/identity_server.py","serve","--env-file",str(envfile)]
    with open(STATE/"deployment-proxy-check.log","w") as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url="http://127.0.0.1:3181",headers={"Host":"department.example.test",
                        "Origin":"https://department.example.test","X-Forwarded-Proto":"https"}) as portal, \
                 httpx.Client(base_url="http://127.0.0.1:3182",headers={"Host":"ai-zkxk.example.test",
                        "Origin":"https://department.example.test","X-Forwarded-Proto":"https"}) as ai:
                for _ in range(100):
                    assert process.poll() is None
                    try:
                        if portal.get("/health").status_code==200 and ai.get("/starting").status_code==401:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise AssertionError("production-mode candidate did not start")
                fixture=json.loads((STATE/"assistant-fixture.json").read_text())
                response=portal.post("/api/auth/login",json={"username":fixture["username"],"password":fixture["password"]})
                assert response.status_code==200
                assert "secure" in response.headers["set-cookie"].lower()
                cookie=SimpleCookie();cookie.load(response.headers["set-cookie"])
                portal.headers.update({"Cookie":"; ".join(k+"="+v.value for k,v in cookie.items()),
                                       "X-CSRF-Token":response.json()["csrfToken"]})
                try:
                    ticket=portal.post("/api/assistant/entry",headers={"X-Department-Space":"zkxk"})
                    assert ticket.status_code==200
                    assert ai.post("/bootstrap",data={"ticket":ticket.json()["ticket"]},headers={"Origin":"https://evil.example.test"}).status_code==403
                    response=ai.post("/bootstrap",data={"ticket":ticket.json()["ticket"]})
                    assert response.status_code==303 and response.headers["location"]=="/starting"
                    assert "secure" in response.headers["set-cookie"].lower() and "dsh-auth" not in response.headers["set-cookie"]
                    cookie=SimpleCookie();cookie.load(response.headers["set-cookie"])
                    ai.headers["Cookie"]="; ".join(k+"="+v.value for k,v in cookie.items())
                    assert ai.get("/starting").status_code==200
                    assert ai.get("/starting",headers={"Host":"ai-senyuan.example.test"}).status_code==401
                    assert ai.get("/starting",headers={"X-Forwarded-Proto":"http"}).status_code==403
                finally:assert portal.post("/api/auth/logout").status_code==200
                assert ai.get("/starting").status_code==401
        finally:
            process.terminate()
            try:process.wait(timeout=25)
            except subprocess.TimeoutExpired:process.kill();process.wait();raise
    for port in (3181,3182):
        with socket.socket() as sock:assert sock.connect_ex(("127.0.0.1",port))!=0
    print("production-mode gateway, proxy scheme/host, secure POST ticket, cross-space denial, logout: PASS",flush=True)


def main():
    for script in ("deploy-server.sh","start-server.sh","start-background.sh","start.sh","restart-server.sh","stop-server.sh"):
        result=subprocess.run(["sh",str(ROOT/script)],cwd=ROOT,capture_output=True,text=True,timeout=5)
        assert result.returncode==1 and "身份版本禁止使用旧共享服务" in result.stderr
    print("legacy deployment/start/stop entry points refuse identity checkout: PASS",flush=True)
    with patch.dict(os.environ,{},clear=True):
        load_environment(STATE/"app.env")
        settings=get_settings()
        result=database_check(settings)
        assert result["migrations"]==5
        credentials=json.loads((STATE/"credentials.json").read_text())
        rejected(lambda:database_check(replace(settings,database_url=credentials["adminDsn"])))
        print("migrations, restricted app role, RLS, bootstrap, read-only legacy counts: PASS",flush=True)
        # Public AI hosts cannot share a cookie authority with the portal or each other.
        os.environ.update(DEPARTMENT_AI_RUNTIME_MODE="production",DEPARTMENT_AUTH_ORIGIN="https://dept.example.test",
                          DEPARTMENT_AI_GATEWAY_PORT="3182")
        rejected(runtime_config)
        os.environ["DEPARTMENT_AI_STATE_DIR"]="/tmp/not-persistent"
        rejected(runtime_config)
        os.environ["DEPARTMENT_AI_STATE_DIR"]="/var/lib/dai-ai-candidate"
        assert runtime_config().root==Path("/var/lib/dai-ai-candidate") # No directory creation.
        valid={"zkxk":"https://ai-zkxk.example.test","senyuan":"https://ai-senyuan.example.test"}
        assert gateway_bindings(valid,"production")==[3182]
        for values in ({"zkxk":"https://dept.example.test"},{"zkxk":"http://ai.example.test"},
                       {"zkxk":"https://ai.example.test","senyuan":"https://ai.example.test:443"}):
            rejected(lambda:gateway_bindings(values,"production"))
        print("persistent state, separate HTTPS authorities, explicit gateway port: PASS",flush=True)
        os.environ["DEPARTMENT_AI_RUNTIME_MODE"]="isolated"
        with TemporaryDirectory(prefix="id-deploy-") as directory:
            os.environ["DEPARTMENT_AI_STATE_DIR"]=directory
            manager=Manager(None,["test"])
            rejected(lambda:Manager(None,["test"]))
            namespace=manager.namespace
            (manager.root/"persistence-marker").write_text("retained")
            asyncio.run(manager.close())
            restarted=Manager(None,["test"])
            assert restarted.namespace==namespace and (restarted.root/"persistence-marker").read_text()=="retained"
            asyncio.run(restarted.close())
            Path(directory).chmod(0o755)
            rejected(runtime_config)
            Path(directory).chmod(0o700)
            print("exclusive supervisor ownership, restart state retention, private mode: PASS",flush=True)

        envfile=STATE/"deployment-app-check.env"
        base=(STATE/"app.env").read_text()
        envfile.write_text(base+"\nDEPARTMENT_PYTHON_PORT=3181\nDEPARTMENT_AI_ORIGINS={}\n")
        envfile.chmod(0o600)
        os.environ["DEPARTMENT_AI_MODEL_KEY"]="must-not-inherit"
        load_environment(envfile)
        assert "DEPARTMENT_AI_MODEL_KEY" not in os.environ
        assert not preflight()["ai_enabled"]
        command=[sys.executable,"backend/identity_server.py","serve","--env-file",str(envfile)]
        with socket.socket() as busy:
            busy.bind(("127.0.0.1",3181));busy.listen()
            failure=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=20)
            assert failure.returncode!=0 and busy.getsockname()[1]==3181
        log=open(STATE/"deployment-supervisor-check.log","w")
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log)
        try:
            import httpx
            for _ in range(100):
                assert process.poll() is None
                try:
                    response=httpx.get("http://127.0.0.1:3181/health",timeout=.3)
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise AssertionError("isolated department service did not start")
            assert httpx.get("http://127.0.0.1:3181/api/state").status_code==401
        finally:
            process.terminate()
            try:process.wait(timeout=25)
            except subprocess.TimeoutExpired:process.kill();process.wait();raise
            log.close()
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1",3181))!=0
        print("explicit private env, AI-off launch, busy-port refusal, owned-process shutdown: PASS",flush=True)
    proxy_check()


if __name__=="__main__":main()
