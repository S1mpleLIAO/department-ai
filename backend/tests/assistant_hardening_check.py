"""Focused source compatibility, storage retention and privileged-launcher checks."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from app.features.assistant import compatibility as compat, storage, recipes

ROOT=Path(__file__).resolve().parents[2]
def expect_error(fn,types):
    try:fn()
    except types:return
    raise AssertionError("Unexpected authorization success")

def main():
    h=Path("/root/liao/DepartmentKnowledgeBase/deepseek-harness")
    assert compat.verify(h)["passed"]
    from identity_server import serve
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(("127.0.0.1",0));listener.listen()
        port=listener.getsockname()[1]
        with patch("identity_server.subprocess.Popen",side_effect=AssertionError("must not spawn on occupied port")):
            expect_error(lambda:serve({"app_port":port,"gateway_ports":[],"ai_enabled":False}),OSError)
    with TemporaryDirectory() as tmp:
        base=Path(tmp); fake=base/"h";fake.mkdir()
        for name in ("package.json","apps/cli/package.json","apps/web/package.json"):
            p=fake/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"version":"0.1.5-rc.1"}')
        p=fake/"packages/api/sample/src/index.ts";p.parent.mkdir(parents=True);p.write_text("interface X {}")
        baseline=base/"baseline.json";baseline.write_text(json.dumps(compat.snapshot(fake)))
        assert compat.verify(fake,baseline)["passed"]
        (fake/"package.json").write_text('{"version":"0.2.2-alpha.2"}')
        expect_error(lambda:compat.verify(fake,baseline),RuntimeError)
        (fake/"package.json").write_text('{"version":"0.1.5-rc.1"}')
        p.write_text("changed api");expect_error(lambda:compat.verify(fake,baseline),RuntimeError)
        p.unlink();expect_error(lambda:compat.verify(fake,baseline),RuntimeError)
        state=base/"state";state.mkdir();uid=str(uuid4())
        for space in ("zkxk","senyuan"):
            folder=state/(uid+"-"+space)/"home/workspace";folder.mkdir(parents=True)
            (folder/"keep.txt").write_text("x"*30)
        r=SimpleNamespace(user=uid,manager=SimpleNamespace(root=state))
        with patch.object(storage,"limits",return_value={"bytes":64,"files":10,"free":0}):
            assert storage.report(state)["users"][uid]["bytes"]==60
            expect_error(lambda:storage.check(r,5),HTTPException)
            assert storage.check(r,4)
        with patch.object(storage,"limits",return_value={"bytes":1024,"files":10,"free":100}), patch.object(storage.shutil,"disk_usage",return_value=SimpleNamespace(free=99)):
            expect_error(lambda:storage.check(r),HTTPException)
        with patch.object(storage,"limits",return_value={"bytes":1024,"files":2,"free":0}):
            expect_error(lambda:storage.check(r,files=1),HTTPException)
        stage=state/(uid+"-zkxk")/"reimbursement-12345678";stage.mkdir()
        (stage/"input").mkdir()
        marker=stage/"input/.department-disposable.json"
        marker.write_text(json.dumps({"kind":"reimbursement-stage","version":1}))
        os.utime(marker,(1,1))
        assert storage.cleanup_candidates(state,["busy"],now=100000)==[]
        assert storage.cleanup_candidates(state,[],now=100000)==[stage]
        (stage/"link").symlink_to("/etc/passwd")
        assert storage.cleanup_candidates(state,[],now=100000)==[]
        assert (state/(uid+"-zkxk")/"home/workspace/keep.txt").read_text()=="x"*30
        async def locking():
            events=[]
            async def first():
                async with storage.admission(r):
                    events.append("first-in");await asyncio.sleep(.2);events.append("first-out")
            async def second():
                await asyncio.sleep(.05)
                async with storage.admission(r):events.append("second-in")
            with patch.object(storage,"check",return_value={}):
                await asyncio.gather(first(),second())
            assert events==["first-in","first-out","second-in"],events
        asyncio.run(locking())
        # Import the root-owned-launcher source with its fixed recipe dependency.
        launchdir=base/"launcher";launchdir.mkdir()
        shutil.copyfile(ROOT/"deploy/identity/container-launcher.py",launchdir/"launcher.py")
        shutil.copyfile(ROOT/"backend/app/features/assistant/recipes.py",launchdir/"recipes.py")
        spec=importlib.util.spec_from_file_location("launcher_test",launchdir/"launcher.py")
        launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
        c={"root":str(state),"checkout":str(ROOT),"harness":str(h),"node":"/usr/local/lib/nodejs/node-v22.22.3-linux-x64/bin/node"}
        key=uid+"-zkxk";args=recipes.personal(c["root"],c["harness"],c["node"],c["checkout"],key)
        assert launcher.validate(args,c)=="run"
        bads=[["exec","production","sh"],["rm","-f","department-ai"],["image","pull",recipes.IMAGE],
              args+["--privileged"],[x.replace("src="+str(state/key/"home"),"src=/") for x in args],
              [x.replace("none","host") for x in args]]
        for bad in bads:expect_error(lambda:launcher.validate(bad,c),ValueError)
        bind=state/key/"home"
        launcher.validate_binds(args,state)
        (state/key).chmod(0o770)
        expect_error(lambda:launcher.validate_binds(args,state),ValueError)
        (state/key).chmod(0o750)
        bind.rename(state/key/"kept-home")
        bind.symlink_to("/etc")
        expect_error(lambda:launcher.validate_binds(args,state),ValueError)

    print("PASS compatibility version/source/removal rejection; cross-space quota and retention; safe temporary candidates; Docker fixed-recipe allowlist")

if __name__=="__main__":main()
