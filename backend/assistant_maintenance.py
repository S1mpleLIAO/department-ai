"""Read-only reports by default. Cleanup requires an offline supervisor and --apply."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
from app.features.assistant.compatibility import verify
from app.features.assistant.storage import report,cleanup_candidates
from app.features.assistant.recipes import namespace
from app.features.assistant.config import runtime_config
from identity_server import load_environment

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("compatibility","storage","cleanup-temp"))
    parser.add_argument("--env-file",required=True)
    parser.add_argument("--candidate",type=Path)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    load_environment(args.env_file);c=runtime_config()
    if args.action=="compatibility":
        print(json.dumps(verify(args.candidate or c.harness),ensure_ascii=False));return
    if args.action=="storage":
        print(json.dumps(report(c.root),ensure_ascii=False,indent=2));return
    # Never touch user output. Offline exclusive ownership prevents running/staged work races.
    with (c.root/".control/supervisor.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("Supervisor is running; cleanup refused (stop only isolated service first)")
        names=subprocess.check_output(["docker","ps","--format","{{.Names}}"],text=True).splitlines()
        owned=[n for n in names if namespace(c.root) in n]
        candidates=cleanup_candidates(c.root,owned)
        if args.apply:
            for p in candidates:shutil.rmtree(p)
        print(json.dumps({"applied":args.apply,"temporaryDirectories":[str(p) for p in candidates],
                          "preserved":"all sessions, attachments, workspace files and personal settings"},ensure_ascii=False))
if __name__=="__main__":main()
