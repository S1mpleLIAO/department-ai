"""Explicit deployment settings; a missing production setting never selects test state."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    root: Path
    harness: Path
    node: Path


def runtime_config():
    mode = os.getenv("DEPARTMENT_AI_RUNTIME_MODE", "isolated")
    if mode not in ("isolated", "production"):
        raise RuntimeError("DEPARTMENT_AI_RUNTIME_MODE must be isolated or production")
    if mode == "isolated" and not str(ROOT).endswith("runtime-data/worktrees/identity-access-20261028"):
        raise RuntimeError("Explicit production AI configuration is required outside the isolated worktree")
    raw = os.getenv("DEPARTMENT_AI_STATE_DIR", "")
    if not raw and mode == "production":
        raise RuntimeError("Production requires DEPARTMENT_AI_STATE_DIR")
    root = Path(raw or "/tmp/department-identity-ai-20261028")
    if not root.is_absolute() or root.resolve() != root:
        raise RuntimeError("AI state directory must be an absolute canonical path, without symlinks")
    # sockaddr_un is 108 bytes including NUL; the longest suffix is a UUID/space + socket.
    if len(os.fsencode(root / ("0" * 36 + "-senyuan") / "transport/web.sock")) > 103:
        raise RuntimeError("AI state directory is too long for Unix sockets")
    if mode == "production" and (root == Path("/") or any(root.is_relative_to(p) for p in
            (Path("/tmp"), Path("/var/tmp"), Path("/run"), ROOT))):
        raise RuntimeError("Production AI state must be persistent and outside temporary/code directories")
    if root.exists() and (not root.is_dir() or not ((root.stat().st_uid == os.geteuid() and not root.stat().st_mode & 0o077) or (os.geteuid() in (0,10001) and root.stat().st_uid==0 and root.stat().st_gid==10001 and not root.stat().st_mode & 0o027))):
        raise RuntimeError("AI state must be an owned private directory (0700)")
    harness = Path(os.getenv("DEPARTMENT_AI_HARNESS_DIR", "/root/liao/DepartmentKnowledgeBase/deepseek-harness"))
    node = Path(os.getenv("DEPARTMENT_AI_NODE", "/usr/local/lib/nodejs/node-v22.22.3-linux-x64/bin/node"))
    for path in (root, harness, node):
        if not path.is_absolute() or any(c in str(path) for c in (",", "\n", "\r")):
            raise RuntimeError("Invalid container bind source")
    return RuntimeConfig(mode, root, harness.resolve(), node.resolve())


def gateway_bindings(values, mode):
    if not values:
        raise RuntimeError("No AI origins configured")
    if mode == "isolated":
        ports = []
        for value in values.values():
            url = urlsplit(value)
            if url.scheme != "http" or url.hostname != "127.0.0.1" or url.port not in (3182,3183,3184):
                raise RuntimeError("Isolated gateway only binds 127.0.0.1:3182–3184")
            ports.append(url.port)
        return ports
    department = urlsplit(os.environ.get("DEPARTMENT_AUTH_ORIGIN", ""))
    if department.scheme != "https":
        raise RuntimeError("Production department origin must use HTTPS")
    hosts = []
    for value in values.values():
        url = urlsplit(value)
        if url.scheme != "https" or url.hostname == department.hostname or url.port not in (None,443):
            raise RuntimeError("Production AI needs separate HTTPS hosts from the department portal")
        hosts.append(url.hostname)
    if len(set(hosts)) != len(hosts):
        raise RuntimeError("AI spaces must not share a cookie host")
    port = int(os.environ.get("DEPARTMENT_AI_GATEWAY_PORT", "0"))
    if not 1024 <= port <= 65535:
        raise RuntimeError("Set an explicit loopback DEPARTMENT_AI_GATEWAY_PORT (1024–65535)")
    return [port]


@dataclass(frozen=True)
class PoolLimits:
    capacity: int
    idle_seconds: int
    min_available_mib: int

def pool_limits():
    def number(name, default, low, high):
        raw = os.getenv(name, str(default))
        if not raw.isdecimal() or not low <= int(raw) <= high:
            raise RuntimeError(f"{name} must be an integer between {low} and {high}")
        return int(raw)
    return PoolLimits(number("DEPARTMENT_AI_MAX_INSTANCES", 2, 1, 16),
                      number("DEPARTMENT_AI_IDLE_SECONDS", 900, 60, 86400),
                      number("DEPARTMENT_AI_MIN_AVAILABLE_MIB", 1200, 900, 65536))
