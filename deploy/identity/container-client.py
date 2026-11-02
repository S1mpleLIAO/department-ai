#!/usr/bin/python3 -I
"""Unprivileged transport; no Docker socket or sudo capability."""
import base64,json,socket,sys
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(195)
    s.connect("/run/department-identity-acceptance/control.sock")
    s.sendall(json.dumps(sys.argv[1:]).encode()+b"\n")
    with s.makefile("rb") as stream:
        line=stream.readline(6*1024*1024)
    if not line:raise SystemExit("Restricted container broker unavailable or operation rejected")
    value=json.loads(line)
    sys.stdout.buffer.write(base64.b64decode(value["stdout"]))
    sys.stderr.buffer.write(base64.b64decode(value["stderr"]))
    sys.exit(value["code"])
