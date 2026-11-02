"""Adapt the staged reimbursement skill; --apply adds an acceptance review draft."""
import argparse, base64, json, os
from pathlib import Path
from types import SimpleNamespace
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.features.identity.acceptance_import import ROOT, STATE, connection_info, private_json
from app.features.identity.service import audit
from app.features.reviews.service import normalize
from app.features.skills.service import _read

NAME = "travel-reimbursement-cn"
SOURCE = STATE / "acceptance/skill-imports/zkxk/travel_reimbursement_skill"
TARGET = STATE / "acceptance/skill-adapted/zkxk" / NAME
DRAFT = "legacy-acceptance-20261029-" + NAME
PROFILE_SCRIPT = """from __future__ import annotations
import argparse, json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('姓名', '部门', '职务', '银行卡', '开户行')
ap = argparse.ArgumentParser()
ap.add_argument('--profile', required=True, help='当前用户私有工作区中的个人档案路径')
ap.add_argument('--set', action='append', default=[], metavar='字段=值')
a = ap.parse_args()
p = Path(a.profile).resolve()
if p == ROOT or ROOT in p.parents:
    raise SystemExit('个人档案必须保存在当前用户的私有工作区，不能写入技能目录')
d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else dict.fromkeys(FIELDS, '')
if not isinstance(d, dict) or set(d) - set(FIELDS):
    raise SystemExit('个人档案字段无效')
for item in a.set:
    k, sep, v = item.partition('=')
    if not sep or k not in FIELDS:
        raise SystemExit('只允许设置姓名、部门、职务、银行卡、开户行')
    d[k] = v
if a.set:
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(d, out, ensure_ascii=False, indent=2)
    p.chmod(0o600)
    print('个人档案已更新')
else:
    print(json.dumps(d, ensure_ascii=False, indent=2))
"""
NOTE = """
## 独立环境目录适配
规范名称为 `travel-reimbursement-cn`，附件仅位于 scripts、references、assets。
技能目录是只读发布资源；模板和规则位于 assets，示例和说明位于 references。
共享包仅提供 assets/config/user_profile.example.json 空白档案，禁止沿用旧技能拥有者的个人资料。
仅在当前已登录用户的私有工作区建立个人档案和生成输出，不使用共享目录或其他人的目录。
更新档案示例：python scripts/profile.py --profile /当前用户私有工作区/user_profile.json --set 姓名=本人姓名
首次使用必须由当前用户补齐五项档案；生成脚本显式要求 --profile，不再读取技能内的档案。
从技能根目录执行示例命令；Python 需 python-docx，原报销单脚本仍需 /usr/bin/python3 的 UNO 和 LibreOffice。
本次只适配资源路径和个人档案入口，补助标准及财务规则仍须业务审核。
"""

def adapted_files():
    files = {}
    for path in sorted(SOURCE.rglob("*")):
        if path.is_symlink():
            raise ValueError("Unexpected symlink")
        if not path.is_file():
            continue
        if path.stat().st_size > 2*1024*1024:
            raise ValueError("Unexpected large resource")
        rel = path.relative_to(SOURCE).as_posix()
        if rel == "config/user_profile.json":
            files["assets/config/user_profile.example.json"] = json.dumps(
                dict.fromkeys(("姓名","部门","职务","银行卡","开户行"),""),ensure_ascii=False,indent=2).encode()
            continue
        if rel.startswith(("config/","templates/")):
            dest = "assets/" + rel
        elif rel.startswith(("schemas/","examples/")) or "/" not in rel and rel != "SKILL.md":
            dest = "references/" + rel
        else:
            dest = rel
        data = path.read_bytes()
        if path.suffix in (".py",".md",".txt"):
            text = data.decode()
            for old,new in (("config/trip_presets.json","assets/config/trip_presets.json"),
                            ("config/rules.json","assets/config/rules.json"),
                            ("templates/","assets/templates/"),("schemas/","references/schemas/"),
                            ("examples/","references/examples/")):
                text = text.replace(old,new)
            if rel == "scripts/generate_documents.py":
                text = text.replace("ap.add_argument('--job',required=True);",
                    "ap.add_argument('--profile',required=True); ap.add_argument('--job',required=True);")
                text = text.replace("profile=load(ROOT/'config/user_profile.json')","profile=load(a.profile)")
            if rel == "scripts/profile.py":
                text = PROFILE_SCRIPT
            if rel in ("SKILL.md","README.md"):
                text = text.replace("config/user_profile.json","当前用户私有工作区中的 user_profile.json")
                text = text.replace("python scripts/generate_documents.py",
                    "python scripts/generate_documents.py --profile /当前用户私有工作区/user_profile.json")
                text += "\n" + NOTE
            data = text.encode()
        if rel == "examples/input.example.json":
            sample = json.loads(data)
            for trip in sample["trips"]:
                if "participants" in trip:
                    trip["participants"] = ["示例人员甲","示例人员乙"]
            data = json.dumps(sample,ensure_ascii=False,indent=2).encode()
        files[dest] = data
    files["references/manifest.txt"] = ("\n".join(sorted(files))+"\n").encode()
    return files

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if Path.cwd()!=ROOT or not (STATE/"real-data-copy-approved-20261029").is_file():
        raise ValueError("Run only in the approved independent worktree")
    os.umask(0o077)
    files=adapted_files()
    for rel,data in files.items():
        p=TARGET/rel
        if p.exists() and (p.is_symlink() or p.read_bytes()!=data):
            raise ValueError("Adapted resource already differs: "+rel)
    for rel,data in files.items():
        p=TARGET/rel
        p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():
            with p.open("xb") as out:out.write(data)
    skill=_read(TARGET)
    assert skill["name"]==TARGET.name
    payload=normalize(SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(max_source_bytes=15*1024*1024))),
        "skills",{"skill":{k:skill[k] for k in ("name","description","instructions","enabled")},
        "resources":[{"path":rel,"contentBase64":base64.b64encode(data).decode()}
                     for rel,data in files.items() if rel!="SKILL.md"]})
    result={"name":NAME,"files":len(files),"resources":len(payload["resources"]),"target":str(TARGET),"draft":DRAFT}
    if args.apply:
        _,dsn=connection_info()
        with psycopg.connect(dsn,row_factory=dict_row) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(DRAFT,))
            existing=conn.execute("SELECT id FROM review_submissions WHERE id=%s",(DRAFT,)).fetchone()
            if existing:result["already_imported"]=True
            else:
                actor=conn.execute("SELECT id FROM users WHERE username='liao-admin' AND active AND superadmin").fetchone()
                if not actor:raise ValueError("Acceptance owner unavailable")
                conn.execute("INSERT INTO review_submissions(id,space_id,owner_id,kind,title,draft,source_key) VALUES (%s,'zkxk',%s,'skills',%s,%s,%s)",
                    (DRAFT,actor["id"],NAME,Jsonb(payload),DRAFT))
                audit(conn,actor["id"],"migration.skill_adapted",DRAFT,space="zkxk",
                    details={"from":"travel_reimbursement_skill","to":NAME,"personal_profile":"excluded","resources":len(payload["resources"])})
                result["status"]="draft"
        if not existing:private_json(STATE/"reimbursement-adaptation-20261029.json",result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()

