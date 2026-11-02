#!/usr/bin/python3 -I
"""Privileged fixed-container broker, local socket only, peer UID 10001 only."""
import base64
import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import threading

SOCKET="/run/department-identity-acceptance/control.sock"
HELPER=str(Path(__file__).resolve().parent/"launcher.py")
LIMIT=65536
slots=threading.BoundedSemaphore(12)
class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(200)
        _,uid,_=struct.unpack("3i",self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=10001:return
        if not slots.acquire(blocking=False):return
        try:
            line=self.rfile.readline(LIMIT+1)
            if len(line)>LIMIT or not line.endswith(b"\n"):return
            args=json.loads(line)
            if not isinstance(args,list) or not all(isinstance(x,str) for x in args):return
            r=subprocess.run([HELPER,*args],capture_output=True,timeout=190,
                             env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","DEPARTMENT_PEER_UID":"10001","LANG":"C.UTF-8"})
            if len(r.stdout)+len(r.stderr)>4*1024*1024:return
            self.wfile.write(json.dumps({"code":r.returncode,"stdout":base64.b64encode(r.stdout).decode(),
                                        "stderr":base64.b64encode(r.stderr).decode()}).encode()+b"\n")
        except (OSError,ValueError,subprocess.SubprocessError):return
        finally:slots.release()
class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
if __name__=="__main__":
    p=Path(SOCKET)
    if p.exists():p.unlink()
    with Server(SOCKET,Handler) as server:
        os.chown(p,0,10001);p.chmod(0o660)
        server.serve_forever()
