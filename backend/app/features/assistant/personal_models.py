"""Native personal model settings; DNS-pinned public-only model transport."""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlsplit
import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from fastapi import HTTPException

PRESETS={"department","standard"}
NAMESPACES={"llm-pi-ai","agent-presets","ui-onboarding"}

def reject(message="个人模型配置无效，不能修改部门受管配置"):
    raise HTTPException(403,message)

def provider(value):
    return isinstance(value,str) and bool(re.fullmatch(r"[a-z][a-z0-9-]{0,79}",value)) and value!="department"

def credential(value):
    return isinstance(value,str) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}_API_KEY",value)) and not value.startswith("DEPARTMENT_")

def public_url(value):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<=32 for c in value):reject("模型地址无效")
    try:
        url=urlsplit(value);port=url.port
        if url.scheme not in ("https","http") or not url.hostname or url.username or url.password or url.fragment:raise ValueError()
        host=url.hostname.rstrip(".").lower()
        if host=="localhost" or host.endswith((".localhost",".local",".internal")):raise ValueError()
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address and not address.is_global:raise ValueError()
        if port is not None and not 1<=port<=65535:raise ValueError()
    except ValueError:reject("模型地址必须是公网 HTTP(S) 地址，不支持本机或内网")
    return url

def validate_value(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ("__proto__","prototype","constructor"):reject()
            if key=="baseURL":public_url(item)
            if key=="apiKeyEnv" and not credential(item):reject()
            validate_value(item)
    elif isinstance(value,list):
        for item in value:validate_value(item)

def settings_ops(args):
    ops=args.get("ops")
    if set(args)-{"ns","ops","expectedRevision"} or not isinstance(ops,list) or not 1<=len(ops)<=128:reject()
    revision=args.get("expectedRevision")
    if revision is not None and (type(revision) is not int or revision<0):reject()
    for op in ops:
        path=op.get("path") if isinstance(op,dict) else None
        if not isinstance(path,list) or not 2<=len(path)<=12 or path[0]!="providers" or not provider(path[1]):reject()
        if any(not isinstance(p,(str,int)) or p in ("__proto__","prototype","constructor") for p in path):reject()
        if op.get("op") not in ("set","unset") or set(op)-{"op","path","value"}:reject()
        if op["op"]=="set":
            if "value" not in op:reject()
            if path[-1]=="baseURL":public_url(op["value"])
            if path[-1]=="apiKeyEnv" and not credential(op["value"]):reject()
            validate_value(op["value"])

class PublicNetwork(AutoBackend):
    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        host=host.decode() if isinstance(host,bytes) else host
        records=await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM),timeout or 10)
        addresses=list(dict.fromkeys(r[4][0] for r in records))
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise httpcore.ConnectError("Model destination is not public")
        # Connect to the checked IP; TLS still verifies the original hostname.
        return await super().connect_tcp(addresses[0],port,timeout,local_address,socket_options)

def public_client():
    transport=httpx.AsyncHTTPTransport(retries=0)
    # Pinned httpx 0.28/httpcore 1.0 pool extension; covered by live HTTPS checks.
    transport._pool=httpcore.AsyncConnectionPool(network_backend=PublicNetwork(),max_connections=4)
    return httpx.AsyncClient(transport=transport,trust_env=False,timeout=httpx.Timeout(180,connect=10),follow_redirects=False)

async def forward(runtime,request,body):
    from fastapi.responses import StreamingResponse
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(runtime.validate)
    target=request.headers.get("x-department-model-target","")
    url=public_url(target)
    path=url.path.rstrip("/")
    allowed=(request.method=="GET" and path.endswith("/models")) or (
        request.method=="POST" and path.endswith(("/chat/completions","/responses","/messages")))
    if not allowed:reject("个人出口仅支持模型列表和模型调用")
    headers={k:v for k,v in request.headers.items() if k.lower() in (
        "authorization","content-type","accept","x-api-key","anthropic-version","anthropic-beta","openai-organization","openai-project")}
    client=public_client()
    try:
        response=await client.send(client.build_request(request.method,target,headers=headers,content=body),stream=True)
    except BaseException as error:
        await client.aclose()
        if isinstance(error,(httpx.HTTPError,OSError,TimeoutError)):raise HTTPException(502,"模型服务连接失败，请检查公网地址")
        raise
    if response.status_code>=300:
        code=response.status_code
        await response.aclose();await client.aclose()
        raise HTTPException(code if 400<=code<500 else 502,f"模型服务返回 HTTP {code}，请检查地址、密钥和模型")
    async def stream():
        total=0
        try:
            async for chunk in response.aiter_bytes():
                await run_in_threadpool(runtime.validate)
                total+=len(chunk)
                if total>32*1024*1024:raise RuntimeError("Model response too large")
                yield chunk
        finally:
            await response.aclose();await client.aclose()
    return StreamingResponse(stream(),media_type=response.headers.get("content-type","application/json"))
