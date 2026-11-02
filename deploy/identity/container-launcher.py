#!/usr/bin/python3 -I
"""Root-owned, acceptance-only Docker gate. No arbitrary images, flags or mounts."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("fixed_recipes",HERE/"recipes.py")
recipes=importlib.util.module_from_spec(spec);spec.loader.exec_module(recipes)
CONFIG=HERE/"config.json"
KEY=re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}-(zkxk|senyuan|shared)")

def valid_name(name,c):
    ns=recipes.namespace(c["root"])
    return bool(re.fullmatch(r"department-reimbursement-"+ns+r"-[a-f0-9]{32}",name) or
                (name.startswith("department-id-ai-"+ns+"-") and KEY.fullmatch(name[len("department-id-ai-"+ns+"-"):])))

def validate(args,c):
    if not args or len(args)>160 or any(not isinstance(x,str) or len(x)>8192 or "\x00" in x for x in args):
        raise ValueError("invalid arguments")
    if len(args) in (2,3) and args[0] in ("prepare","prepare-job","cleanup-job") and KEY.fullmatch(args[1]):
        if args[0]=="prepare" and len(args)==2:return "prepare"
        if args[0]!="prepare" and len(args)==3 and re.fullmatch(r"[a-f0-9]{32}",args[2]):return args[0]
    ns=recipes.namespace(c["root"]);prefix="department-id-ai-"+ns+"-"
    if args==["image","inspect",recipes.IMAGE]:return "image"
    if args[0]=="inspect":
        if len(args)==2 and valid_name(args[1],c):return "inspect"
        if len(args)==4 and args[1]=="--format" and args[2] in ("{{json .Mounts}}","{{.State.Running}}") and valid_name(args[3],c):return "inspect"
    if len(args)==3 and args[:2]==["rm","-f"] and valid_name(args[2],c):return "remove"
    if args==["ps","-a","--format","{{.Names}}","--filter","label=department.identity-ai=true","--filter","name=^/"+prefix]:
        return "ps"
    if args[:3]==["ps","-aq","--filter"] and len(args) in (4,6):
        name=args[3].removeprefix("name=^/").removesuffix("$")
        if args[3]=="name=^/"+name+"$" and valid_name(name,c) and (len(args)==4 or args[4:]==["--filter","label=department.identity-ai=true"]):return "ps"
    if args[0]=="run" and args.count("--name")==1:
        name=args[args.index("--name")+1]
        if not valid_name(name,c):raise ValueError("foreign namespace")
        if name.startswith(prefix):
            expected=recipes.personal(c["root"],c["harness"],c["node"],c["checkout"],name[len(prefix):])
        else:
            mounts=[args[i+1] for i,x in enumerate(args[:-1]) if x=="--mount"]
            sources=[m.split(",src=",1)[1].split(",dst=",1)[0] for m in mounts if ",dst=/skill," in m]
            if len(sources)!=1:raise ValueError("stage missing")
            stage=Path(sources[0]).parent
            rel=stage.relative_to(c["root"])
            if len(rel.parts)!=2 or not KEY.fullmatch(rel.parts[0]) or not re.fullmatch(r"reimbursement-(?:[a-z0-9_]{8}|[a-f0-9]{32})",rel.parts[1]):
                raise ValueError("invalid stage")
            expected=recipes.reimbursement(c["root"],c["checkout"],stage,name.rsplit("-",1)[1])
        if args==expected:return "run"
    raise ValueError("Docker operation is not allowed")

def validate_binds(args,root):
    # Fixed entries in root-owned parents cannot be exchanged for symlinks by the app.
    for i,x in enumerate(args[:-1]):
        if x!="--mount":continue
        src=Path(args[i+1].split(",src=",1)[1].split(",dst=",1)[0])
        if src.is_relative_to(root):
            if src.is_symlink() or src.resolve()!=src:raise ValueError("unsafe bind")
            for parent in src.parents:
                info=parent.stat()
                if info.st_uid!=0 or info.st_mode&0o022:raise ValueError("mutable bind parent")
                if parent==root:break

def main():
    if os.geteuid()!=0 or int(os.getenv("DEPARTMENT_PEER_UID","-1"))!=10001:raise ValueError("invalid caller")
    for p in (HERE,Path(__file__),HERE/"recipes.py",CONFIG):
        s=p.stat()
        if s.st_uid!=0 or s.st_mode&0o022:raise ValueError("launcher installation is writable")
    c=json.loads(CONFIG.read_text());args=sys.argv[1:];kind=validate(args,c)
    env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","HOME":"/root","LANG":"C.UTF-8"}
    docker="/usr/bin/docker"
    root=Path(c["root"])
    if kind in ("prepare","prepare-job","cleanup-job"):
        key=root/args[1]
        if key.is_symlink() or (key.exists() and not key.is_dir()):raise ValueError("invalid personal root")
        key.mkdir(mode=0o750,exist_ok=True);os.chown(key,0,10001);key.chmod(0o750)
        if kind=="prepare":
            for part in ("home","transport","bridge","config",".control"):
                p=key/part
                if p.is_symlink():raise ValueError("symlink personal directory")
                p.mkdir(mode=0o700,exist_ok=True);os.chown(p,10001,10001)
            old=key/"session-authorizations.json";new=key/".control/session-authorizations.json"
            if old.is_file() and not old.is_symlink() and not new.exists():
                try:
                    fd=os.open(new,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd,"wb") as output:
                        output.write(old.read_bytes());os.fchown(output.fileno(),10001,10001)
            return 0
        stage=key/("reimbursement-"+args[2])
        if stage.is_symlink():raise ValueError("symlink stage")
        if kind=="cleanup-job":
            name="department-reimbursement-"+recipes.namespace(root)+"-"+args[2]
            r=subprocess.run([docker,"inspect","--format","{{.State.Running}}",name],capture_output=True,text=True,env=env)
            if r.returncode==0 and r.stdout.strip()=="true":raise ValueError("job still running")
            if stage.exists():shutil.rmtree(stage)
            return 0
        stage.mkdir(mode=0o750);os.chown(stage,0,10001);stage.chmod(0o750)
        for part in ("skill","input","output"):
            p=stage/part;p.mkdir(mode=0o700);os.chown(p,10001,10001)
        log=stage/"worker.log";log.touch(mode=0o600);os.chown(log,10001,10001)
        return 0
    if kind=="run":
        validate_binds(args,root)
        return subprocess.call([docker,*args],env=env)
    if kind=="inspect":
        name=args[-1]
        r=subprocess.run([docker,"inspect",name],capture_output=True,text=True,env=env)
        if r.returncode:return r.returncode
        values=json.loads(r.stdout)
        if len(args)==2:print(json.dumps(values))
        elif args[2]=="{{json .Mounts}}":print(json.dumps(values[0]["Mounts"]))
        else:print(str(values[0]["State"]["Running"]).lower())
        return 0
    return subprocess.call([docker,*args],env=env)

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,OSError,KeyError,IndexError,json.JSONDecodeError):
        print("Restricted acceptance container operation rejected",file=sys.stderr);sys.exit(77)
