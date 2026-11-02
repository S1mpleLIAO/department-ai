"""Pinned dsh-v0.1.5-rc.1 wire allowlist. Never forward arbitrary plugin RPCs."""
from pathlib import PurePosixPath
from .personal_models import PRESETS, NAMESPACES, provider, credential, settings_ops, public_url
from fastapi import HTTPException

WORKSPACE="/home/assistant/workspace"
PERSONAL_SETTINGS={"locale","agent-default-model","ui-theme","ui-chat","ui-conversation"}|NAMESPACES
READ={"session/list","session/search","session/page","session/modelCatalog",
      "session/canOpenWorkspacePath","session/attachment","agentPresets/list","settings/describe","commands/list"}
WRITE={"session/create","session/rename","session/prompt","session/cancel","session/fork","session/updateQueue",
       "workspace/rename","workspace/archiveSession","workspace/insertBefore","workspace/insertSessionBefore"}
STREAMS={"$events","session/follow","session/control","workspace/follow"}


def deny():
    raise HTTPException(403,"此 Harness 操作未获授权，请使用部门系统管理入口")


def workspace_path(value):
    """Accept canonical paths inside the personal container workspace only."""
    if not isinstance(value,str) or "\\" in value or any(ord(c)<32 or ord(c)==127 for c in value):
        deny()
    try:
        if len(value.encode("utf-8"))>4096: deny()
    except UnicodeError:
        deny()
    if ".." in value.split("/") or "." in value.split("/"): deny()
    path=PurePosixPath(value)
    if not path.is_relative_to(WORKSPACE): deny()
    return str(path)


def validate_workspace_directory(root, method, body):
    """Map container paths to this authenticated runtime; refuse symlink escapes."""
    args=body["payload"]["args"]
    if method in ("directoryPicker/list","directoryPicker/createDirectory"):
        path=args["path"]
    elif method in ("workspace/create","session/create"):
        path=args["request"].get("path" if method=="workspace/create" else "cwd",WORKSPACE)
    else:
        return
    base=root/"home/workspace"
    candidate=base/PurePosixPath(workspace_path(path)).relative_to(WORKSPACE)
    try:
        if candidate.resolve()!=candidate: deny()
    except (OSError,RuntimeError):
        deny()


def rpc(method, body, models):
    if not isinstance(body,dict) or body.get("type")!="client-request" or body.get("method")!=method:
        deny()
    payload=body.get("payload")
    args=payload.get("args") if isinstance(payload,dict) else None
    if not isinstance(args,dict): deny()
    if method=="$events/result":
        # Native approvals/questions settle only an event delivered to this private instance's client.
        # The pinned Harness host validates clientId/eventId and ignores unknown or settled deliveries.
        if set(args)!={"clientId","eventId","outcome"}:deny()
        if any(not isinstance(args[k],str) or not 1<=len(args[k])<=160 for k in ("clientId","eventId")):deny()
        outcome=args["outcome"]
        if not isinstance(outcome,dict) or outcome.get("kind") not in ("next","result","rejected"):deny()
        return body
    if method in {"llm/listProviders","llm/listConfigurableProviders"}:return body
    if method=="credentials/describe":
        refs=args.get("refs")
        if not isinstance(refs,list) or len(refs)>256 or not all(isinstance(r,str) and len(r)<=128 for r in refs):deny()
        return body
    if method in {"credentials/set","credentials/unset"}:
        if not credential(args.get("ref")):deny()
        if method.endswith("/set") and (not isinstance(args.get("value"),str) or not 1<=len(args["value"])<=8192):deny()
        return body
    if method=="llm/discoverModels":
        req=args.get("request",{})
        if args.get("settingsNs")!="llm-pi-ai" or not isinstance(req,dict):deny()
        if req.get("provider") is not None and not provider(req["provider"]):deny()
        if "baseURL" in req:public_url(req["baseURL"])
        return body
    if method=="commands/execute":
        # Restore only manual context compaction, never /permission or arbitrary plugin commands.
        if set(args)!={"agentId","line","submittedAttachments"} or not isinstance(args["agentId"],str) or not args["agentId"] or args["line"]!="/compact" or args["submittedAttachments"]!=[]:deny()
        return body
    if method=="agentPresets/select":
        if set(args)!={"agentId","agentPreset"} or not isinstance(args["agentId"],str) or args["agentPreset"] not in PRESETS:deny()
        return body
    if method=="agentPresets/read":
        if args.get("id") not in PRESETS:deny()
        return body
    if method=="settings/canOpenAgentPresetDirectory":return body
    if method=="settings/mutate" and args.get("ns")=="llm-pi-ai":
        settings_ops(args);return body
    if method in READ|WRITE:
        if method in ("session/prompt","session/fork","session/updateQueue"):
            req=args.get("request")
            if not isinstance(req,dict) or not isinstance(req.get("sessionId"),str):deny()
        if method=="session/create":
            req=args.get("request")
            # Native create can adopt an existing caller-chosen ID; forbid this to protect stale-context epochs.
            if not isinstance(req,dict) or set(req)-{"cwd","agentPreset","workspaceId"}: deny()
            if req.get("agentPreset","department") not in PRESETS: deny()
            if "cwd" in req: req["cwd"]=workspace_path(req["cwd"])
            elif not req.get("workspaceId"): req["cwd"]=WORKSPACE
        return body
    if method=="workspace/create":
        req=args.get("request")
        if not isinstance(req,dict) or set(req)!={"path"}: deny()
        req["path"]=workspace_path(req["path"])
        return body
    if method=="directoryPicker/list":
        if set(args)-{"path"}: deny()
        args["path"]=workspace_path(WORKSPACE if args.get("path") is None else args["path"])
        return body
    if method=="directoryPicker/createDirectory":
        if set(args)!={"path","name"}: deny()
        args["path"]=workspace_path(args["path"])
        name=args["name"]
        if not isinstance(name,str) or not name.strip() or name in (".","..") or any(
                c in "/\\" or ord(c)<32 or ord(c)==127 for c in name): deny()
        try:
            if len(name.encode("utf-8"))>255: deny()
        except UnicodeError:
            deny()
        return body
    if method=="session/selectModel":
        req=args.get("request",{})
        if not isinstance(req,dict):deny()
        if not (req.get("provider")=="department" and req.get("model") in models or provider(req.get("provider")) and isinstance(req.get("model"),str) and 0<len(req["model"])<=256):deny()
        if req.get("reasoningEffort") not in (None,"off","minimal","low","medium","high","xhigh","max"):deny()
        return body
    if method=="settings/mutate":
        # Native preference controls use scalar path operations, not the legacy update RPC.
        ops=args.get("ops")
        if set(args)-{"ns","ops","expectedRevision"} or not isinstance(ops,list) or not 1<=len(ops)<=4:deny()
        revision=args.get("expectedRevision")
        if revision is not None and (type(revision) is not int or revision<0):deny()
        patch={}
        for op in ops:
            if not isinstance(op,dict) or set(op)!={"op","path","value"} or op["op"]!="set":deny()
            path=op["path"]
            if not isinstance(path,list) or len(path)!=1 or not isinstance(path[0],str) or path[0] in patch:deny()
            patch[path[0]]=op["value"]
        rpc("settings/update",{"type":"client-request","method":"settings/update",
                              "payload":{"args":{"ns":args.get("ns"),"patch":patch}}},models)
        return body
    if method=="settings/update":
        ns,patch=args.get("ns"),args.get("patch")
        if not isinstance(ns,str):deny()
        if ns=="agent-presets" and isinstance(patch,dict) and set(patch)=={"default"} and patch["default"] in PRESETS:return body
        if ns=="ui-onboarding" and isinstance(patch,dict) and patch=={"welcomeNoticeVersion":"2026-08-13.1"}:return body
        if ns=="locale" and isinstance(patch,dict) and set(patch)=={"preference"} and patch["preference"] in ("zh","en","system"):
            return body
        if ns=="ui-theme" and isinstance(patch,dict) and patch and set(patch)<={"preference","fontSize"}:
            if patch.get("preference","system") not in ("light","dark","system"):deny()
            size=patch.get("fontSize",14)
            if type(size) is not int or not 12<=size<=17:deny()
            return body
        fields={"ui-chat":("transcriptView",("normal","compact")),"ui-conversation":("busyEnter",("queue","steer"))}
        if ns in fields and isinstance(patch,dict):
            field,values=fields[ns]
            if set(patch)=={field} and patch[field] in values:return body
        if ns=="agent-default-model" and isinstance(patch,dict) and set(patch)<= {"provider","model"} and ((patch.get("provider")=="department" and patch.get("model") in models) or (provider(patch.get("provider")) and isinstance(patch.get("model"),str) and 0<len(patch["model"])<=256)):
            return body
        deny()
    deny()


def frame(value):
    if not isinstance(value,dict): deny()
    if value.get("type")=="open":
        if value.get("endpoint") not in STREAMS or set(value)-{"type","streamId","endpoint","payload"}: deny()
        payload=value.get("payload")
        if not isinstance(payload,dict) or not isinstance(payload.get("args"),dict): deny()
    elif value.get("type") not in ("cancel","close"):
        deny()
    if not isinstance(value.get("streamId"),str) or len(value["streamId"])>128: deny()
    return value
