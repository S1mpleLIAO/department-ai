"""Build the pinned upstream Landlock runner in this checkout only; never alter Harness."""
import json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
source=Path(os.getenv('DEPARTMENT_HARNESS_DIR','/root/liao/DepartmentKnowledgeBase/deepseek-harness'))/'native/system'
platform=ROOT/'.identity-state/native-system/linux-x64'
(platform/'bin').mkdir(parents=True,exist_ok=True)
compiler=shutil.which('musl-gcc') or shutil.which('gcc')
if not compiler:raise RuntimeError('Install a C compiler before preparing the acceptance sandbox')
pending=platform/'bin/landlock-run.pending'
subprocess.run([compiler,'-std=c11','-Os','-Wall','-Wextra','-Werror','-static','-s','-o',str(pending),str(source/'packages/entry/src/main.c')],check=True)
subprocess.run([str(pending),'--probe'],check=True)
for name in ('package.json','prebuilds.json'):(platform/name).write_text((source/'packages/linux-x64'/name).read_text())
pending.replace(platform/'bin/landlock-run')
# The platform overlay also contains the flock addon used by session persistence.
headers=Path('/usr/local/lib/nodejs/node-v22.22.3-linux-x64/include/node')
if not (headers/'node_api.h').is_file():raise RuntimeError('Node development headers missing')
addon=platform/'bin/glibc/system.node';addon.parent.mkdir(parents=True,exist_ok=True)
pending_addon=addon.with_suffix('.pending')
subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-fvisibility=hidden','-DNAPI_VERSION=8','-I',str(headers),'-shared','-o',str(pending_addon),str(source/'packages/entry/src/flock.c')],check=True)
pending_addon.replace(addon)
print('Built private sandbox runner; upstream Harness unchanged')
