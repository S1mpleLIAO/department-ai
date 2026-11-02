"""Opt-in native Models UI proof; disposable accounts, namespaces and loopback servers.

Experimental API permissions and model transport live ONLY in this test process.
No production/acceptance config, installed helper, or upstream source is changed.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from assistant_pool_probe import creds, STATE, ROOT, rpc, until
from app.core.database import create_pool
from app.features.identity.service import HASHER, login, authenticate
from app.features.assistant.auth import issue, redeem, live_principal
from app.features.assistant.runtime import Manager, PrivateSocketServer
from app.features.assistant import runtime as runtime_module, gateway, policy
from app.features.assistant.activity import activity

RUN=STATE/"native-models-probe"
RUN.mkdir(mode=0o700,exist_ok=True)


async def main():
    db=create_pool(creds["appDsn"]);db.open(wait=True)
    users=[];calls=[];servers=[];tasks=[];manager=None
    original_docker=runtime_module.docker
    original_rpc=policy.rpc
    sockets=[]
    for _ in range(2):
        sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128);sockets.append(sock)
    origins={space:f"http://127.0.0.1:{sock.getsockname()[1]}" for space,sock in zip(("zkxk","senyuan"),sockets)}
    os.environ["DEPARTMENT_AI_ORIGINS"]=json.dumps(origins)
    os.environ["DEPARTMENT_AI_MAX_INSTANCES"]="2"
    os.environ["DEPARTMENT_AI_IDLE_SECONDS"]="60"
    os.environ["DEPARTMENT_AI_MIN_AVAILABLE_MIB"]="1200"
    model_keys={};principal_by_user={}

    def model_bridge(runtime):
        app=FastAPI()
        app.add_middleware(gateway.RuntimeLeaseMiddleware,runtime=runtime)
        @app.get("/probe/v1/models")
        async def models(request:Request):
            runtime.validate()
            if request.headers.get("authorization")!="Bearer "+model_keys[runtime.user]:raise HTTPException(401)
            return {"object":"list","data":[{"id":"probe-fast"},{"id":"probe-reason"}]}
        @app.post("/probe/v1/chat/completions")
        async def completion(request:Request):
            runtime.validate()
            if request.headers.get("authorization")!="Bearer "+model_keys[runtime.user]:raise HTTPException(401)
            data=await request.json()
            if data.get("model") not in ("probe-fast","probe-reason"):raise HTTPException(400)
            calls.append({"user":runtime.user,"space":runtime.space,"model":data["model"],"credentialMatched":True})
            text=f"NATIVE_OK {runtime.space} {data['model']}"
            async def stream():
                for delta,finish in [({"role":"assistant","content":text},None),({},"stop")]:
                    yield "data: "+json.dumps({"id":"probe","object":"chat.completion.chunk","created":0,
                        "model":data["model"],"choices":[{"index":0,"delta":delta,"finish_reason":finish}]})+"\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(stream(),media_type="text/event-stream")
        return app

    def native_rpc(method,body,models):
        args=body.get("payload",{}).get("args",{})
        if body.get("type")!="client-request" or body.get("method")!=method or not isinstance(args,dict):policy.deny()
        if method=="settings/mutate" and args.get("ns")=="ui-onboarding":
            if args.get("ops")!=[{"op":"set","path":["welcomeNoticeVersion"],"value":"2026-08-13.1"}]:policy.deny()
            return body
        if method in {"llm/listProviders","llm/listConfigurableProviders","credentials/describe"}:return body
        if method in {"credentials/set","credentials/unset"}:
            # Synthetic secrets only, native private store remains the owner.
            if args.get("ref")!="NATIVE_PROBE_API_KEY":policy.deny()
            return body
        if method=="llm/discoverModels":
            if "http://127.0.0.1:39100/probe/v1" not in json.dumps(args):policy.deny()
            return body
        if method=="settings/mutate" and args.get("ns")=="llm-pi-ai":
            for op in args.get("ops",[]):
                if op.get("op")!="set" or op.get("path")!=["providers","native-probe"]:policy.deny()
                value=op.get("value",{})
                if value.get("baseURL")!="http://127.0.0.1:39100/probe/v1" or value.get("api")!="openai-completions":policy.deny()
                if value.get("apiKeyEnv") not in (None,"NATIVE_PROBE_API_KEY"):policy.deny()
            return body
        if method=="session/selectModel":
            req=args.get("request",{})
            if req.get("provider")=="native-probe" and req.get("model") in ("probe-fast","probe-reason"):return body
        if method in ("settings/update","settings/mutate") and args.get("ns")=="agent-default-model":
            # The composer persists its selected model through this native namespace.
            return body
        return original_rpc(method,body,models)

    try:
        for space in origins:
            uid=str(uuid4());name="native-"+uid[:8];password=secrets.token_urlsafe(24);group="probe-"+uid[:8]
            with psycopg.connect(creds["adminDsn"]) as conn:
                conn.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,%s,%s,%s,false)",(uid,name,"原生模型验证",HASHER.hash(password),space))
                conn.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",(group,group,Jsonb(["assistant.use"])))
                conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,%s,%s)",(uid,space,group))
            token,_,_=login(db,name,password,"native-models-probe","native-models-probe")
            principal=authenticate(db,token)[0];principal_by_user[uid]=principal
            ticket=issue(db,principal,space)
            cookie=redeem(db,ticket["ticket"],origins[space])
            model_keys[uid]=secrets.token_urlsafe(24)
            users.append({"user":uid,"space":space,"group":group,"origin":origins[space],"cookie":cookie,"key":model_keys[uid]})

        with TemporaryDirectory(prefix="native-models-") as folder:
            os.environ["DEPARTMENT_AI_STATE_DIR"]=folder
            manager=Manager(db,["department-test"])
            # One tiny test-only transport file; shared Harness sources stay read-only.
            relay=Path(folder)/"relay.mjs"
            relay.write_text((ROOT/"harness/identity/relay.mjs").read_text().replace(
                "headers:{'content-type':req.headers['content-type']||'application/json'}",
                "headers:{'content-type':req.headers['content-type']||'application/json',authorization:req.headers.authorization||''}"))
            relay.chmod(0o644);Path(folder).chmod(0o755)
            async def docker(*args):
                if args[0]=="run":
                    parts=list(args)
                    mounted=next(parts[i+1] for i,a in enumerate(parts[:-1]) if a=="--mount" and ",dst=/config," in parts[i+1])
                    config=Path(mounted.split("src=",1)[1].split(",dst=",1)[0])/"patch.yml"
                    data=json.loads(config.read_text())
                    data=[row for row in data if row["id"]!="ui-settings-models"]
                    config.write_text(json.dumps(data))
                    i=parts.index("--entrypoint");parts[i:i]=["--mount",f"type=bind,src={relay},dst=/integration/relay.mjs,readonly"]
                    args=tuple(parts)
                return await original_docker(*args)
            with patch.object(runtime_module,"docker",docker),patch.object(gateway,"bridge_app",model_bridge),patch.object(gateway,"rpc",native_rpc),patch.object(gateway,"PERSONAL_SETTINGS",policy.PERSONAL_SETTINGS|{"llm-pi-ai","llm-deepseek","ui-onboarding"}):
                gateway.app.state.pool=db;gateway.app.state.manager=manager;gateway.app.state.origins=origins
                gateway.app.state.settings=type("Settings",(),{"auth_origin":origins["zkxk"]})()
                # Test controls are authenticated and installed only in this test process.
                @gateway.app.post("/__probe/recycle")
                async def recycle(request:Request):
                    p,space=await gateway.ready_identity(request)
                    runtime=await manager.get(p,space)
                    if any((await activity(runtime)).values()):raise HTTPException(409,"busy")
                    runtime.last=time.monotonic()-120;runtime.idle_since=runtime.last
                    await manager.reap_once()
                    assert runtime.key not in manager.items,"idle instance was not reclaimed"
                    # The standard scheduler recreates from the SAME private state.
                    fresh=await manager.get(p,space)
                    assert fresh is not runtime
                    return {"reclaimed":True,"restarted":True}
                @gateway.app.get("/__probe/results")
                async def results(request:Request):
                    p,space=await gateway.identity(request)
                    return {"calls":[c for c in calls if c["user"]==p.user_id],"space":space}
                controls=[route for route in gateway.app.router.routes if getattr(route,"path","").startswith("/__probe/")]
                gateway.app.router.routes[:]=controls+[route for route in gateway.app.router.routes if route not in controls]
                for user in users:
                    await manager.get(principal_by_user[user["user"]],user["space"])
                    print("READY runtime",user["space"],flush=True)
                server=PrivateSocketServer(uvicorn.Config(gateway.app,log_level="error",access_log=False,lifespan="off",timeout_graceful_shutdown=3))
                tasks.append(asyncio.create_task(server.serve(sockets=sockets)));servers.append(server)
                await until(lambda:server.started,10)
                path=RUN/"browser-input.json";path.write_text(json.dumps({"users":users}));path.chmod(0o600)
                print("READY browser-input",flush=True)
                await until(lambda:(RUN/"done").exists(),2400)
                report={"calls":calls,"runtimeNamespace":manager.namespace,"productionUnchanged":True}
                (RUN/"server-results.json").write_text(json.dumps(report,indent=2))
                # Native settings and credential files survive the tested recycle.
                for user in users:
                    root=manager.root/(user["user"]+"-"+user["space"])/"home/dsh"
                    found=[p for p in root.rglob("*") if p.is_file() and p.suffix in (".yaml",".yml") and user["key"] in p.read_text(errors="ignore")]
                    assert found,"native key was not persisted"
                    assert all(p.stat().st_mode & 0o077==0 for p in found),"credentials file is not private"
                print("PASS native credential persistence and file permissions",flush=True)
                await manager.close();manager=None
    finally:
        for server in servers:server.should_exit=True
        for task in tasks:
            try:await asyncio.wait_for(task,10)
            except TimeoutError:task.cancel()
        if manager:await manager.close()
        with psycopg.connect(creds["adminDsn"]) as conn:
            for user in users:
                conn.execute("UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s",(user["user"],))
                conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s",(user["user"],))
                conn.execute("DELETE FROM user_space_grants WHERE user_id=%s",(user["user"],))
                conn.execute("DELETE FROM permission_groups WHERE id=%s",(user["group"],))
        db.close();(RUN/"browser-input.json").unlink(missing_ok=True)
        print("CLEANUP temporary accounts disabled and owned runtimes stopped",flush=True)

if __name__=="__main__":asyncio.run(main())
