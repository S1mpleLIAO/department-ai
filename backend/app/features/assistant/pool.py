"""Bounded FIFO admission; container starts never hold the admission lock."""
import asyncio
from contextlib import asynccontextmanager
import fcntl
import hashlib
import logging
import json
from types import SimpleNamespace
from uuid import UUID
import httpx
from pathlib import Path
import re
import time
from fastapi import HTTPException
from .auth import live_principal
from .config import runtime_config, pool_limits
from .activity import activity
from .runtime import Runtime, docker, LABEL

logger = logging.getLogger(__name__)

class Manager:
    def __init__(self, pool, models):
        self.config = runtime_config()
        self.limits = pool_limits()
        self.pool, self.models = pool, models
        self.root = self.config.root
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.namespace = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        (self.root / ".control").mkdir(mode=0o700,exist_ok=True)
        self.ownership = (self.root / ".control/supervisor.lock").open("a")
        try: fcntl.flock(self.ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.ownership.close()
            raise RuntimeError("Another AI supervisor already owns this state directory")
        self.items = {}
        self.pending = {}
        self.starting = {}
        self.failures = {}
        self.lock = asyncio.Lock()
        self.closed = False

    async def recover(self):
        """Reconcile only this owner's abandoned containers before accepting traffic."""
        names = (await docker("ps", "-a", "--format", "{{.Names}}",
                    "--filter", "label="+LABEL+"=true",
                    "--filter", "name=^/department-id-ai-"+self.namespace+"-")).splitlines()
        safe = []
        prefix = "department-id-ai-"+self.namespace+"-"
        for name in names:
            key = name.removeprefix(prefix)
            uid, separator, space = key.rpartition("-")
            try: valid = separator and str(UUID(uid)) == uid and space in ("zkxk","senyuan","shared")
            except ValueError: valid = False
            root = self.root/key
            if not name.startswith(prefix) or not valid or root.resolve() != root:
                raise RuntimeError("Abandoned AI instance ownership is invalid; recovery stopped")
            info = json.loads(await docker("inspect", name))[0]
            if (info["Config"].get("Labels",{}).get(LABEL)!="true" or
                not any(m["Source"]==str(root/"home") and m["Destination"]=="/home/assistant"
                        for m in info["Mounts"])):
                raise RuntimeError("Abandoned AI instance mount mismatch; recovery stopped")
            if info["State"]["Running"]:
                socket = root/"transport/web.sock"
                async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)),
                                             base_url="http://runtime",timeout=10) as client:
                    try: busy = any((await activity(SimpleNamespace(socket=socket,client=client))).values())
                    except Exception:
                        raise RuntimeError("Cannot confirm abandoned AI task state; instances preserved") from None
                    if busy:
                        raise RuntimeError("Abandoned AI still has running or queued tasks; instances preserved")
            safe.append(name)
        for name in safe:
            await docker("rm", "-f", name)
        return len(safe)

    def available_mib(self):
        return int(re.search(r"MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text())[1]) // 1024

    def check(self, p, space):
        if self.closed: raise HTTPException(503, "个人 AI 服务正在维护")
        return live_principal(self.pool, p.session_id, space)

    def _dispatch(self):
        # Called only under admission lock; all slow work belongs to background tasks.
        now = time.monotonic()
        for key, entry in list(self.pending.items()):
            if now - entry["seen"] > 120:
                self.pending.pop(key, None); continue
            try: self.check(entry["principal"], entry["space"])
            except HTTPException:
                self.pending.pop(key, None); continue
        while self.pending and len(self.items) < self.limits.capacity and not self.closed:
            if self.available_mib() < self.limits.min_available_mib + 640 * (1 + len(self.starting)):
                break
            key = next(iter(self.pending))
            entry = self.pending.pop(key)
            try:
                runtime = Runtime(self, entry["principal"], entry["space"])
            except Exception:
                self.failures[key] = "个人 AI 配置检查失败，请重新打开"
                continue
            self.items[key] = runtime
            self.starting[key] = asyncio.create_task(self._start(key, runtime))

    async def _start(self, key, runtime):
        try:
            await runtime.start()
            runtime.last = time.monotonic()
        except BaseException as error:
            runtime.retiring = True
            self.failures[key] = error.detail if isinstance(error, HTTPException) else "个人 AI 启动失败，请重试"
            try:
                await runtime.stop()
            except Exception:
                logger.exception("Startup cleanup failed; keep its capacity reserved")
            else:
                async with self.lock:
                    if self.items.get(key) is runtime: self.items.pop(key, None)
            if isinstance(error, asyncio.CancelledError): raise
        finally:
            async with self.lock:
                self.starting.pop(key, None)

    async def status(self, p, space, *, enqueue=True, retry=False):
        self.check(p, space)
        key = p.user_id + "-" + space
        async with self.lock:
            runtime = self.items.get(key)
            if runtime:
                runtime.validate()
                if runtime.session != p.session_id:
                    raise HTTPException(409, "另一登录正在使用此个人实例，请先结束原登录或稍后重试")
                state = "retiring" if runtime.retiring else ("ready" if runtime.ready else "starting")
                return {"ready": state == "ready", "state": state, "capacity": self.limits.capacity}
            if retry: self.failures.pop(key, None)
            if key in self.failures: raise HTTPException(503, self.failures[key])
            if enqueue:
                entry = self.pending.get(key)
                if entry and entry["principal"].session_id != p.session_id:
                    raise HTTPException(409, "另一登录已在排队")
                if not entry:
                    entry = {"principal": p, "space": space}
                    self.pending[key] = entry
                entry["seen"] = time.monotonic()
                self._dispatch()
                if key in self.items:
                    return {"ready": False, "state": "starting", "capacity": self.limits.capacity}
            position = list(self.pending).index(key) + 1 if key in self.pending else None
            return {"ready": False, "state": "queued" if position else "idle",
                    "position": position, "capacity": self.limits.capacity,
                    "reason": "capacity" if len(self.items) >= self.limits.capacity else "memory"}

    async def cancel(self, p, space):
        self.check(p, space)
        async with self.lock:
            key = p.user_id + "-" + space
            entry = self.pending.get(key)
            if entry and entry["principal"].session_id == p.session_id:
                self.pending.pop(key)
                return {"cancelled": True}
            return {"cancelled": False, "detail": "已开始启动或运行，无需取消；空闲后会自动回收"}

    async def get(self, p, space):
        # Internal callers can await readiness. HTTP /ready exposes nonblocking status.
        while True:
            status = await self.status(p, space)
            if status["ready"]: return self.items[p.user_id + "-" + space]
            await asyncio.sleep(.2)

    @asynccontextmanager
    async def lease(self, p, space, touch=True):
        runtime = await self.get(p, space)
        async with runtime.hold(touch=touch):
            runtime.validate()
            yield runtime

    async def _retire(self, key, runtime):
        # No admission lock while inspecting/stopping. The slot stays reserved.
        async with runtime.guard:
            if self.items.get(key) is not runtime or not runtime.ready: return
            if runtime.retiring:
                pass  # Retry a failed cleanup without admitting an extra container.
            else:
                try: runtime.validate()
                except HTTPException:
                    runtime.retiring = True  # Authorization revocation, not idle policy.
                else:
                    if runtime.active: runtime.idle_since = None; return
                    try: busy = any((await activity(runtime)).values())
                    except Exception:
                        runtime.idle_since = None
                        return  # Unknown task state is never proof of idleness.
                    now = time.monotonic()
                    if busy: runtime.idle_since = None; return
                    if runtime.idle_since is None: runtime.idle_since = now
                    if now - max(runtime.last, runtime.idle_since) < self.limits.idle_seconds: return
                    runtime.retiring = True
            await runtime.stop()
            async with self.lock:
                if self.items.get(key) is runtime: self.items.pop(key, None)

    async def reap_once(self):
        candidates = [(key, runtime) for key, runtime in self.items.items()
                      if key not in self.starting and (runtime.ready or runtime.retiring)]
        # Failed startup cleanup can be retried too.
        for key, runtime in candidates:
            if runtime.retiring and not runtime.ready: runtime.ready = True
        results = await asyncio.gather(*(self._retire(k, r) for k, r in candidates), return_exceptions=True)
        for error in results:
            if isinstance(error, BaseException): logger.warning("AI retirement deferred: %s", type(error).__name__)
        async with self.lock:
            self._dispatch()

    async def sweep(self):
        while True:
            await asyncio.sleep(2)
            try: await self.reap_once()
            except Exception: logger.exception("AI pool sweep failed; existing runtimes retained")

    async def close(self):
        self.closed = True
        self.pending.clear()
        tasks = list(self.starting.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            for runtime in list(self.items.values()): await runtime.stop()
            self.items.clear()
        finally: self.ownership.close()

