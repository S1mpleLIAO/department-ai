"""Fast scheduler regressions; fake containers, real admission and idle policy."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import time
from fastapi import HTTPException
from app.features.assistant.runtime import Manager, Runtime
from app.features.assistant.config import pool_limits
from app.features.assistant.activity import control_busy

checks=[]
def check(name, value=True):
    assert value, name
    checks.append(name); print("PASS "+name, flush=True)

class FakeRuntime:
    hold=Runtime.hold
    def __init__(self, manager, p, space):
        self.manager,self.session,self.space=manager,p.session_id,space
        self.key=p.user_id+"-"+space
        self.ready=self.stopped=self.retiring=False
        self.active=0;self.last=time.monotonic();self.idle_since=None
        self.guard=asyncio.Lock();self.gate=asyncio.Event()
        self.busy=False;self.unknown=False;self.fail=False;self.stop_fail=False
    def validate(self):
        if self.stopped: raise HTTPException(409,"stopped")
        if self.session in revoked:raise HTTPException(401,"revoked")
    async def start(self):
        await self.gate.wait()
        if self.fail:raise HTTPException(503,"synthetic failure")
        self.ready=True
    async def stop(self):
        if self.stop_fail: raise RuntimeError("synthetic cleanup error")
        self.stopped=True
async def activity(r):
    if r.unknown:raise TimeoutError()
    return {"running":r.busy}
revoked=set()
def principal(p,s,space):
    if s in revoked:raise HTTPException(401,"revoked")
def user(n):return SimpleNamespace(user_id=str(n),session_id=str(n))
async def main():
    with TemporaryDirectory() as folder,patch("app.features.assistant.pool.runtime_config",return_value=SimpleNamespace(root=Path(folder))),patch("app.features.assistant.pool.Runtime",FakeRuntime),patch("app.features.assistant.pool.live_principal",side_effect=principal),patch("app.features.assistant.pool.activity",side_effect=activity):
        m=Manager(None,["test"]);m.limits=replace(m.limits,capacity=1,idle_seconds=.01)
        m.available_mib=lambda:10000
        try:
            a,b,c=user(1),user(2),user(3)
            s=await m.status(a,"x");ar=m.items["1-x"]
            check("cold start reports starting without waiting",s["state"]=="starting" and not ar.ready)
            await m.status(b,"x");await m.status(b,"x");await m.status(c,"x")
            check("FIFO deduplicates one user",list(m.pending)==["2-x","3-x"] and (await m.status(c,"x"))["position"]==2)
            check("cancel only queued user",(await m.cancel(c,"x"))["cancelled"] and not (await m.cancel(a,"x"))["cancelled"])
            ar.gate.set();await asyncio.sleep(.02)
            ar.last=ar.idle_since=time.monotonic()-20;ar.busy=True
            await m.reap_once();check("running task never idle-stopped",not ar.stopped)
            ar.busy=False;ar.unknown=True;ar.idle_since=time.monotonic()-20
            await m.reap_once();check("unknown engine state is preserved",not ar.stopped and ar.idle_since is None)
            ar.unknown=False
            async with ar.hold():
                ar.last=ar.idle_since=time.monotonic()-20
                await m.reap_once();check("active ingress lease prevents stop",not ar.stopped)
            ar.last=ar.idle_since=time.monotonic()-20
            ar.stop_fail=True;await m.reap_once()
            check("failed cleanup keeps capacity reserved",m.items.get("1-x") is ar and "2-x" not in m.items)
            ar.stop_fail=False;await m.reap_once();br=m.items["2-x"]
            check("next user admitted only after cleanup",ar.stopped and len(m.items)==1 and not br.ready)
            br.gate.set();await asyncio.sleep(.02)
            m.limits=replace(m.limits,capacity=2)
            await m.status(c,"x");cr=m.items["3-x"]
            start=time.monotonic();check("warm access does not wait for another startup",(await m.status(b,"x"))["ready"] and time.monotonic()-start<.1)
            m.limits=replace(m.limits,capacity=1)
            await m.status(user(4),"x")
            check("lower capacity does not terminate existing tasks",len(m.items)==2 and not br.stopped)
            m.pending["4-x"]["seen"]-=121
            await m.reap_once();check("abandoned queue expires","4-x" not in m.pending)
            await m.status(user(5),"x");revoked.add("5")
            await m.reap_once();check("revoked queue removed before admission","5-x" not in m.pending)
            cr.fail=True;cr.gate.set();await asyncio.sleep(.03)
            try:await m.status(c,"x")
            except HTTPException as e:check("startup failure requires explicit retry",e.status_code==503)
            else:raise AssertionError("failure hidden")
            m.limits=replace(m.limits,capacity=2)
            await m.status(c,"x",retry=True)
            check("explicit retry creates a fresh startup","3-x" in m.items)
        finally:await m.close()
        m=Manager(None,["test"]);m.available_mib=lambda:1000
        try:
            check("low memory queues even with free slots",(await m.status(user(6),"x"))["reason"]=="memory" and not m.items)
        finally:await m.close()
    baseline={"type":"baseline","value":{"queues":{},"jobs":{"s":[{"status":"unknown"}]}}}
    check("nonterminal job prevents idle",control_busy({"items":[]},baseline)["jobs"])
    with patch.dict("os.environ",{"DEPARTMENT_AI_MAX_INSTANCES":"0"}):
        try:pool_limits()
        except RuntimeError:check("invalid capacity fails configuration")
        else:raise AssertionError("invalid config accepted")
    print(str(len(checks))+" scheduler checks passed")
if __name__=="__main__":asyncio.run(main())

