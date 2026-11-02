"""Fail closed on changes to the reviewed Harness source/plugin integration surface."""
import hashlib
import json
from pathlib import Path

BASELINE=Path(__file__).resolve().parents[4]/"harness/identity/compatibility-baseline.json"
MODULES=("api","client/connection","client/modules","host/webserver","host/frontend-static",
         "preset/persona","preset/agent-presets","llm/llm-pi-ai","core/tools",
         "core/session","core/session-persistence","core/settings","boot")
def snapshot(harness):
    root=Path(harness)
    paths={root/"package.json",root/"apps/cli/package.json",root/"apps/web/package.json"}
    paths.update(root.glob("packages/*/*/package.json"))
    paths.update(root.glob("vendor/*/package.json"))
    for module in MODULES:
        base=root/"packages"/module
        if not base.exists():continue
        for pattern in ("**/src/**/*.ts","**/*.cordis.yml"):
            paths.update(p for p in base.glob(pattern) if not any(x in p.parts for x in ("node_modules","lib","dist","test","tests","__tests__")) and not p.name.endswith((".test.ts",".spec.ts")))
    files={}
    for p in sorted(paths):
        if p.is_symlink() or not p.is_file():raise RuntimeError("Missing or symlinked Harness source: "+str(p.relative_to(root)))
        if p.stat().st_size>2*1024*1024:raise RuntimeError("Unexpected oversized source")
        files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return {"version":json.loads((root/"package.json").read_text())["version"],"files":files}

def verify(harness,baseline=BASELINE):
    expected=json.loads(Path(baseline).read_text());actual=snapshot(harness)
    changes=[p for p in sorted(set(expected["files"])|set(actual["files"])) if expected["files"].get(p)!=actual["files"].get(p)]
    if expected["version"]!=actual["version"] or changes:
        raise RuntimeError("Harness compatibility not approved; expected "+expected["version"]+
                           ", found "+actual["version"]+"; changed source/package metadata: "+", ".join(changes[:12]))
    return {"version":actual["version"],"checkedFiles":len(actual["files"]),"passed":True,
            "note":"Source/package baseline only; candidate build still requires native integration regression."}
