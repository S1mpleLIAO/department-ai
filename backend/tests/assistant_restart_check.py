"""Real Harness restart on private persistent staging storage; no production data/model."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from app.core.database import create_pool
from app.features.identity.service import login, authenticate
from app.features.assistant.runtime import Manager

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/".identity-state"
if not str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028"):
    raise SystemExit("isolated worktree required")


async def main():
    os.environ.update(DEPARTMENT_AI_RUNTIME_MODE="production",DEPARTMENT_AI_STATE_DIR="/root/.dai-stage-20261028")
    credentials=json.loads((STATE/"credentials.json").read_text())
    fixture=json.loads((STATE/"assistant-fixture.json").read_text())
    pool=create_pool(credentials["appDsn"]);pool.open(wait=True)
    token,_,_=login(pool,fixture["username"],fixture["password"],"staging-restart","staging-restart")
    principal,_=authenticate(pool,token)
    session=None
    try:
        for generation in range(2):
            manager=Manager(pool,["department-test"])
            try:
                runtime=await manager.get(principal,"zkxk")
                response=await runtime.client.get("/")
                assert response.status_code==200 and "dsh web authentication required" not in response.text
                async def rpc(name,args):
                    r=await runtime.client.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),
                       "method":name,"payload":{"args":args}})
                    payload=r.json();assert payload["result"]["ok"],payload
                    return payload["result"].get("value")
                if generation==0:
                    session=(await rpc("session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":"department"}}))["sessionId"]
                    runtime.session_epoch(session,create=True)
                    await rpc("settings/update",{"ns":"locale","patch":{"preference":"zh"}})
                    print("persistent staging runtime + private automatic auth: PASS",flush=True)
                else:
                    assert session in json.dumps(await rpc("session/list",{"_request":{}}))
                    runtime.session_epoch(session)
                    settings=await rpc("settings/describe",{})
                    locale=next(n for n in settings["namespaces"] if n["ns"]=="locale")
                    assert '"zh"' in json.dumps(locale.get("value",locale.get("config",{})))
                    print("fresh container restart retains session, personal locale and authorization epoch: PASS",flush=True)
            finally:await manager.close()
    finally:
        with pool.connection() as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at=now() WHERE id=%s",(principal.session_id,))
        pool.close()


if __name__=="__main__":asyncio.run(main())
