"""Private runtime supervisor. Fixed container recipe; never accepts Docker arguments."""
import asyncio
import json
import hashlib
import fcntl
import logging
import os
from pathlib import Path
import re
import time
from contextlib import contextmanager, asynccontextmanager
from uuid import UUID
import httpx
import uvicorn
from fastapi import HTTPException
from .auth import live_principal
from .resources import revision
from .config import runtime_config

ROOT=Path(__file__).resolve().parents[4]
LABEL="department.identity-ai"


class PrivateSocketServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # Only the outer gateway owns process signals; instance servers are tasks.
        yield

async def docker(*args):
    from .host_command import command
    proc=await asyncio.create_subprocess_exec(*command(*args),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try: out,err=await asyncio.wait_for(proc.communicate(),30)
    except TimeoutError:
        proc.kill();await proc.wait();raise HTTPException(503,"个人 AI 运行管理超时")
    if proc.returncode:
        logging.getLogger(__name__).warning("Isolated container %s failed: %s",args[0],err.decode()[:800])
        raise HTTPException(503,"个人 AI 运行管理失败")
    return out.decode().strip()


class Runtime:
    def __init__(self,manager,p,space):
        self.manager,self.session,self.space=manager,p.session_id,space
        self.user=str(UUID(p.user_id))
        self.key=self.user+"-"+space
        self.name="department-id-ai-"+manager.namespace+"-"+self.key
        self.root=manager.root/self.key
        self.socket=self.root/"transport/web.sock"
        self.client=None
        self.task=None
        self.bridge=None
        self.last=time.monotonic()
        self.fingerprint=revision(manager.pool,p,space)
        self.sockets=set()
        self.stopped=False
        self.ready=False
        self.stop_lock=asyncio.Lock()
        self.guard=asyncio.Lock()
        self.active=0
        self.idle_since=None
        self.retiring=False
        self.cleaned=False

    def validate(self):
        if self.stopped: raise HTTPException(409,"个人 AI 已停止，请重新打开")
        p=live_principal(self.manager.pool,self.session,self.space)
        if revision(self.manager.pool,p,self.space)!=self.fingerprint:
            raise HTTPException(409,"授权或已发布资料已变化，请重新打开 AI 助手")
        return p

    def session_epoch(self,session_id,create=False):
        path=self.root/".control/session-authorizations.json"
        bindings=json.loads(path.read_text()) if path.exists() else {}
        epoch=hashlib.sha256(self.fingerprint.encode()).hexdigest()
        if create:
            bindings[session_id]=epoch
            temporary=path.with_suffix(".tmp")
            temporary.write_text(json.dumps(bindings));temporary.chmod(0o600);temporary.replace(path)
        elif not session_id or bindings.get(session_id)!=epoch:
            raise HTTPException(409,"这段对话的授权或资料版本已变化，请新建对话；历史记录仍可查看")

    async def start(self):
        from .compatibility import verify
        await asyncio.to_thread(verify,self.manager.config.harness)
        available=int(re.search(r"MemAvailable:\s+(\d+)",Path("/proc/meminfo").read_text())[1])
        if available<900*1024: raise HTTPException(503,"服务器空闲内存不足，请稍后打开")
        leftovers=await docker("ps","-aq","--filter","name=^/"+self.name+"$","--filter","label="+LABEL+"=true")
        if leftovers:
            mounts=json.loads(await docker("inspect","--format","{{json .Mounts}}",self.name))
            if not any(m["Source"]==str(self.root/"home") and m["Destination"]=="/home/assistant" for m in mounts):
                raise HTTPException(503,"个人 AI 实例归属不匹配，请联系管理员")
            await docker("rm","-f",self.name)
        if os.geteuid()!=0:
            await docker("prepare",self.key)
        for folder in ("home","home/workspace","transport","bridge","config",".control"):
            path=self.root/folder
            if path.resolve()!=path: raise HTTPException(503,"个人 AI 目录不能包含符号链接")
            path.mkdir(parents=True,exist_ok=True,mode=0o700)
            os.chown(path,10001,10001)
        # The module and preset remain read-only even to the instance UID.
        config=self.root/"config"
        preset=config/"presets/department";preset.mkdir(parents=True,exist_ok=True)
        for path in (config/"presets",preset): path.chmod(0o755)
        from .department_preset import composition, METADATA
        (preset/"agent.cordis.yml").write_text(json.dumps(composition(ROOT)))
        (preset/"preset.yml").write_text(json.dumps(METADATA,ensure_ascii=False))
        standard=config/"presets/standard";standard.mkdir(parents=True,exist_ok=True);standard.chmod(0o755)
        source=self.manager.config.harness/"packages/preset/agent-presets/presets/standard/agent.cordis.yml"
        (standard/"agent.cordis.yml").write_text(source.read_text()+"\n- id: department-tools\n  name: /integration/tools.ts\n")
        (standard/"preset.yml").write_text(json.dumps({"name":"通用编程","description":"原生标准模式；文件与终端在个人隔离容器内运行","order":1},ensure_ascii=False))
        patch=[
          {"id":"agent-presets","config":{"default":"department","includeShippedRoot":False,"includeUserRoot":False,
             "roots":[{"path":"/config/presets","trust":"system"}]}},
          {"id":"agent-default-model","config":{"provider":"department","model":self.manager.models[0]}},
          {"id":"llm-deepseek","disabled":True},
          {"id":"llm-pi-ai","config":{"providers":{"department":{"api":"openai-completions",
            "apiKeyEnv":"DEPARTMENT_LOCAL_MODEL","baseURL":"http://127.0.0.1:39100/v1",
            "retryPolicy":{"mode":"normal","maxRetries":0},
            "models":[{"id":m,"name":m,"contextWindow":32768,"maxTokens":4096} for m in self.manager.models]}}}},
        ]
        # Platform administration stays locked; personal models and fixed presets are allowed.
        patch += [{"id":name,"disabled":True} for name in (
            "client-hmr","cordis-client-runner","ui-cordis",
            "ui-settings-plugin-inventory","ui-settings-plugins","ui-permission",
            "ui-skill","ui-reference","ui-subagent","ui-jobs","ui-goal","ui-plan",
            "ui-message-feedback","ui-sidebar-files","ui-deliverables")]
        (config/"patch.yml").write_text(json.dumps(patch))
        from .gateway import bridge_app
        self.bridge=PrivateSocketServer(uvicorn.Config(bridge_app(self),uds=str(self.root/"bridge/io.sock"),
                         log_level="error",access_log=False,lifespan="off",timeout_graceful_shutdown=3))
        self.task=asyncio.create_task(self.bridge.serve())
        for _ in range(50):
            if self.bridge.started: break
            await asyncio.sleep(.05)
        if not self.bridge.started: raise HTTPException(503,"个人 AI 工具通道启动失败")
        os.chmod(self.root/"bridge/io.sock",0o666)
        from .recipes import personal
        args=personal(self.manager.root,self.manager.config.harness,self.manager.config.node,ROOT,self.key)
        await docker(*args)
        self.client=httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(self.socket)),
                                    base_url="http://runtime",timeout=30)
        deadline=time.monotonic()+120
        for attempt in range(240):
            if time.monotonic()>=deadline:break
            if self.stopped: raise HTTPException(503,"个人 AI 启动已取消")
            self.validate()
            if attempt%10==0 and await docker("inspect","--format","{{.State.Running}}",self.name)!="true":
                raise HTTPException(503,"个人 AI 进程未能启动，请联系管理员检查实例日志")
            try:
                response=await self.client.get("/__ready",timeout=2)
                if response.status_code==200:
                    self.ready=True
                    return
            except httpx.HTTPError: pass
            await asyncio.sleep(.5)
        raise HTTPException(503,"个人 AI 启动超时，请重试")

    async def stop(self):
        async with self.stop_lock:
            if self.cleaned: return
            await self._stop()

    async def _stop(self):
        self.stopped=True
        for ws in list(self.sockets):
            try: await ws.close(code=1008)
            except Exception: pass
        try:
            info=json.loads(await docker("inspect",self.name))[0]
            if (info["Config"].get("Labels",{}).get(LABEL)=="true" and
                any(m["Source"]==str(self.root/"home") and m["Destination"]=="/home/assistant" for m in info["Mounts"])):
                await docker("rm","-f",self.name)
            else:
                raise HTTPException(503,"个人 AI 容器归属不匹配，保留名额等待检查")
        except HTTPException:
            # An inspect error is not proof that the container is gone.
            remaining=await docker("ps","-aq","--filter","name=^/"+self.name+"$")
            if remaining: raise
        if self.client: await self.client.aclose()
        if self.bridge:
            self.bridge.should_exit=True
            if self.task:
                try: await asyncio.wait_for(self.task,5)
                except (TimeoutError,asyncio.CancelledError):
                    self.task.cancel()
        self.cleaned=True

    @asynccontextmanager
    async def hold(self, touch=False):
        # Ingress and idle retirement use the same per-instance gate.
        async with self.guard:
            if self.retiring or self.stopped:
                raise HTTPException(409,"个人 AI 已回收，请重新打开")
            self.active += 1
            if touch: self.last=time.monotonic(); self.idle_since=None
        try:
            yield self
        finally:
            async with self.guard:
                self.active -= 1
                if touch: self.last=time.monotonic(); self.idle_since=None


# Preserve the original import surface for callers and deployment checks.
from .pool import Manager
