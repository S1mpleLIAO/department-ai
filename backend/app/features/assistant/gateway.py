"""Separate AI origin server. Run only via explicit isolated environment settings."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
import re
from urllib.parse import parse_qs, urlsplit, quote
import httpx
import uvicorn
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from app.core.config import get_settings
from app.core.database import create_pool
from .recipes import SPACE_PATTERN
from .auth import origins, redeem, gateway_identity
from .policy import validate_workspace_directory, rpc, frame, PERSONAL_SETTINGS
from .resources import call
from .storage import admission
from .runtime import Manager, ROOT
from .config import runtime_config, gateway_bindings


async def bounded_json(request,limit=1024*1024):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>limit: raise HTTPException(413,"请求过大")
    try: return json.loads(data)
    except (ValueError,UnicodeError): raise HTTPException(400,"请求格式无效")


class RuntimeLeaseMiddleware:
    """Keep the lease until the ASGI response/stream has fully completed."""
    def __init__(self, app, runtime):
        self.app, self.runtime = app, runtime
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async with self.runtime.hold(touch=True):
            await self.app(scope, receive, send)


def bridge_app(runtime):
    bridge=FastAPI()
    bridge.add_middleware(RuntimeLeaseMiddleware, runtime=runtime)
    @bridge.api_route("/personal-model",methods=["GET","POST"])
    async def personal_model(request:Request):
        from .personal_models import forward
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>20*1024*1024:raise HTTPException(413,"模型请求超过 20 MiB")
        return await forward(runtime,request,bytes(body))

    @bridge.post("/tool/{name}")
    async def tool(name:str,request:Request):
        p=await run_in_threadpool(runtime.validate)
        args=await bounded_json(request,65536)
        if not isinstance(args,dict): raise HTTPException(422,"工具参数无效")
        if name in ("department_uploaded_document_read", "department_reimbursement_generate"):
            from .reimbursement import read_upload, generate
            async with admission(runtime,16*1024*1024,64,enabled=name.endswith("_generate")):
                return await (read_upload(runtime,args) if name.endswith("_read") else generate(runtime,args))
        async with admission(runtime,10*1024*1024,513,enabled=name=="department_skill_prepare"):
            return await run_in_threadpool(call,runtime.manager.pool,p,runtime.space,name,args)

    @bridge.post("/v1/chat/completions")
    async def model(request:Request):
        await run_in_threadpool(runtime.validate)
        data=await bounded_json(request,2*1024*1024)
        if not isinstance(data,dict) or data.get("model") not in runtime.manager.models:
            raise HTTPException(403,"模型未授权")
        if not isinstance(data.get("max_tokens",4096),int) or not 1<=data.get("max_tokens",4096)<=4096:
            raise HTTPException(422,"模型输出上限为 4096 tokens")
        data["max_tokens"]=data.get("max_tokens",4096)
        target=os.getenv("DEPARTMENT_AI_MODEL_URL","").rstrip("/")
        key=os.getenv("DEPARTMENT_AI_MODEL_KEY","")
        if not target or not key: raise HTTPException(503,"管理员尚未配置模型出口")
        if urlsplit(target).scheme not in ("http","https"): raise HTTPException(503,"模型出口配置无效")
        client=httpx.AsyncClient(timeout=httpx.Timeout(120,connect=10),follow_redirects=False)
        try:
            response=await client.send(client.build_request("POST",target+"/chat/completions",json=data,
                headers={"Authorization":"Bearer "+key}),stream=True)
        except BaseException as error:
            await client.aclose()
            if isinstance(error,httpx.HTTPError):raise HTTPException(502,"模型出口连接失败")
            raise
        async def stream():
            try:
                async for chunk in response.aiter_bytes():
                    await run_in_threadpool(runtime.validate)
                    yield chunk
            finally:
                await response.aclose();await client.aclose()
        if response.status_code>=300:
            await response.aclose();await client.aclose()
            raise HTTPException(502,"模型服务拒绝请求")
        return StreamingResponse(stream(),media_type=response.headers.get("content-type","application/json"))
    return bridge


@asynccontextmanager
async def lifespan(app):
    settings=get_settings()
    models=json.loads(os.getenv("DEPARTMENT_AI_MODELS",'["department-test"]'))
    if not isinstance(models,list) or not models or not all(isinstance(m,str) and 0<len(m)<128 for m in models):
        raise RuntimeError("Invalid allowed models")
    pool=create_pool(settings.database_url);pool.open(wait=True)
    app.state.pool,app.state.settings=pool,settings
    app.state.origins=origins()
    manager=None
    try:
        manager=Manager(pool,models)
        await manager.recover()
        app.state.manager=manager
    except BaseException:
        if manager: await manager.close()
        pool.close();raise
    monitor=asyncio.create_task(app.state.manager.sweep())
    try: yield
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError): await monitor
        await app.state.manager.close();pool.close()


app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

def prefix(request):
    return request.scope.get("ai_prefix", "")


def cookie_name(request, space):
    # Old intranet cookies covered every path on this host, including the new port.
    return ("department_ai_scoped_" if prefix(request) else "department_ai_") + space


class SpacePath:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and "*" in scope["app"].state.origins:
            match = re.match(r"^/s/("+SPACE_PATTERN+r")(?=/)", scope["path"])
            if match and scope["raw_path"].startswith(match.group().encode("ascii") + b"/"):
                base = match.group()
                scope = dict(scope, ai_prefix=base, ai_space=match[1],
                             path=scope["path"][len(base):],
                             raw_path=scope["raw_path"][len(base):])
        await self.app(scope, receive, send)


app.add_middleware(SpacePath)


def origin_of(request):
    origin=str(request.url).split("/",3)[:3]
    origin="/".join(origin).replace("ws://","http://").replace("wss://","https://")
    space=next((s for s,o in request.app.state.origins.items() if o==origin),None)
    if space == "*": space = request.scope.get("ai_space")
    if space is None: raise HTTPException(403,"AI 入口不受信任")
    return origin,space

async def identity(request):
    origin,space=origin_of(request)
    p,actual=await run_in_threadpool(gateway_identity,request.app.state.pool,
                                    request.cookies.get(cookie_name(request, space)),origin)
    if actual!=space: raise HTTPException(403,"空间不一致")
    return p,space


@app.exception_handler(HTTPException)
async def error(request,error):
    if "text/html" in request.headers.get("accept","") or request.url.path in ("/bootstrap","/starting"):
        from html import escape
        target=escape(request.app.state.settings.auth_origin+"/department#assistant",quote=True)
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>个人 AI 助手</title>'
          '<main style="font:16px system-ui;padding:32px"><h2>暂时无法打开 AI 助手</h2><p role="alert">'+
          escape(str(error.detail))+'</p><a target="_top" href="'+target+'">返回部门系统重新打开</a></main></html>',
          status_code=error.status_code,headers={"Cache-Control":"no-store"})
    return JSONResponse({"detail":error.detail},status_code=error.status_code,headers={"Cache-Control":"no-store"})


@app.middleware("http")
async def headers(request,call_next):
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Content-Security-Policy"]="frame-ancestors "+request.app.state.settings.auth_origin
    return response


@app.post("/bootstrap")
async def bootstrap(request:Request):
    origin,space=origin_of(request)
    if request.headers.get("origin")!=request.app.state.settings.auth_origin:
        raise HTTPException(403,"请从部门系统打开")
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>1024:raise HTTPException(413,"请求过大")
    try:params=parse_qs(data.decode())
    except UnicodeError:raise HTTPException(400,"入口票据格式无效")
    token=await run_in_threadpool(redeem,request.app.state.pool,params.get("ticket",[""])[0],origin,space)
    response=RedirectResponse(prefix(request)+"/starting",status_code=303)
    response.set_cookie(cookie_name(request, space),token,max_age=604800,httponly=True,
                        secure=origin.startswith("https://"),samesite="lax",path=prefix(request)+"/")
    return response


@app.get("/starting")
async def starting(request:Request):
    await identity(request)
    return HTMLResponse((ROOT/"harness/identity/starting.html").read_text())


async def ready_identity(request):
    origin,_=origin_of(request)
    if request.headers.get("origin")!=origin: raise HTTPException(403,"请求来源无效")
    return await identity(request)


@app.post("/ready")
async def ready(request:Request):
    p,space=await ready_identity(request)
    state=await request.app.state.manager.status(p,space,retry=request.query_params.get("retry")=="1")
    return JSONResponse(state,status_code=200 if state["ready"] else 202)


@app.post("/waiting/cancel")
async def cancel_waiting(request:Request):
    p,space=await ready_identity(request)
    return await request.app.state.manager.cancel(p,space)


@app.post("/runtime-status")
async def runtime_status(request:Request):
    p,space=await ready_identity(request)
    return await request.app.state.manager.status(p,space,enqueue=False)


@app.api_route("/{path:path}",methods=["GET","POST"])
async def proxy(path:str,request:Request):
    p,space=await identity(request)
    origin,_=origin_of(request)
    method=request.method
    if "\\" in path or any(part in (".","..") for part in path.split("/")) or "%" in path:
        raise HTTPException(403,"无效的资源路径")
    if method=="POST" and request.headers.get("origin")!=origin:
        raise HTTPException(403,"请求来源无效")
    if request.query_params.get("token") is not None:
        raise HTTPException(403,"请使用部门登录入口")
    data=None
    upload=path=="api/session/uploadFileBinary" and method=="POST"
    raw=None
    if upload:
        if len(request.query_params.multi_items())!=len(request.query_params) or set(request.query_params)-{"sessionId","name"} or request.headers.get("content-type","").split(";")[0]!="application/octet-stream":
            raise HTTPException(422,"附件上传格式无效")
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>20*1024*1024:raise HTTPException(413,"附件不能超过 20 MiB")
        name="session/uploadFileBinary"
    elif path.startswith("api/"):
        if method=="POST":
            name=path[4:].replace(".","/")
            data=rpc(name,await bounded_json(request),request.app.state.manager.models)
        elif path=="api/file":
            if set(request.query_params)-{"path","download"}: raise HTTPException(403,"文件参数无效")
        else: raise HTTPException(403,"此接口未授权")
    elif method=="GET" and path=="plugins/":
        # Harness combo bundles use a second question mark, not ordinary query parameters.
        if not re.fullmatch(r"\?@deepseek-ai/[a-z0-9-]+/client\.(?:js|css)(?:,@deepseek-ai/[a-z0-9-]+/client\.(?:js|css))*&rev=[a-f0-9]+",request.url.query):
            raise HTTPException(403,"此插件资源未授权")
    elif method!="GET" or not (path=="" or path.startswith(("assets/","modules/")) or path in ("favicon.ico","manifest.webmanifest")):
        raise HTTPException(403,"此页面接口未授权")
    state=await request.app.state.manager.status(p,space,enqueue=False)
    if not state["ready"]:
        if path=="": return RedirectResponse(prefix(request)+"/starting",status_code=303)
        raise HTTPException(409,"个人 AI 尚未就绪或已空闲回收，请重新打开")
    touch=method=="POST" and name not in ("session/list","session/get","settings/get","settings/describe","commands/list")
    writing=upload or (data is not None and name in ("session/create","session/prompt","session/fork","session/updateQueue","directoryPicker/createDirectory","workspace/create","commands/execute"))
    async with request.app.state.manager.lease(p,space,touch=touch) as runtime, admission(runtime,2*len(raw) if upload else 1024*1024,4,enabled=writing):
        if upload: runtime.session_epoch(request.query_params.get("sessionId"))
        if data: validate_workspace_directory(runtime.root,name,data)
        if data and name in ("agentPresets/select","commands/execute"):runtime.session_epoch(data["payload"]["args"].get("agentId"))
        if data and name in ("session/prompt","session/fork","session/updateQueue"):
            runtime.session_epoch(data["payload"]["args"].get("request",{}).get("sessionId"))
        target="/"+path+("?"+request.url.query if request.url.query else "")
        try:
            response=await runtime.client.request(method,target,content=bytes(raw),headers={"Content-Type":"application/octet-stream"}) if upload else await runtime.client.request(method,target,json=data)
        except httpx.HTTPError:
            raise HTTPException(503,"个人 AI 连接中断，请重新打开")
        # Never return upstream auth challenges or cookies to the browser.
        if response.status_code==401: raise HTTPException(503,"个人 AI 认证正在恢复，请重新打开")
        if data and name in ("session/create","session/fork") and response.status_code==200:
            result=response.json().get("result",{})
            if result.get("ok") and isinstance(result.get("value"),dict):
                runtime.session_epoch(result["value"]["sessionId"],create=True)
        if data and name=="settings/canOpenAgentPresetDirectory":
            result=response.json()
            if result.get("result",{}).get("ok"):result["result"]["value"]=False
            return JSONResponse(result)
        if data and name=="llm/listConfigurableProviders" and response.status_code==200:
            result=response.json()
            value=result.get("result",{}).get("value")
            if isinstance(value,list):result["result"]["value"]=[p for p in value if p.get("provider")!="department"]
            return JSONResponse(result)
        if data and name=="commands/list" and response.status_code==200:
            result=response.json()
            if result.get("result",{}).get("ok"):result["result"]["value"]=[]
            return JSONResponse(result)
        if data and path[4:].replace(".","/")=="settings/describe" and response.status_code==200:
            result=response.json()
            value=result.get("result",{}).get("value")
            if isinstance(value,dict):
                value["namespaces"]=[n for n in value.get("namespaces",[]) if n.get("ns") in PERSONAL_SETTINGS]
                value["hasDocument"]=False
            return JSONResponse(result)
        if path=="api/file":
            return Response(response.content,status_code=response.status_code,media_type="application/octet-stream",
                            headers={"Content-Disposition":"attachment; filename*=UTF-8\'\'"+quote(request.query_params.get("path","download").rsplit("/",1)[-1],safe="")})
        if path=="" and response.status_code==200:
            style=(ROOT/"harness/identity/managed.css").read_text()
            html = response.text
            if prefix(request):
                base = prefix(request) + "/"
                script = (ROOT/"harness/identity/space-path.js").read_text()
                html = html.replace('<base href="/">', '<base href="'+base+'">')
                html = re.sub(r"""(["'])/(assets/|modules/|plugins/|favicon\.ico|manifest\.webmanifest)""",
                              lambda m: m[1]+base+m[2], html)
                html = html.replace("<head>", "<head><script>window.departmentScope="+
                                    json.dumps([base,str(p.user_id)])+";"+script+"</script>", 1)
            return HTMLResponse(html.replace("</head>","<style>"+style+"</style><script>"+(ROOT/"harness/identity/runtime-status.js").read_text()+"</script></head>",1))
        return Response(response.content,status_code=response.status_code,
                        media_type=response.headers.get("content-type","application/octet-stream"))


@app.websocket("/api/remote.mux")
async def mux(ws:WebSocket):
    try:
        origin,_=origin_of(ws)
        if ws.headers.get("origin")!=origin: raise HTTPException(403,"来源无效")
        p,space=await identity(ws)
        runtime=await ws.app.state.manager.get(p,space)
    except HTTPException:
        await ws.close(code=1008);return
    await ws.accept();runtime.sockets.add(ws)
    try:
        async with websockets.unix_connect(str(runtime.socket),uri="ws://runtime/api/remote.mux",max_size=4*1024*1024) as upstream:
            async def incoming():
                while True:
                    text=await ws.receive_text()
                    await identity(ws);await run_in_threadpool(runtime.validate)
                    if len(text)>65536: raise HTTPException(413,"消息过大")
                    async with runtime.hold():
                        await upstream.send(json.dumps(frame(json.loads(text))))
            async def outgoing():
                async for text in upstream:
                    await identity(ws);await run_in_threadpool(runtime.validate)
                    await ws.send_text(text)
            tasks=[asyncio.create_task(incoming()),asyncio.create_task(outgoing())]
            try:
                done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                for task in done: task.result()
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    except Exception:
        with suppress(Exception): await ws.close(code=1008)
    finally: runtime.sockets.discard(ws)


if __name__=="__main__":
    import socket
    get_settings()  # Load only the explicitly selected environment before reading AI settings.
    sockets=[]
    for port in gateway_bindings(origins(),runtime_config().mode):
        sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        sock.bind(("0.0.0.0" if os.getenv("DEPARTMENT_INTRANET_HTTP")=="1" else "127.0.0.1",port));sock.listen(128);sockets.append(sock)
    uvicorn.Server(uvicorn.Config(app,log_level="warning",access_log=False,timeout_graceful_shutdown=3,
                    proxy_headers=True,forwarded_allow_ips="127.0.0.1")).run(sockets=sockets)
