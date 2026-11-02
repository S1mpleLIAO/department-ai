"""Request-scoped business access. Never accepts a caller-supplied user identity."""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from fastapi import HTTPException

# Every exposed action has a server-side capability; deferred workflow actions are
# described separately so create never silently implies publishing.
MODULES = {"processes":"业务流程", "knowledge":"知识库", "skills":"技能", "catalog":"目录与用途", "assistant":"AI 助手"}
ACTION_LABELS = {"read":"查看已发布内容", "source_download":"下载文档原文", "source_read":"查看／下载技能源码",
 "create":"新增、维护本人草稿并提交审核", "edit_any":"修改已有资料并提交审核", "archive":"下架／归档", "publish_direct":"免审核直接发布",
 "reindex":"重建索引", "manage":"新增／修改／删除目录", "review":"审核提交内容", "publish":"发布已审核内容", "use":"使用"}
ACTIONS = {
 "processes": ["read","create","edit_any","archive","publish_direct","review","publish"],
 "knowledge": ["read","source_download","create","edit_any","archive","publish_direct","reindex","review","publish"],
 "skills": ["source_read","use","create","edit_any","archive","publish_direct","review","publish"],
 "assistant": ["use"],
 "catalog": ["read","manage"],
}
ALL_ACTIONS = frozenset(f"{module}.{action}" for module, actions in ACTIONS.items() for action in actions)


def validate_actions(actions):
    values = set(actions)
    if values - ALL_ACTIONS:
        raise HTTPException(422, "包含不支持的权限项")
    for module, names in ACTIONS.items():
        if module == "assistant":
            continue
        read = "source_read" if module == "skills" else "read"
        if any(f"{module}.{x}" in values for x in names if x not in (read,"use")) and f"{module}.{read}" not in values:
            raise HTTPException(422, f"{MODULES[module]}的操作权限必须同时包含查看权限")
    return sorted(values)


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str
    company_id: str
    superadmin: bool
    grants: dict
    must_change: bool

    def allowed(self, space, action):
        return self.superadmin or action in self.grants.get(space, ())

    def require(self, space, *actions):
        if not all(self.allowed(space, x) for x in actions):
            raise HTTPException(403, "没有此空间的操作权限")


class ScopedPool:
    """Explicit context travels with the pool, including threadpool/async work."""
    def __init__(self, pool, principal, space):
        self.pool, self.principal, self.space = pool, principal, space

    @contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            conn.execute("SELECT set_config('department.space',%s,true), set_config('department.user',%s,true)",
                         (self.space, self.principal.user_id))
            kinds = [m for m in ("processes","knowledge","skills") if
                     self.principal.allowed(self.space,m+".review") or self.principal.allowed(self.space,m+".publish")]
            conn.execute("SELECT set_config('department.review_kinds',%s,true)", (",".join(kinds),))
            yield conn


def scoped_settings(settings, principal, space):
    # Space names come only from validated spaces, user IDs only from the DB.
    return replace(settings, data_dir=settings.data_dir / "spaces" / space,
                   skill_dir=settings.skill_dir / "spaces" / space)


def preview_directory(request):
    return request.state.settings.data_dir / "users" / request.state.principal.user_id

