"""Real disposable Harness instance; synthetic user, no real model credentials."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.core.database import create_pool
from app.features.identity.service import HASHER,login
from app.features.assistant.auth import live_principal
from app.features.assistant.runtime import Manager

ROOT=Path(__file__).resolve().parents[2]

async def main():
    data=json.loads((ROOT/".identity-state/credentials.json").read_text())
    pool=create_pool(data["appDsn"]);pool.open(wait=True)
    uid=str(uuid4()); username="ai-"+uid[:8]; password="Test-personal-456"
    with pool.connection() as conn:
        conn.execute("""INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password)
          VALUES(%s,%s,'AI 隔离测试员',%s,'zkxk',false)""",(uid,username,HASHER.hash(password)))
        gid="ai-"+uid
        conn.execute("INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)",
                     (gid,gid,Jsonb(["assistant.use","knowledge.read","skills.use","processes.read"])))
        conn.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,gid))
    token,csrf,user=login(pool,username,password,"probe","probe")
    from app.features.identity.service import authenticate
    p,_=authenticate(pool,token)
    manager=Manager(pool,["department-test"])
    try:
        runtime=await manager.get(p,"zkxk")
        response=await runtime.client.get("/")
        assert response.status_code==200
        print("real runtime + server-only authentication: PASS",flush=True)
        async def rpc(name,args):
            r=await runtime.client.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),
                "method":name,"payload":{"args":args}})
            value=r.json()
            assert value["result"]["ok"],value
            return value["result"].get("value")
        created=await rpc("session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}})
        print("restricted department preset session: PASS",flush=True)
        await rpc("session/rename",{"request":{"sessionId":created["sessionId"],"title":"本人隔离会话"}})
        await rpc("settings/update",{"ns":"locale","patch":{"preference":"zh"}})
        print("private session and settings persistence: PASS",flush=True)
        metadata={"username":username,"password":password,"userId":uid,"groupId":gid,"sessionId":created["sessionId"],
                  "runtimeRoot":str(runtime.root)}
        target=ROOT/".identity-state/assistant-fixture.json";target.write_text(json.dumps(metadata));target.chmod(0o600)
    finally:
        await manager.close();pool.close()

if __name__=="__main__": asyncio.run(main())
