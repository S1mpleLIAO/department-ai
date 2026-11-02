"""Acceptance resource gate regression; no session/model/provider calls."""
import json
from pathlib import Path
from fastapi import HTTPException
from app.core.database import create_pool
from app.core.security import Principal
from app.features.assistant.resources import call
from app.features.identity.acceptance_import import ROOT,STATE,connection_info
assert Path.cwd()==ROOT
connection_info()
config=json.loads((STATE/"acceptance-db.json").read_text())
f=json.loads((STATE/"six-skills-fixture.json").read_text())
pool=create_pool(config["appDsn"]);pool.open(wait=True)
u=f["users"]["reader"]["id"]
user=Principal(u,"direct-tool-test","zkxk",False,{"zkxk":["assistant.use","skills.use"]},False)
source=Principal(u,"direct-tool-test","zkxk",False,{"zkxk":["assistant.use","skills.use","skills.source_read"]},False)
args={"id":"travel-reimbursement-cn","resource":"scripts/generate_documents.py"}
try:
    try:call(pool,user,"zkxk","department_skill_get",args)
    except HTTPException as error:assert error.status_code==403
    else:raise AssertionError("skills.use can retrieve script source via AI tool")
    assert call(pool,source,"zkxk","department_skill_get",args)["path"]==args["resource"]
    assert call(pool,user,"zkxk","department_skill_get",{"id":args["id"]})["name"]==args["id"]
    assert call(pool,user,"zkxk","department_skill_get",{"id":args["id"],"resource":"assets/config/rules.json"})["path"]=="assets/config/rules.json"
    print("PASS AI script resources require source_read; skill instructions and non-script assets still available")
finally:pool.close()

