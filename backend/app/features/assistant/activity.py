"""Conservative native task inspection, independent of browser connections."""
import asyncio
import json
from uuid import uuid4
import websockets

def control_busy(rows, baseline):
    if not isinstance(rows, dict) or not isinstance(rows.get("items"), list):
        raise ValueError("unknown session list")
    if not isinstance(baseline, dict) or baseline.get("type") != "baseline":
        raise ValueError("unknown control baseline")
    value = baseline["value"]
    for field in ("queues", "jobs"):
        if not isinstance(value.get(field), dict) or any(not isinstance(x, list) for x in value[field].values()):
            raise ValueError("unknown " + field)
    if any(type(row.get("running")) is not bool for row in rows["items"]):
        raise ValueError("unknown running state")
    return {
        "running": any(row["running"] for row in rows["items"]),
        "queued": any(value["queues"].values()),
        "jobs": any(job.get("status") not in ("completed", "killed", "failed")
                    for jobs in value["jobs"].values() for job in jobs),
    }

async def activity(runtime):
    async with asyncio.timeout(10):
        response = await runtime.client.post("/api/session/list", json={
            "type": "client-request", "rpcId": str(uuid4()), "method": "session/list",
            "payload": {"args": {"_request": {}}}})
        response.raise_for_status()
        result = response.json()["result"]
        if result.get("ok") is not True: raise ValueError("session query failed")
        async with websockets.unix_connect(str(runtime.socket), uri="ws://runtime/api/remote.mux") as ws:
            await ws.send(json.dumps({"type": "open", "streamId": "idle-control",
                "endpoint": "session/control", "payload": {"args": {}}}))
            first = json.loads(await ws.recv())
            if first.get("type") != "item": raise ValueError("missing control state")
            return control_busy(result["value"], first.get("value"))

