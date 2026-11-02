"""Personal directory RPC boundaries; no network, database or model calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import HTTPException
from app.features.assistant.policy import rpc, WORKSPACE
def call(method,args):
 return rpc(method,{"type":"client-request","method":method,"payload":{"args":args}},["test"])
def denied(method,args):
 try:call(method,args)
 except HTTPException as e:assert e.status_code==403
 else:raise AssertionError((method,args))
child=WORKSPACE+"/项目 liao"
call("directoryPicker/createDirectory",{"path":WORKSPACE,"name":"项目 liao"})
call("directoryPicker/list",{"path":child})
call("workspace/create",{"request":{"path":child}})
call("session/create",{"request":{"cwd":child}})
for path in ("/etc","/home/assistant","/root/liao",WORKSPACE+"-other",WORKSPACE+"/../dsh",WORKSPACE+"/a/../../b","relative",WORKSPACE+"/x\\y",WORKSPACE+"/x\0",42):
 for method,args in (
  ("directoryPicker/createDirectory",{"path":path,"name":"child"}),
  ("directoryPicker/list",{"path":path}),
  ("workspace/create",{"request":{"path":path}}),
  ("session/create",{"request":{"cwd":path}})):
  denied(method,args)
for name in (""," ",".","..","../other","a/b","a\\b","x\0","x\n",None,42,"中"*100):
 denied("directoryPicker/createDirectory",{"path":WORKSPACE,"name":name})
denied("directoryPicker/createDirectory",{"path":WORKSPACE,"name":"ok","recursive":True})
denied("workspace/create",{"request":{"path":child,"command":"unsafe"}})
denied("session/create",{"request":{"cwd":child,"sessionId":"existing"}})
denied("settings/update",{"ns":"permission","patch":{"mode":"full"}})
print("directory policy: create/list/workspace/session paths and invalid names passed")


from app.features.assistant.policy import validate_workspace_directory
with TemporaryDirectory() as folder:
    root=Path(folder)
    base=root/"home/workspace";base.mkdir(parents=True)
    (base/"项目 liao").mkdir()
    outside=root/"private";outside.mkdir()
    (base/"escape").symlink_to(outside,target_is_directory=True)
    (base/"inside-link").symlink_to(base/"项目 liao",target_is_directory=True)
    for method,args in (
        ("directoryPicker/createDirectory",{"path":child,"name":"nested"}),
        ("directoryPicker/list",{"path":child}),
        ("workspace/create",{"request":{"path":child}}),
        ("session/create",{"request":{"cwd":child}})):
        validate_workspace_directory(root,method,call(method,args))
    for name in ("escape","inside-link"):
        for method,args in (
            ("directoryPicker/createDirectory",{"path":WORKSPACE+"/"+name,"name":"nested"}),
            ("directoryPicker/list",{"path":WORKSPACE+"/"+name}),
            ("workspace/create",{"request":{"path":WORKSPACE+"/"+name}}),
            ("session/create",{"request":{"cwd":WORKSPACE+"/"+name}})):
            try:validate_workspace_directory(root,method,call(method,args))
            except HTTPException as e:assert e.status_code==403
            else:raise AssertionError("symbolic link accepted")
print("directory filesystem boundary: own paths accepted; external and internal symlinks denied")

for bad in (WORKSPACE+"/" + chr(0xd800), WORKSPACE+"/" + "x"*4097):
    denied("directoryPicker/list",{"path":bad})
print("malformed and oversized paths denied")
