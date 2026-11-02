"""Opt-in real-provider smoke test; only the isolated synthetic fixture is sent."""
import asyncio
import json
from uuid import uuid4
import websockets
from assistant_live_check import STATE, AI, login, entry, rpc


def events(value):
    if isinstance(value,dict):
        if value.get("type") in ("assistant/message","assistant/attempt","tool/call","tool/result"):
            yield value
        else:
            for child in value.values():yield from events(child)
    elif isinstance(value,list):
        for child in value:yield from events(child)


async def main():
    fixture=json.loads((STATE/"assistant-fixture.json").read_text())
    department=await login(fixture["username"],fixture["password"])
    ai=None
    records=[]
    try:
        ai=await entry(department)
        session=(await rpc(ai,"session/create",{"request":{"cwd":"/home/assistant/workspace"}}))["sessionId"]
        await rpc(ai,"session/rename",{"request":{"sessionId":session,"title":"真实模型与已发布技能验收"}})
        cookie="; ".join(k+"="+v for k,v in ai.cookies.items())
        async with websockets.connect("ws://127.0.0.1:3182/api/remote.mux",origin=AI,additional_headers={"Cookie":cookie}) as ws:
            await ws.send(json.dumps({"type":"open","streamId":"real","endpoint":"session/follow",
                "payload":{"args":{"request":{"address":{"kind":"session","sessionId":session}}}}}))
            await asyncio.wait_for(ws.recv(),15)
            await rpc(ai,"session/prompt",{"request":{"sessionId":session,"requestId":str(uuid4()),"mode":"queue",
                "content":[{"type":"text","text":"这是合成数据验收。请调用 department_skill_list 查询当前可用技能，再调用 department_skill_get 读取其中第一项的完整说明。最后用中文列出该技能的 ID 和一句概述。不要执行技能、不要生成文件或调用其他工具。"}]}})
            async with asyncio.timeout(150):
                while True:
                    records.extend(events(json.loads(await ws.recv())))
                    calls={e.get("data",{}).get("name") for e in records if e["type"]=="tool/call"}
                    answers=[e for e in records if e["type"]=="assistant/message"]
                    results=[e for e in records if e["type"]=="tool/result"]
                    if ({"department_skill_list","department_skill_get"}<=calls and len(results)>=2 and answers
                        and answers[-1]["seq"]>results[-1]["seq"]
                        and fixture["approvedSkill"] in json.dumps(answers[-1],ensure_ascii=False)):
                        break
            serialized=json.dumps(records,ensure_ascii=False)
            assert fixture["foreignSkill"] not in serialized and fixture["pendingSkill"] not in serialized
            print("PASS real model: native Harness login, streaming reply, published skill list/read, excluded foreign and pending skills",flush=True)
        result={"passed":True,"sessionId":session,"modelMode":"real","events":records}
        output=STATE/"assistant-real-model-results.json"
        output.write_text(json.dumps(result,ensure_ascii=False));output.chmod(0o600)
    except BaseException:
        output=STATE/"assistant-real-model-failure.json"
        with output.open("w") as handle:json.dump(records,handle,ensure_ascii=False)
        output.chmod(0o600)
        raise
    finally:
        if ai:await ai.aclose()
        await department.post("/api/auth/logout")
        await department.aclose()


if __name__=="__main__":asyncio.run(main())
