"""Application-level storage admission; never deletes persistent user material."""
import asyncio
from contextlib import asynccontextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
from fastapi import HTTPException

KEY=re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}-(zkxk|senyuan|shared)")
MiB=1024*1024

def limits():
    def number(name,default,low,high):
        raw=os.getenv(name,str(default))
        if not raw.isdecimal() or not low<=int(raw)<=high:raise RuntimeError("Invalid "+name)
        return int(raw)
    return {"bytes":number("DEPARTMENT_AI_USER_STORAGE_MIB",512,64,1048576)*MiB,
            "files":number("DEPARTMENT_AI_USER_FILE_LIMIT",10000,100,10000000),
            "free":number("DEPARTMENT_AI_MIN_FREE_MIB",2048,256,1048576)*MiB}

def inventory(folder):
    """lstat only: no file contents, hashes or symlink traversal."""
    size=count=links=0
    if not folder.exists():return {"bytes":0,"files":0,"symlinks":0}
    if folder.is_symlink():raise RuntimeError("Storage root is a symlink")
    for parent,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs[:]:
            if (Path(parent)/name).is_symlink():dirs.remove(name);links+=1
        for name in files:
            try:info=(Path(parent)/name).lstat()
            except FileNotFoundError:continue
            if stat.S_ISREG(info.st_mode):size+=info.st_size;count+=1
            elif stat.S_ISLNK(info.st_mode):links+=1
    return {"bytes":size,"files":count,"symlinks":links}

def report(root):
    root=Path(root); users={}
    for folder in sorted(root.iterdir()):
        if not KEY.fullmatch(folder.name):continue
        uid=folder.name.rsplit("-",1)[0]
        row=users.setdefault(uid,{"bytes":0,"files":0,"symlinks":0,"spaces":{}})
        values=inventory(folder)
        row["spaces"][folder.name.rsplit("-",1)[1]]=values
        for field in ("bytes","files","symlinks"):row[field]+=values[field]
    bound=limits()
    for row in users.values():row["overQuota"]=row["bytes"]>=bound["bytes"] or row["files"]>=bound["files"]
    return {"limits":bound,"freeBytes":shutil.disk_usage(root).free,"users":users}

def check(runtime,reserve=0,files=0):
    values=report(runtime.manager.root)
    row=values["users"].get(runtime.user,{"bytes":0,"files":0})
    if row["bytes"]+reserve>values["limits"]["bytes"] or row["files"]+files>values["limits"]["files"]:
        raise HTTPException(507,"个人 AI 存储额度不足；已有会话和文件保留，可继续下载，请联系管理员整理或调整额度")
    if values["freeBytes"]-reserve<values["limits"]["free"]:
        raise HTTPException(507,"服务器存储余量不足，暂停新增写入；已有文件保留并可下载")
    return values

@asynccontextmanager
async def admission(runtime,reserve=0,files=0,enabled=True):
    if not enabled:
        yield
        return
    # ponytail: four active instances; lstat scan per write. Cache only if measured slow.
    control=runtime.manager.root/".control";control.mkdir(mode=0o700,exist_ok=True)
    path=control/(".storage-"+runtime.user+".lock")
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        for _ in range(100):
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:await asyncio.sleep(.1)
        else:raise HTTPException(429,"本人另一项文件操作正在进行，请稍后重试")
        await asyncio.to_thread(check,runtime,reserve,files)
        yield
    finally:os.close(fd)

def cleanup_candidates(root,active_names,now=None):
    """Only explicit disposable markers created by this release are eligible."""
    now=time.time() if now is None else now
    result=[]
    if active_names:return result
    for home in Path(root).iterdir():
        if not KEY.fullmatch(home.name) or home.is_symlink():continue
        for stage in home.glob("reimbursement-*"):
            marker=stage/"input/.department-disposable.json"
            if not stage.is_dir() or stage.is_symlink() or marker.is_symlink():continue
            try:
                value=json.loads(marker.read_text())
                if value!={"kind":"reimbursement-stage","version":1}:continue
                if now-marker.stat().st_mtime<86400:continue
                if inventory(stage)["symlinks"]:continue
            except (OSError,ValueError):continue
            result.append(stage)
    return result
