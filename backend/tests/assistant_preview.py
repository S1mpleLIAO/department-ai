"""Start/stop only this worktree's localhost preview; no production scripts."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import socket
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/".identity-state"
if not str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028"):
    raise SystemExit("isolated worktree required")
path=STATE/"assistant-preview-pids.json"
if sys.argv[1]=="stop":
    owned=[]
    for pid in json.loads(path.read_text()).values():
        proc=Path("/proc")/str(pid)
        if proc.exists() and (proc/"cwd").resolve()==ROOT:
            os.kill(pid,signal.SIGTERM)
            owned.append(pid)
    for _ in range(150):
        if not any((Path('/proc')/str(pid)).exists() for pid in owned): break
        time.sleep(.1)
    for pid in owned:
        proc=Path('/proc')/str(pid)
        if proc.exists() and (proc/'cwd').resolve()==ROOT:
            os.kill(pid,signal.SIGKILL)
    print("Stopped isolated preview processes; data retained.")
else:
    if path.exists():
        for pid in json.loads(path.read_text()).values():
            proc=Path('/proc')/str(pid)
            if proc.exists() and (proc/'cwd').resolve()==ROOT:
                raise SystemExit('Stop the existing isolated preview first')
    env={**os.environ,**dotenv_values(STATE/"app.env"),"PYTHONPATH":"backend",
         "DEPARTMENT_AI_ORIGINS":json.dumps({"zkxk":"http://127.0.0.1:3182","senyuan":"http://127.0.0.1:3183","shared":"http://127.0.0.1:3184"}),
         "DEPARTMENT_AI_MODELS":'["department-test"]',
         "DEPARTMENT_AI_MODEL_URL":"http://127.0.0.1:3190/v1","DEPARTMENT_AI_MODEL_KEY":"synthetic-only"}
    real_model="--real-model" in sys.argv[2:]
    if real_model:
        model_path=STATE/"model.env"
        if not model_path.exists() or model_path.stat().st_mode & 0o077:
            raise SystemExit('Private .identity-state/model.env (mode 600) required')
        model=dotenv_values(model_path)
        for key in ("DEPARTMENT_AI_MODELS","DEPARTMENT_AI_MODEL_URL","DEPARTMENT_AI_MODEL_KEY"):
            if not model.get(key):raise SystemExit('Incomplete isolated model configuration')
            env[key]=model[key]
    commands={"app":["-m","uvicorn","app.main:app","--app-dir","backend","--host","127.0.0.1","--port","3181"],
              "gateway":["-m","app.features.assistant.gateway"],
              "model":["backend/tests/assistant_model_stub.py"]}
    if real_model:commands.pop("model")
    pids={}
    for name,args in commands.items():
        log=open(STATE/("assistant-"+name+".log"),"a")
        pids[name]=subprocess.Popen([str(ROOT/".venv-identity/bin/python"),*args],cwd=ROOT,env=env,
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True).pid
        log.close()
    path.write_text(json.dumps(pids));path.chmod(0o600)
    for port in ((3181,3182,3183,3184) if real_model else (3181,3182,3183,3184,3190)):
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):break
            except OSError:time.sleep(.2)
        else:raise SystemExit(f'Isolated preview failed to bind {port}; inspect private logs')
    print("Isolated preview started on loopback 3181–3184; model mode: "+("real" if real_model else "synthetic on 3190"))
