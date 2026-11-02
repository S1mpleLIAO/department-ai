"""Acceptance-only cold backup and disposable PostgreSQL/native Harness restore drill."""
import asyncio,hashlib,json,os,shutil,stat,subprocess,time
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from uuid import uuid4
import httpx,psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/".identity-state"
SOURCE_DB="identity_acceptance_20261028";SOURCE_CONTAINER="department-identity-dev-20261028"
AI=Path("/root/liao/identity-ai-acceptance");SERVICE="department-identity-acceptance.service"
assert str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028") and os.geteuid()==0
os.umask(0o077)
checks=[]
def check(s):checks.append(s);print("PASS "+s,flush=True)
def run(args,**kw):
 return subprocess.run(args,check=True,capture_output=True,**kw).stdout
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def manifest(root):
 v=root.stat();result={".":{"kind":"dir","mode":stat.S_IMODE(v.st_mode),"uid":v.st_uid,"gid":v.st_gid}}
 for parent,dirs,files in os.walk(root,followlinks=False):
  for name in dirs+files:
   p=Path(parent)/name;v=p.lstat();rel=p.relative_to(root).as_posix()
   base={"mode":stat.S_IMODE(v.st_mode),"uid":v.st_uid,"gid":v.st_gid}
   if stat.S_ISLNK(v.st_mode):base.update(kind="link",target=os.readlink(p))
   elif stat.S_ISREG(v.st_mode):base.update(kind="file",size=v.st_size,sha256=digest(p))
   elif stat.S_ISDIR(v.st_mode):base.update(kind="dir")
   else:continue # Unix sockets and live IPC are regenerated on startup.
   result[rel]=base
 return result
def ignored(directory,names):
 return [name for name in names if not (stat.S_ISREG((Path(directory)/name).lstat().st_mode) or stat.S_ISDIR((Path(directory)/name).lstat().st_mode) or stat.S_ISLNK((Path(directory)/name).lstat().st_mode))]
def restore_ownership(root,m):
 for name,row in m.items():
  p=root/name
  os.chown(p,row["uid"],row["gid"],follow_symlinks=False)
  if row["kind"]!="link":p.chmod(row["mode"])
def verify_tree(root,m):
 current=manifest(root)
 assert set(current)==set(m),"backup file inventory mismatch"
 for name,row in m.items():
  for field in ("kind","size","sha256","target","mode"):
   assert current[name].get(field)==row.get(field),f"backup verification failed: {name} {field}"
def fingerprint(dsn):
 with psycopg.connect(dsn) as c:
  tables=[r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
  result={}
  for table in tables:
   rows=[r[0] for r in c.execute(sql.SQL("SELECT row_to_json(t)::text FROM public.{} t").format(sql.Identifier(table)))]
   result[table]={"rows":len(rows),"sha256":hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()}
  return result
async def native_restore(app_dsn,folder,fixture):
 from app.core.database import create_pool
 from app.features.identity.service import login,authenticate
 from app.features.assistant.runtime import Manager
 from app.features.assistant.activity import activity
 db=create_pool(app_dsn);db.open(wait=True);m=None
 try:
  u=fixture["users"][0];token,_,_=login(db,u["username"],u["password"],"restore-test","restore-test")
  p=authenticate(db,token)[0];m=Manager(db,["deepseek-v4-flash"])
  async with m.lease(p,"zkxk") as r:
   async def rpc(name,args):
    response=await r.client.post("/api/"+name,json={"type":"client-request","rpcId":str(uuid4()),"method":name,"payload":{"args":args}})
    response.raise_for_status();value=response.json()["result"];assert value["ok"];return value["value"]
   rows=await rpc("session/list",{"_request":{}})
   assert fixture["sessionId"] in json.dumps(rows)
   assert not any((await activity(r)).values())
   desc=await rpc("settings/describe",{})
   assert next(x for x in desc["namespaces"] if x["ns"]=="ui-theme")["value"]["fontSize"]==17
   response=await r.client.get("/api/file",params={"path":fixture["downloadPath"],"download":"1"})
   response.raise_for_status();assert len(response.content)>100
   check("restored native Harness opens previous session, personal setting and generated download")
 finally:
  if m:await m.close()
  db.close()
def main():
 from app.features.assistant.recipes import namespace
 creds=json.loads((STATE/"acceptance-db.json").read_text())
 assert conninfo_to_dict(creds["adminDsn"])["dbname"]==SOURCE_DB
 fixture=json.loads((STATE/"hardening-live.private.json").read_text())
 backup=STATE/"backups"/("acceptance-"+time.strftime("%Y%m%d-%H%M%S"))
 backup.mkdir(parents=True,mode=0o700)
 roots={"ai":AI,"data":STATE/"acceptance/data","skills":STATE/"acceptance/skills"}
 result={"passed":False,"backupPath":str(backup),"checks":checks};stopped=False;container=None
 source_before=None
 try:
  assert shutil.disk_usage(AI).free>3*1024**3,"not enough disk headroom"
  own=run(["docker","ps","--format","{{.Names}}"]).decode().splitlines()
  assert not any(namespace(AI) in n for n in own),"acceptance has active instances; refuse cold backup"
  run(["systemctl","stop",SERVICE]);stopped=True
  try:
   own=run(["docker","ps","--format","{{.Names}}"]).decode().splitlines()
   assert not any(namespace(AI) in n for n in own),"active acceptance work; backup refused"
   source_before=fingerprint(creds["adminDsn"])
   with (backup/"database.dump").open("wb") as f:
    subprocess.run(["docker","exec",SOURCE_CONTAINER,"pg_dump","-U","postgres","-Fc",SOURCE_DB],stdout=f,stderr=subprocess.PIPE,check=True)
   with (backup/"roles.sql").open("wb") as f:
    subprocess.run(["docker","exec",SOURCE_CONTAINER,"pg_dumpall","-U","postgres","--roles-only"],stdout=f,stderr=subprocess.PIPE,check=True)
   manifests={}
   for name,path in roots.items():
    manifests[name]=manifest(path)
    shutil.copytree(path,backup/name,symlinks=True,ignore=ignored)
    verify_tree(backup/name,manifests[name])
   (backup/"config").mkdir()
   for name,path in {"service.env":Path("/var/lib/department-identity-acceptance/service.env"),"broker.json":Path("/usr/local/libexec/department-identity-acceptance/config.json"),"compatibility-baseline.json":ROOT/"harness/identity/compatibility-baseline.json"}.items():
    shutil.copyfile(path,backup/"config"/name)
   meta={"roots":{k:str(v) for k,v in roots.items()},"files":manifests,"database":source_before,
         "dumpSha256":digest(backup/"database.dump"),"rolesSha256":digest(backup/"roles.sql"),
         "harnessVersion":"0.1.5-rc.1","sourceDatabase":SOURCE_DB}
   (backup/"manifest.json").write_text(json.dumps(meta,ensure_ascii=False))
   check("cold backup captures database, roles, business files, AI sessions/settings and private configuration")
  finally:
   run(["systemctl","start",SERVICE]);stopped=False
   for _ in range(40):
    try:
     if httpx.get("http://127.0.0.1:3181/health",timeout=3).status_code==200:break
    except httpx.HTTPError:pass
    time.sleep(1)
   else:raise AssertionError("acceptance failed to restart")
  @contextmanager
  def restore_workspace():
   nonlocal container
   with TemporaryDirectory(prefix=".id-dr-",dir="/root") as tmp:
    try:yield tmp
    finally:
     if container:run(["docker","rm","-f",container]);container=None
  with restore_workspace() as tmp:
   restore=Path(tmp)
   for name in roots:
    shutil.copytree(backup/name,restore/name,symlinks=True)
    restore_ownership(restore/name,manifests[name]);verify_tree(restore/name,manifests[name])
   check("every restored regular file hash and symlink target matches; no shared dependency copied")
   # Corruption test touches only a disposable restored file, not the retained backup.
   target=next(restore/"data"/k for k,v in manifests["data"].items() if v["kind"]=="file")
   original=target.read_bytes();target.write_bytes(original+b"CORRUPTION_TEST")
   try:verify_tree(restore/"data",manifests["data"])
   except AssertionError:check("corrupted restore rejected by manifest verification")
   else:raise AssertionError("corruption was not detected")
   target.write_bytes(original);verify_tree(restore/"data",manifests["data"])
   assert digest(backup/"database.dump")==meta["dumpSha256"] and digest(backup/"roles.sql")==meta["rolesSha256"]
   password=uuid4().hex;env=restore/"postgres.env"
   env.write_text("POSTGRES_USER=restore_admin\nPOSTGRES_PASSWORD="+password+"\n")
   (restore/"pgdata").mkdir();container="department-restore-"+uuid4().hex[:10]
   run(["docker","run","-d","--pull=never","--name",container,"--label","department.restore-drill=true","--memory","256m","--cpus","0.5",
        "-p","127.0.0.1::5432","--env-file",str(env),"--mount","type=bind,src="+str(restore/"pgdata")+",dst=/var/lib/postgresql/data","pgvector/pgvector:0.8.6-pg17-bookworm"])
   port=int(run(["docker","port",container,"5432/tcp"]).decode().strip().rsplit(":",1)[1])
   admin=make_conninfo(host="127.0.0.1",port=port,user="restore_admin",password=password,dbname="postgres")
   for _ in range(60):
    try:
     with psycopg.connect(admin):break
    except psycopg.OperationalError:time.sleep(.5)
   else:raise AssertionError("disposable PostgreSQL did not start")
   run(["docker","exec","-i",container,"psql","-U","restore_admin","-d","postgres","-v","ON_ERROR_STOP=1"],input=(backup/"roles.sql").read_bytes())
   with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL("CREATE DATABASE {} OWNER postgres").format(sql.Identifier(SOURCE_DB)))
   run(["docker","exec","-i",container,"pg_restore","-U","restore_admin","-d",SOURCE_DB,"--exit-on-error"],input=(backup/"database.dump").read_bytes())
   restored_admin=make_conninfo(admin,dbname=SOURCE_DB)
   assert fingerprint(restored_admin)==source_before
   app_params=conninfo_to_dict(creds["appDsn"]);app_params.update(host="127.0.0.1",port=str(port))
   app_dsn=make_conninfo(**app_params)
   with psycopg.connect(app_dsn) as c:
    row=c.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone();assert row==(False,False)
   check("fresh PostgreSQL restores roles, all 22 tables, vectors and identical row contents")
   with psycopg.connect(restored_admin) as c:
    assert c.execute("SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relrowsecurity").fetchone()[0]>0
    # Only the disposable database gets temporary validation authorization/path remapping.
    u=fixture["users"][0];c.execute("UPDATE users SET active=true,superadmin=true WHERE id=%s",(u["id"],))
    c.execute("UPDATE knowledge_documents SET original_path=replace(original_path,%s,%s)",(str(roots["data"]),str(restore/"data")))
   values=dotenv_values(backup/"config/service.env")
   os.environ.update({k:v for k,v in values.items() if v is not None})
   os.environ.update(DEPARTMENT_DATABASE_URL=app_dsn,DEPARTMENT_DATA_DIR=str(restore/"data"),DEPARTMENT_SKILL_DIR=str(restore/"skills"),
      DEPARTMENT_AI_STATE_DIR=str(restore/"ai"),DEPARTMENT_AI_RUNTIME_MODE="isolated",DEPARTMENT_AI_ORIGINS="{}")
   from fastapi.testclient import TestClient
   from app.main import app
   with TestClient(app,base_url="http://127.0.0.1:3181") as client:
    assert client.get("/api/state").status_code==401
    r=client.post("/api/auth/login",headers={"Origin":"http://127.0.0.1:3181"},json={"username":u["username"],"password":u["password"]})
    assert r.status_code==200,r.status_code
    downloaded=set()
    for space in ("zkxk","senyuan","shared"):
     h={"X-Department-Space":space}
     assert client.get("/api/processes",headers=h).status_code==200
     docs=client.get("/api/documents",headers=h);assert docs.status_code==200
     for doc in docs.json():
      r=client.get("/api/documents/"+doc["id"]+"/source",headers=h)
      assert r.status_code==200 and len(r.content)>0
      downloaded.add(doc["id"])
    assert len(downloaded)==source_before["knowledge_documents"]["rows"],(len(downloaded),source_before["knowledge_documents"]["rows"])
   check("restored department login, company views and all "+str(len(downloaded))+" unique source document downloads succeed")
   asyncio.run(native_restore(app_dsn,restore,fixture))
   run(["docker","rm","-f",container]);container=None
  assert fingerprint(creds["adminDsn"])==source_before,"source acceptance DB unexpectedly changed"
  for name,path in roots.items():verify_tree(path,manifests[name])
  check("original acceptance database and persistent files unchanged by restore drill")
  for port,path,code in ((3080,"/",401),(3081,"/health",200),(3181,"/health",200)):
   assert httpx.get(f"http://127.0.0.1:{port}{path}",timeout=5).status_code==code
  result.update(passed=True,tableCount=len(source_before),regularFiles=sum(v["kind"]=="file" for m in manifests.values() for v in m.values()),
                symlinks=sum(v["kind"]=="link" for m in manifests.values() for v in m.values()))
 finally:
  if container:run(["docker","rm","-f",container])
  if stopped:run(["systemctl","start",SERVICE])
  (STATE/"backup-restore-results-20261030.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
