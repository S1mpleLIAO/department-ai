"""Exercise the script-source permission on the actual isolated Harness tool bridge."""
import asyncio,json
from pathlib import Path
import httpx
import assistant_live_check as live
live.ORIGIN="http://127.0.0.1:3191"
async def main():
    f=json.loads((live.STATE/"six-skills-fixture.json").read_text())
    user=f["users"]["reader"]
    dept=await live.login(user["username"],user["password"])
    ai=None
    try:
        ai=await live.entry(dept)
        root=Path(json.loads((live.STATE/"six-skills-ai-process.json").read_text())["stateRoot"])
        socket=root/(user["id"]+"-zkxk")/"bridge/io.sock"
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)),base_url="http://bridge") as bridge:
            r=await bridge.post("/tool/department_skill_get",json={"id":"travel-reimbursement-cn","resource":"scripts/generate_documents.py"})
            assert r.status_code==403,r.status_code
            r=await bridge.post("/tool/department_skill_get",json={"id":"travel-reimbursement-cn","resource":"assets/config/rules.json"})
            assert r.status_code==200 and r.json()["path"]=="assets/config/rules.json"
            r=await bridge.post("/tool/department_skill_list",json={})
            assert r.status_code==200 and [s["id"] for s in r.json()]==["travel-reimbursement-cn"]
        result={"script_source_denied":True,"non_script_assets_allowed":True,"only_reimbursement_enabled":True,
                "authenticated_runtime_bridge":True}
        p=live.STATE/"six-skills-source-bridge-results.json"
        p.write_text(json.dumps(result));p.chmod(0o600)
        print("PASS actual Harness bridge: use-only script read 403; assets 200; reimbursement-only list",flush=True)
    finally:
        await dept.post("/api/auth/logout")
        if ai:await ai.aclose()
        await dept.aclose()
if __name__=="__main__":asyncio.run(main())

