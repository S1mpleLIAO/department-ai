"""Fixed isolated container recipes shared with the root-owned launcher."""
from pathlib import Path
import hashlib
IMAGE="pgvector/pgvector:0.8.6-pg17-bookworm"
UID=10001

def namespace(root):
    return hashlib.sha256(str(root).encode()).hexdigest()[:12]

def mount(args, src, dst, ro=True):
    args += ["--mount",f"type=bind,src={src},dst={dst}"+(",readonly" if ro else "")]

def personal(root, harness, node, checkout, key):
    root,harness,node,checkout=map(Path,(root,harness,node,checkout))
    home=root/key
    args=["run","-d","--pull=never","--name","department-id-ai-"+namespace(root)+"-"+key,
          "--label","department.identity-ai=true","--network","none","--read-only",
          "--user","10001:10001","--cap-drop","ALL","--security-opt","no-new-privileges",
          "--memory","640m","--memory-swap","640m","--cpus","0.5","--pids-limit","128",
          "--log-opt","max-size=10m","--log-opt","max-file=2",
          "--tmpfs","/tmp:rw,nosuid,nodev,size=64m",
          "-e","HOME=/home/assistant","-e","DSH_HOME=/home/assistant/dsh",
          "-e","NODE_OPTIONS=--max-old-space-size=256","-e","DEPARTMENT_LOCAL_MODEL=local-transport-only",
          "-e","DSH_TELEMETRY_DISABLED=1","-e","TSX_TSCONFIG_PATH=/opt/harness/tsconfig.json",
          "-w","/home/assistant/workspace"]
    for src,dst,ro in [(home/"home","/home/assistant",False),(home/"transport","/transport",False),
                       (home/"bridge","/bridge",True),(home/"config","/config",True),
                       (checkout/"harness/identity","/integration",True),(node,"/usr/local/bin/node",True)]:
        mount(args,src,dst,ro)
    for part in ("apps","packages","vendor","native","node_modules","package.json","pnpm-workspace.yaml","tsconfig.json","tsconfig.base.json"):
        mount(args,harness/part,"/opt/harness/"+part)
    mount(args,checkout/".identity-state/native-system/linux-x64","/opt/harness/native/system/packages/linux-x64")
    return args+["--entrypoint","/usr/local/bin/node",IMAGE,"/integration/relay.mjs"]

def reimbursement(root, checkout, stage, job):
    root,checkout,stage=map(Path,(root,checkout,stage))
    args=["run","--rm","--pull=never","--name","department-reimbursement-"+namespace(root)+"-"+job,
          "--label","department.reimbursement=true","--network","none","--read-only",
          "--user","10001:10001","--cap-drop","ALL","--security-opt","no-new-privileges",
          "--memory","512m","--memory-swap","512m","--cpus","0.5","--pids-limit","128",
          "--ulimit","fsize=33554432:33554432","--log-driver","none",
          "--tmpfs","/tmp:rw,nosuid,nodev,size=128m","-e","HOME=/tmp",
          "-e","FONTCONFIG_FILE=/department-fonts.conf","-e","PYTHONDONTWRITEBYTECODE=1"]
    for src,dst,ro in [(Path("/usr"),"/usr",True),(Path("/lib"),"/lib",True),(Path("/lib64"),"/lib64",True),
                      (Path("/etc/fonts"),"/etc/fonts",True),(Path("/etc/libreoffice"),"/etc/libreoffice",True),
                      (checkout/".identity-state/reimbursement-fonts/extracted/usr/share/fonts/truetype/arphic","/department-fonts",True),
                      (checkout/".identity-state/reimbursement-fonts/fonts.conf","/department-fonts.conf",True),
                      (checkout/"harness/identity/reimbursement_worker.py","/worker.py",True),
                      (stage/"skill","/skill",True),(stage/"input","/input",True),(stage/"output","/output",False)]:
        mount(args,src,dst,ro)
    return args+["--entrypoint","/usr/bin/timeout",IMAGE,"--kill-after=5","175","/usr/bin/python3","/worker.py"]
