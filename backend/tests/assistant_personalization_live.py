"""Disposable real-model/native-UI deployment check, no acceptance service writes."""
import asyncio,json,os,secrets,socket,time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import psycopg,uvicorn
from dotenv import dotenv_values
from psycopg.types.json import Jsonb
from fastapi import Request,HTTPException
from assistant_pool_probe import creds,STATE,ROOT,rpc,until
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.auth import issue,redeem
from app.features.assistant.runtime import Manager,PrivateSocketServer,docker
from app.features.assistant.activity import activity
from app.features.assistant import gateway

RUN=STATE/"personalization-live";RUN.mkdir(mode=0o700,exist_ok=True)
async def main():
    db=create_pool(creds["appDsn"]);db.open(wait=True)
    values=dotenv_values(STATE/"acceptance-preview.env")
    for name in ("DEPARTMENT_AI_MODEL_URL","DEPARTMENT_AI_MODEL_KEY","DEPARTMENT_AI_MODELS"):
        os.environ[name]=values[name]
    models=json.loads(values["DEPARTMENT_AI_MODELS"])
    os.environ["DEPARTMENT_AI_MAX_INSTANCES"]="2"
    users=[];manager=None;server=None;task=None
    sockets=[];origins={}
    for space in ("zkxk","senyuan"):
        s=socket.socket();s.bind(("127.0.0.1",0));s.listen(128);sockets.append(s)
        origins[space]=f"http://127.0.0.1:{s.getsockname()[1]}"
    os.environ["DEPARTMENT_AI_ORIGINS"]=json.dumps(origins)
    (RUN/"done").unlink(missing_ok=True)
    try:
        for space in origins:
            uid=str(uuid4());name="native-live-"+uid[:8];pw=secrets.token_urlsafe(24)
            with psycopg.connect(creds["adminDsn"]) as c:
                c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'原生功能临时验证',%s,%s,false)",(uid,name,HASHER.hash(pw),space))
                c.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(name,name,Jsonb(["assistant.use"])))
                c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(uid,space,name))
            token,_,_=login(db,name,pw,"native-live","native-live")
            p=authenticate(db,token)[0]
            cookie=redeem(db,issue(db,p,space)["ticket"],origins[space])
            users.append({"user":uid,"space":space,"group":name,"origin":origins[space],"cookie":cookie,"principal":p})
        with TemporaryDirectory(prefix="native-live-") as folder:
            os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
            manager=Manager(db,models)
            gateway.app.state.pool=db;gateway.app.state.manager=manager;gateway.app.state.origins=origins
            gateway.app.state.settings=type("Settings",(),{"auth_origin":origins["zkxk"]})()
            @gateway.app.post("/__probe/recycle")
            async def recycle(request:Request):
                p,space=await gateway.ready_identity(request);r=await manager.get(p,space)
                if any((await activity(r)).values()):raise HTTPException(409,"busy")
                r.last=time.monotonic()-100000;r.idle_since=r.last
                await manager.reap_once();assert r.key not in manager.items
                fresh=await manager.get(p,space);assert fresh is not r
                return {"reclaimed":True,"restarted":True}
            controls=[r for r in gateway.app.router.routes if getattr(r,"path","").startswith("/__probe/")]
            gateway.app.router.routes[:]=controls+[r for r in gateway.app.router.routes if r not in controls]
            for u in users:
                runtime=await manager.get(u["principal"],u["space"])
                u["runtime"]=runtime.name;u["root"]=str(runtime.root)
                roster=await rpc(runtime,"agentPresets/list",{})
                assert {p["id"] for p in roster["presets"] if not p.get("broken")}=={"department","standard"},roster
                print("READY",u["space"],"two healthy presets",flush=True)
            server=PrivateSocketServer(uvicorn.Config(gateway.app,log_level="error",access_log=False,lifespan="off",timeout_graceful_shutdown=3))
            task=asyncio.create_task(server.serve(sockets=sockets));await until(lambda:server.started,10)
            data={"users":[{k:v for k,v in u.items() if k!="principal"} for u in users],"baseURL":values["DEPARTMENT_AI_MODEL_URL"],"key":values["DEPARTMENT_AI_MODEL_KEY"],"model":models[0]}
            path=RUN/"browser-input.json";path.write_text(json.dumps(data));path.chmod(0o600)
            print("READY native browser",flush=True)
            await until(lambda:(RUN/"done").exists(),5400)
            await manager.close();manager=None
    finally:
        if server:server.should_exit=True
        if task:
            try:await asyncio.wait_for(task,10)
            except TimeoutError:task.cancel()
        if manager:await manager.close()
        with psycopg.connect(creds["adminDsn"]) as c:
            for u in users:
                c.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(u["user"],))
                c.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(u["user"],))
                c.execute("DELETE FROM user_space_grants WHERE user_id=%s",(u["user"],))
                c.execute("DELETE FROM permission_groups WHERE id=%s",(u["group"],))
        db.close();(RUN/"browser-input.json").unlink(missing_ok=True)
        print("CLEANUP isolated native test",flush=True)
if __name__=="__main__":asyncio.run(main())
