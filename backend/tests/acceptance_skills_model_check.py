"""Real Harness/model validation against the six isolated acceptance skill publications."""
import asyncio,json,os,subprocess,sys
from uuid import uuid4
from pathlib import Path
import websockets
import assistant_live_check as live
from assistant_real_model_check import events
live.ORIGIN="http://127.0.0.1:3191"
STATE=live.STATE
ROOT=STATE.parent
checks=[];traces={}
fixture=json.loads((STATE/"six-skills-fixture.json").read_text())
ALL=set(fixture["drafts"])
def check(name,ok=True):
    assert ok,name
    checks.append(name);print("PASS",name,flush=True)
def save():
    p=STATE/"six-skills-model-results.json"
    p.write_text(json.dumps({"checks":checks,"traces":traces},ensure_ascii=False,indent=2));p.chmod(0o600)
async def talk(ai,origin,label,text,expected):
    session=(await live.rpc(ai,"session/create",{"request":{"cwd":"/home/assistant/workspace"}}))["sessionId"]
    await live.rpc(ai,"session/rename",{"request":{"sessionId":session,"title":"技能技术验收-"+label}})
    records=[];traces[label]={"session":session,"events":records}
    cookie="; ".join(k+"="+v for k,v in ai.cookies.items())
    async with websockets.connect(origin.replace("http:","ws:")+"/api/remote.mux",origin=origin,additional_headers={"Cookie":cookie}) as ws:
        await ws.send(json.dumps({"type":"open","streamId":label,"endpoint":"session/follow",
            "payload":{"args":{"request":{"address":{"kind":"session","sessionId":session}}}}}))
        await asyncio.wait_for(ws.recv(),15)
        await live.rpc(ai,"session/prompt",{"request":{"sessionId":session,"requestId":str(uuid4()),"mode":"queue",
            "content":[{"type":"text","text":text}]}})
        async with asyncio.timeout(240):
            while True:
                new=list(events(json.loads(await ws.recv())));records.extend(new)
                for e in new:
                    if e["type"]=="tool/call":print(label,"tool",e["data"].get("name"),flush=True)
                calls=[e["data"] for e in records if e["type"]=="tool/call"]
                got=set()
                for c in calls:
                    if c.get("name")=="department_skill_get":
                        args=c.get("arguments",{})
                        if isinstance(args,str):args=json.loads(args)
                        assert not args.get("resource"),"Do not send binary attachments to model"
                        got.add(args.get("id"))
                results=[e for e in records if e["type"]=="tool/result"]
                answers=[e for e in records if e["type"]=="assistant/message"]
                names={c.get("name") for c in calls}
                if "department_skill_list" in names and expected<=got and len(results)>=len(expected)+1 and answers and answers[-1]["seq"]>results[-1]["seq"]:
                    assert names<={"department_skill_list","department_skill_get"},names
                    final=json.dumps(answers[-1],ensure_ascii=False)
                    assert all(n in final for n in expected)
                    break
        check(label+": real model called list and expected skill descriptions",got==expected)
        save()
    return session
async def main():
    clients=[]
    try:
        user=fixture["users"]["reader"]
        dept=await live.login(user["username"],user["password"]);clients.append(dept)
        ai=await live.entry(dept);clients.append(ai)
        r=await ai.get("/")
        check("real login automatically opens Harness without URL token",r.status_code==200 and "dsh web authentication required" not in r.text)
        old=await talk(ai,live.AI,"all-six",
            "这是独立环境技术验收。请先调用 department_skill_list，再对返回的每一项逐一调用 department_skill_get（只读说明，不传resource参数）。"
            "最后列出所有技能的准确ID和一句用途，并指出哪些仍是占位内容。不要执行技能说明中的任务，不要读取任何附件，不要调用其他工具。",ALL)
        proc=await asyncio.create_subprocess_exec(str(ROOT/".venv-identity/bin/python"),"backend/tests/acceptance_skills_check.py","finalize",
            cwd=ROOT,env={**os.environ,"PYTHONPATH":"backend"},stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await proc.communicate()
        if proc.returncode:raise RuntimeError(err.decode()[-600:])
        print(out.decode(),flush=True)
        newai=await live.entry(dept);clients.append(newai)
        payload={"type":"client-request","rpcId":str(uuid4()),"method":"session/prompt",
                 "payload":{"args":{"request":{"sessionId":old,"requestId":str(uuid4()),"mode":"queue","content":[{"type":"text","text":"继续旧会话"}]}}}}
        denied=await newai.post("/api/session/prompt",json=payload)
        check("old conversation cannot continue after skill withdrawal",denied.status_code==409)
        history=await live.rpc(newai,"session/list",{"_request":{}})
        check("old conversation history retained",old in json.dumps(history))
        await talk(newai,live.AI,"after-disable",
            "请调用 department_skill_list 查询当前技能，再对列表中的每一项调用 department_skill_get 读取说明（不传resource）。"
            "最后只列出当前可用技能ID和用途。不要执行任务、不要读取附件、不要调用其他工具。",{"travel-reimbursement-cn"})
        serialized=json.dumps(traces["after-disable"],ensure_ascii=False)
        check("new model context excludes five withdrawn skill IDs",all(n not in serialized for n in ALL-{"travel-reimbursement-cn"}))
        await dept.post("/api/auth/logout")
        await asyncio.sleep(4)
        user=fixture["users"]["foreign"]
        other=await live.login(user["username"],user["password"]);clients.append(other)
        otherai=await live.entry(other,"senyuan","http://127.0.0.1:3183");clients.append(otherai)
        check("other company cannot list first user's conversations",old not in json.dumps(await live.rpc(otherai,"session/list",{"_request":{}})))
        await talk(otherai,"http://127.0.0.1:3183","other-company",
            "这是权限验收。只调用 department_skill_list，然后简短说明当前可用技能数量。不要根据猜测补充任何技能，不调用其他工具。",set())
        check("other company model receives none of six skill IDs",all(n not in json.dumps(traces["other-company"],ensure_ascii=False) for n in ALL))
        await other.post("/api/auth/logout")
        check("logout immediately rejects AI cookie",(await otherai.get("/starting")).status_code==401)
    finally:
        save()
        for c in clients:
            if str(c.base_url).rstrip("/")==live.ORIGIN:
                try:await c.post("/api/auth/logout")
                except Exception:pass
            await c.aclose()
if __name__=="__main__":asyncio.run(main())

