"""Small boundary checks for the fixed reimbursement runner."""
import asyncio,json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from fastapi import HTTPException
from app.core.security import Principal
from app.features.assistant.reimbursement import inputs,uploaded_path,materialize,publication
profile=dict(zip(("姓名","部门","职务","银行卡","开户行"),("测试","技术","工程师","0000","测试银行")))
job={"trips":[{"project_name":"测试项目","city":"北京","start_date":"2026-01-01","end_date":"2026-01-01","visited_company":"测试公司","work_item":"测试","transport_type":"汽车","transport_items":[],"lodging_items":[],"airport_station_transport":[],"other_items":[]}]}
def denied(fn):
 try:fn()
 except HTTPException as e:assert 400<=e.status_code<500
 else:raise AssertionError("expected rejection")
def main():
 args={"jobJson":json.dumps(job),"profileJson":json.dumps(profile)}
 assert inputs(args)[0]["trips"][0]["city"]=="北京"
 for key,value in (("folder_name","../another-user"),("project_name",""),("end_date","2025-12-31")):
  bad=deepcopy(job);bad["trips"][0][key]=value
  denied(lambda:inputs({**args,"jobJson":json.dumps(bad)}))
 for value in ("NaN","-1","0.001","10000000"):
  bad=deepcopy(job);bad["trips"][0]["other_items"]=[{"amount":value,"receipt_count":1}]
  denied(lambda:inputs({**args,"jobJson":json.dumps(bad)}))
 denied(lambda:inputs({**args,"profileJson":"{}"}))
 p=Principal("user","session","zkxk",False,{"zkxk":{"assistant.use","skills.use"}},False)
 denied(lambda:publication(SimpleNamespace(space="senyuan"),p))
 with TemporaryDirectory() as folder:
  root=Path(folder);rt=SimpleNamespace(root=root)
  digest="a"*64;native=f"/home/assistant/dsh/attachments/v1/files/aa/{digest}/receipt.txt"
  file=root/"home"/Path(native).relative_to("/home/assistant")
  file.parent.mkdir(parents=True);file.write_text("receipt")
  assert uploaded_path(rt,native)==file
  other=SimpleNamespace(root=root/"another-user")
  denied(lambda:uploaded_path(other,native))
  file.unlink();file.symlink_to("/etc/passwd")
  denied(lambda:uploaded_path(rt,native))
  denied(lambda:materialize({"resources":[{"path":"../secret","contentBase64":""}]},root))
 print("PASS reimbursement input, money, company, foreign user, symlink and resource path boundaries")
if __name__=="__main__":main()
