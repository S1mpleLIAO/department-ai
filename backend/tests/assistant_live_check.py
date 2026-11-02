"""Real loopback gateway, two private Harness containers and deterministic model."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4
import httpx
import websockets
from psycopg.types.json import Jsonb
from app.core.database import create_pool
from app.features.identity.service import HASHER

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/".identity-state"
ORIGIN="http://127.0.0.1:3181"
AI="http://127.0.0.1:3182"
checks=[]
def check(name,condition=True):
    assert condition,name
    checks.append(name);print("PASS",name,flush=True)

async def login(name,password):
    c=httpx.AsyncClient(base_url=ORIGIN,timeout=150)
    r=await c.post("/api/auth/login",json={"username":name,"password":password},headers={"Origin":ORIGIN})
    assert r.status_code==200,r.text
    c.headers.update({"Origin":ORIGIN,"X-CSRF-Token":r.json()["csrfToken"]})
    return c

async def entry(c,space="zkxk",origin=AI):
    r=await c.post("/api/assistant/entry",headers={"X-Department-Space":space})
    assert r.status_code==200,r.text
    ai=httpx.AsyncClient(base_url=origin,timeout=150,headers={"Origin":origin})
    r=await ai.post("/bootstrap",data={"ticket":r.json()["ticket"]},headers={"Origin":ORIGIN})
    assert r.status_code==303,r.text
    assert "dsh-auth" not in r.headers.get("set-cookie","")
    for attempt in range(150):
        r=await ai.post("/ready")
        if r.status_code==200:break
        assert r.status_code==202,r.text
        await asyncio.sleep(1)
    assert r.status_code==200,r.text
    return ai

async def rpc(ai,name,args):
    r=await ai.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),
        "method":name,"payload":{"args":args}})
    assert r.status_code==200,(name,r.status_code,r.text[:300])
    result=r.json()["result"]
    assert result["ok"],result
    return result.get("value")

async def main():
    config=json.loads((STATE/"credentials.json").read_text())
    assert "@127.0.0.1:15433/identity_test" in config["appDsn"]
    fixture=json.loads((STATE/"assistant-fixture.json").read_text())
    pool=create_pool(config["appDsn"]);pool.open(wait=True)
    uid=str(uuid4());username="isolate-"+uid[:8];password="Synthetic-personal-123"
    with pool.connection() as conn:
        conn.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'隔离对照用户',%s,'zkxk',false)",
                     (uid,username,HASHER.hash(password)))
        conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,fixture["groupId"]))
        conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'shared',%s) ON CONFLICT DO NOTHING",
                     (fixture["userId"],fixture["groupId"]))
    clients=[]
    try:
        a=await login(fixture["username"],fixture["password"]);clients.append(a)
        aa=await entry(a);clients.append(aa)
        check("department login automatically opens native Harness without URL token",(await aa.get("/")).status_code==200)
        session=(await rpc(aa,"session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
        await rpc(aa,"settings/update",{"ns":"locale","patch":{"preference":"zh"}})
        cookie="; ".join(k+"="+v for k,v in aa.cookies.items())
        async with websockets.connect("ws://127.0.0.1:3182/api/remote.mux",origin=AI,additional_headers={"Cookie":cookie}) as ws:
            await ws.send(json.dumps({"type":"open","streamId":"history","endpoint":"session/follow",
                "payload":{"args":{"request":{"address":{"kind":"session","sessionId":session},"assistantStream":True}}}}))
            first=json.loads(await asyncio.wait_for(ws.recv(),15));assert first["type"]=="item",first
            await rpc(aa,"session/prompt",{"request":{"sessionId":session,"requestId":str(uuid4()),"mode":"queue",
                "content":[{"type":"text","text":"请列出当前允许使用的已发布技能。"}]}})
            observed=""
            async with asyncio.timeout(90):
                while True:
                    observed+=await ws.recv()
                    if "已按当前权限读取已发布技能" in observed and fixture["approvedSkill"] in observed:break
            check("native chat calls authorized department tool through isolated model bridge",
                  fixture["foreignSkill"] not in observed and fixture["pendingSkill"] not in observed)
        # File route serves only a regular file below this user's workspace.
        workspace=Path(fixture["runtimeRoot"])/"home/workspace"
        (workspace/"proof.txt").write_text("private synthetic output")
        link=workspace/"escape.txt"
        if not link.exists():link.symlink_to("/etc/passwd")
        r=await aa.get("/api/file",params={"path":"/home/assistant/workspace/proof.txt"})
        check("own output download works",r.status_code==200 and r.text=="private synthetic output")
        for path in ("/etc/passwd","/home/assistant/workspace/escape.txt","/home/assistant/dsh/cordis.yml"):
            assert (await aa.get("/api/file",params={"path":path})).status_code>=400
        check("outside-workspace and symlink downloads are rejected")
        b=await login(username,password);clients.append(b)
        bb=await entry(b);clients.append(bb)
        rows=await rpc(bb,"session/list",{"_request":{}})
        check("second user cannot list first user's sessions",session not in json.dumps(rows))
        desc=await rpc(bb,"settings/describe",{})
        locale=next(n for n in desc["namespaces"] if n["ns"]=="locale")
        check("second user's preferences are independent",'"zh"' not in json.dumps(locale.get("value",locale.get("config",{}))))
        cookie_b="; ".join(k+"="+v for k,v in bb.cookies.items())
        async with websockets.connect("ws://127.0.0.1:3182/api/remote.mux",origin=AI,additional_headers={"Cookie":cookie_b}) as ws:
            await ws.send(json.dumps({"type":"open","streamId":"foreign","endpoint":"session/follow",
                "payload":{"args":{"request":{"address":{"kind":"session","sessionId":session}}}}}))
            result=json.loads(await asyncio.wait_for(ws.recv(),15))
            check("guessed foreign session ID is unreadable",result["type"]=="error")
        await b.post("/api/auth/logout")
        check("logout revokes existing AI cookie",(await bb.get("/starting")).status_code==401)
        await asyncio.sleep(4)
        shared=await entry(a,"shared","http://127.0.0.1:3184");clients.append(shared)
        check("same user's other space has separate session history",session not in json.dumps(await rpc(shared,"session/list",{"_request":{}})))
        # Revoke the original department session with an active mux connection.
        async with websockets.connect("ws://127.0.0.1:3182/api/remote.mux",origin=AI,additional_headers={"Cookie":cookie}) as ws:
            await ws.send(json.dumps({"type":"open","streamId":"events","endpoint":"$events","payload":{"args":{}}}))
            await a.post("/api/auth/logout")
            async with asyncio.timeout(12):
                try:
                    while True:await ws.recv()
                except websockets.exceptions.ConnectionClosed:pass
            check("logout closes an already connected websocket")
        check("logout revokes every space's AI cookie",(await shared.get("/starting")).status_code==401)
    finally:
        for c in clients:
            if str(c.base_url).rstrip("/")==ORIGIN:
                await c.post("/api/auth/logout")
            await c.aclose()
        pool.close()
        (STATE/"assistant-live-results.json").write_text(json.dumps(checks,ensure_ascii=False))

if __name__=="__main__":asyncio.run(main())
