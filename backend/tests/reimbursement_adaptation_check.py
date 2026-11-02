"""Run on Aliyun isolated worktree: PYTHONPATH=backend .venv-identity/bin/python backend/tests/reimbursement_adaptation_check.py"""
import json, os, subprocess, tempfile, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from app.features.identity.reimbursement_adaptation import ROOT, STATE, SOURCE, TARGET, adapted_files
from app.features.skills.service import _read

assert Path.cwd()==ROOT
os.umask(0o077)
checks=[]
def check(name,ok):
    assert ok,name
    checks.append(name)
    print("PASS",name,flush=True)
def run(script,*args,ok=True):
    p=subprocess.run(["/usr/bin/python3",str(TARGET/"scripts"/script),*map(str,args)],
        cwd=STATE,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"},capture_output=True,text=True,timeout=120)
    assert (p.returncode==0)==ok,(script,p.stderr[-1000:])
    return p
def contents(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if p.is_file()}
source_before=contents(SOURCE)
skill_before=contents(TARGET)
check("canonical skill name and 16 supported resources",_read(TARGET)["name"]==TARGET.name and len(_read(TARGET)["resources"])==16)
check("repeat adaptation is deterministic",adapted_files()==skill_before)
check("complete manifest",set((TARGET/"references/manifest.txt").read_text().splitlines())==set(skill_before))
check("original templates preserved",all((TARGET/"assets"/p).read_bytes()==v for p,v in source_before.items() if p.startswith("templates/")))
check("shared profile contains no personal values",not any(json.loads((TARGET/"assets/config/user_profile.example.json").read_text()).values()))
check("missing profile fails explicitly",run("generate_documents.py","--job","absent","--output-dir","absent",ok=False).returncode==2)
run("profile.py","--profile",TARGET/"assets/config/user_profile.example.json","--set","姓名=禁止写入",ok=False)
check("profile helper refuses writes into skill",contents(TARGET)==skill_before)

testroot=Path(tempfile.mkdtemp(prefix="reimbursement-check-",dir=STATE))
profile_a={"姓名":"验收人员甲","部门":"虚构部门甲","职务":"测试员","银行卡":"TEST-ACCOUNT-A","开户行":"测试银行甲"}
profile_b={**profile_a,"姓名":"验收人员乙","银行卡":"TEST-ACCOUNT-B","开户行":"测试银行乙"}
job_a=json.loads((TARGET/"references/examples/input.example.json").read_text())
job_b={"form_date":"2026-10-29","generation_timestamp":"20261029_120000","trips":[{
    "folder_name":"虚构项目","project_name":"虚构项目","city":"北京","start_date":"2026-10-28","end_date":"2026-10-28",
    "visited_company":"虚构单位","work_item":"验证生成","transport_type":"汽车",
    "transport_items":[],"lodging_items":[],"airport_station_transport":[],
    "other_items":[{"name":"测试费用","amount":12.34,"receipt_count":1}]}]}
for user,profile,job,total,count in (("a",profile_a,job_a,2702.36,5),("b",profile_b,job_b,162.34,3)):
    home=testroot/user;home.mkdir(mode=0o700)
    pp=home/"profile.json"; jp=home/"job.json";out=home/"output"
    run("profile.py","--profile",pp,*[a for k,v in profile.items() for a in ("--set",k+"="+v)])
    check(user+" profile is private",pp.stat().st_mode&0o777==0o600)
    jp.write_text(json.dumps(job,ensure_ascii=False))
    result=run("generate_documents.py","--profile",pp,"--job",jp,"--output-dir",out)
    report=json.loads((out/"generation_report.json").read_text())
    check(user+" expected financial total",report["total"]==total)
    docs=list(out.rglob("*.docx"))
    check(user+" correct number and timestamp of documents",len(docs)==count and all(job["generation_timestamp"] in p.name for p in docs))
    texts=[]
    for p in docs:
        with zipfile.ZipFile(p) as z:
            check(user+" valid DOCX "+p.name,z.testzip() is None and "word/document.xml" in z.namelist())
            texts.append("".join(ET.fromstring(z.read("word/document.xml")).itertext()))
    text="\n".join(texts)
    check(user+" current profile used",profile["姓名"] in text and profile["银行卡"] in text and profile["开户行"] in text)
    other=profile_b if user=="a" else profile_a
    check(user+" no other synthetic profile",other["姓名"] not in text and other["银行卡"] not in text)
    check(user+" no leftover private payload",not (out/".reimbursement_payload.json").exists())
    check(user+" no missing metadata warnings",not report["warnings"])
blank=testroot/"blank.json";blank.write_text("{}")
run("generate_documents.py","--profile",blank,"--job",testroot/"a/job.json","--output-dir",testroot/"must-not-exist",ok=False)
check("incomplete profile stops before output creation",not (testroot/"must-not-exist").exists())
check("staged original is unchanged",contents(SOURCE)==source_before)
check("adapted skill is unchanged by execution",contents(TARGET)==skill_before)
report={"checks":checks,"output":str(testroot),"documents":8,"synthetic_profiles_only":True,"visual_render_checked":False}
(STATE/"reimbursement-generation-check-20261029.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({"passed":len(checks),"output":str(testroot)},ensure_ascii=False))

