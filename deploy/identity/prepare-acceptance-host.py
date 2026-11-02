"""Install acceptance-only account, fixed broker and units; does not migrate data or restart."""
import json,os,pwd,grp,shutil,subprocess
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path.cwd()
assert str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028") and os.geteuid()==0
STATE=ROOT/".identity-state"
values=dotenv_values(STATE/"acceptance-preview.env")
runtime=Path(values["DEPARTMENT_AI_STATE_DIR"])
assert runtime==Path("/root/liao/identity-ai-acceptance")
assert (STATE/"native-system/linux-x64/bin/landlock-run").is_file(), "Run deploy/identity/build-native-sandbox.py first"
name="department-id-accept"
try:account=pwd.getpwuid(10001);assert account.pw_name==name
except KeyError:
    try:assert grp.getgrgid(10001).gr_name==name
    except KeyError:subprocess.run(["groupadd","--gid","10001",name],check=True)
    subprocess.run(["useradd","--system","--uid","10001","--gid","10001","--no-create-home","--home-dir",str(runtime),"--shell","/usr/sbin/nologin",name],check=True)
assert "docker" not in subprocess.check_output(["id","-nG",name],text=True).split()
helper=Path("/usr/local/libexec/department-identity-acceptance");helper.mkdir(mode=0o755,parents=True,exist_ok=True)
for source,target in [(ROOT/"deploy/identity/container-launcher.py",helper/"launcher.py"),
                      (ROOT/"backend/app/features/assistant/recipes.py",helper/"recipes.py"),
                      (ROOT/"deploy/identity/container-broker.py",helper/"broker.py"),
                      (ROOT/"deploy/identity/container-client.py",helper/"client.py")]:
    temporary=target.with_suffix(".pending")
    temporary.write_text(source.read_text());os.chown(temporary,0,0);temporary.chmod(0o755);temporary.replace(target)
config={"root":str(runtime),"checkout":str(ROOT),"harness":"/root/liao/DepartmentKnowledgeBase/deepseek-harness",
        "node":"/usr/local/lib/nodejs/node-v22.22.3-linux-x64/bin/node"}
pending=helper/"config.pending"
pending.write_text(json.dumps(config));os.chown(pending,0,0);pending.chmod(0o600);pending.replace(helper/"config.json")
# No sudo authorization: the service authenticates through the local peer-UID broker.
old_rule=Path("/etc/sudoers.d/department-identity-acceptance")
if old_rule.exists():old_rule.unlink()
for name in ("department-identity-container-broker.service","department-identity-acceptance.service"):
    source=ROOT/"deploy/identity"/name
    target=Path("/etc/systemd/system")/name
    target.write_text(source.read_text());os.chown(target,0,0);target.chmod(0o644)
subprocess.run(["systemctl","daemon-reload"],check=True)
print("Prepared fixed Unix broker and non-login service account; services not restarted")
