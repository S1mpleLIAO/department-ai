from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from app.db import ConflictError, NotFoundError, StoreError


SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESOURCE_KINDS = ("scripts", "references", "assets")
MANAGED_FRONTMATTER = {
    "name",
    "description",
    "disable-model-invocation",
    "user-invocable",
}


def _directory(root: Path, skill_name: str) -> Path:
    if not SKILL_NAME.fullmatch(skill_name):
        raise StoreError("技能名称必须使用英文小写、数字和短横线")
    root = root.resolve()
    directory = (root / skill_name).resolve()
    if directory.parent != root:
        raise StoreError("技能路径无效")
    return directory


def _read(directory: Path) -> dict[str, Any]:
    try:
        skill_file = directory / "SKILL.md"
        skill_text = skill_file.read_text(encoding="utf-8")
    except OSError as error:
        raise StoreError(f"技能文件损坏：{directory.name}") from error
    parts = skill_text.split("---", 2)
    if len(parts) != 3:
        raise StoreError(f"技能文件缺少 YAML frontmatter：{directory.name}")
    frontmatter = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    name = frontmatter.get("name", directory.name)
    description = frontmatter.get("description", "")
    if description.startswith('"'):
        try:
            description = json.loads(description)
        except ValueError:
            pass
    instructions = parts[2].strip() if len(parts) == 3 else ""
    updated_at = datetime.fromtimestamp(skill_file.stat().st_mtime, timezone.utc)
    resources = _list_resources(directory)
    return {
        "id": directory.name,
        "name": name,
        "description": description,
        "instructions": instructions,
        "enabled": frontmatter.get("disable-model-invocation") != "true",
        "valid": True,
        "error": "",
        "resources": resources,
        "resourceCounts": {
            kind: sum(item["kind"] == kind for item in resources)
            for kind in RESOURCE_KINDS
        },
        "updatedAt": updated_at.isoformat().replace("+00:00", "Z"),
    }


def _invalid_skill(directory: Path, error: StoreError) -> dict[str, Any]:
    resources = _list_resources(directory)
    updated_at = datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc)
    return {
        "id": directory.name,
        "name": directory.name,
        "description": "",
        "instructions": "",
        "enabled": False,
        "valid": False,
        "error": str(error),
        "resources": resources,
        "resourceCounts": {
            kind: sum(item["kind"] == kind for item in resources)
            for kind in RESOURCE_KINDS
        },
        "updatedAt": updated_at.isoformat().replace("+00:00", "Z"),
    }


def list_skills(root: Path) -> list[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    skills = []
    for directory in root.iterdir():
        if (
            directory.is_dir()
            and not directory.is_symlink()
            and SKILL_NAME.fullmatch(directory.name)
        ):
            try:
                skills.append(_read(directory))
            except StoreError as error:
                skills.append(_invalid_skill(directory, error))
    return sorted(skills, key=lambda item: item["updatedAt"], reverse=True)


def _preserved_frontmatter(directory: Path) -> list[str]:
    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        return []
    parts = skill_file.read_text(encoding="utf-8").split("---", 2)
    if len(parts) != 3:
        return []
    preserved = []
    for line in parts[1].splitlines():
        if line and not line[0].isspace() and ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in MANAGED_FRONTMATTER:
                continue
        preserved.append(line)
    while preserved and not preserved[-1].strip():
        preserved.pop()
    return preserved


def save_skill(root: Path, skill: dict[str, Any], current_name: str | None = None) -> dict[str, Any]:
    creating = current_name is None
    target = _directory(root, skill["name"])
    current = target if creating else _directory(root, current_name)
    if creating and target.exists():
        raise ConflictError("技能已存在")
    if not creating and not current.is_dir():
        raise NotFoundError("技能不存在")
    if current != target and target.exists():
        raise ConflictError("技能名称已存在")
    preserved_frontmatter = _preserved_frontmatter(current)
    if current != target:
        current.rename(target)
    target.mkdir(parents=True, exist_ok=not creating)
    frontmatter = [
        "---",
        f"name: {skill['name']}",
        f"description: {json.dumps(skill['description'], ensure_ascii=False)}",
    ]
    if not skill["enabled"]:
        frontmatter.append("disable-model-invocation: true")
        frontmatter.append("user-invocable: false")
    frontmatter.extend(preserved_frontmatter)
    skill_text = "\n".join([*frontmatter, "---", "", skill["instructions"].strip(), ""])
    skill_tmp = target / ".SKILL.md.tmp"
    skill_tmp.write_text(skill_text, encoding="utf-8")
    skill_tmp.replace(target / "SKILL.md")
    (target / "metadata.json").unlink(missing_ok=True)
    return _read(target)


def _resource_target(root: Path, skill_id: str, resource_path: str) -> tuple[Path, Path]:
    directory = _directory(root, skill_id)
    if not directory.is_dir():
        raise NotFoundError("技能不存在")
    if "\\" in resource_path:
        raise StoreError("技能资源路径无效")
    relative = PurePosixPath(resource_path)
    if (
        relative.is_absolute()
        or len(relative.parts) < 2
        or relative.parts[0] not in RESOURCE_KINDS
        or any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts)
    ):
        raise StoreError("技能资源必须位于 scripts、references 或 assets 目录")
    raw_target = directory.joinpath(*relative.parts)
    target = raw_target.resolve()
    if not target.is_relative_to(directory.resolve()):
        raise StoreError("技能资源路径无效")
    return directory, target


def _resource_info(directory: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    relative = path.relative_to(directory).as_posix()
    return {
        "path": relative,
        "kind": relative.split("/", 1)[0],
        "name": path.name,
        "size": stat.st_size,
        "updatedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _list_resources(directory: Path) -> list[dict[str, Any]]:
    resources = []
    for kind in RESOURCE_KINDS:
        resource_root = directory / kind
        if not resource_root.is_dir() or resource_root.is_symlink():
            continue
        for current, names, files in os.walk(resource_root, followlinks=False):
            current_path = Path(current)
            names[:] = [
                name for name in names
                if not name.startswith(".") and not (current_path / name).is_symlink()
            ]
            for name in files:
                path = current_path / name
                if name.startswith(".") or path.is_symlink() or not path.is_file():
                    continue
                resources.append(_resource_info(directory, path))
    return sorted(resources, key=lambda item: item["path"])


def save_skill_resource(
    root: Path,
    skill_id: str,
    resource_path: str,
    content: bytes,
    max_bytes: int = 20 * 1024 * 1024,
) -> dict[str, Any]:
    if len(content) > max_bytes:
        raise StoreError(f"技能资源不能超过 {max_bytes // (1024 * 1024)} MiB")
    directory, target = _resource_target(root, skill_id, resource_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(target)
    return _resource_info(directory, target)


def read_skill_resource(root: Path, skill_id: str, resource_path: str) -> Path:
    _directory_path, target = _resource_target(root, skill_id, resource_path)
    if not target.is_file() or target.is_symlink():
        raise NotFoundError("技能资源不存在")
    return target


def delete_skill_resource(root: Path, skill_id: str, resource_path: str) -> None:
    directory, target = _resource_target(root, skill_id, resource_path)
    if not target.is_file() or target.is_symlink():
        raise NotFoundError("技能资源不存在")
    target.unlink()
    kind_root = directory / PurePosixPath(resource_path).parts[0]
    parent = target.parent
    while parent != kind_root.parent and parent != directory:
        try:
            parent.rmdir()
        except OSError:
            break
        if parent == kind_root:
            break
        parent = parent.parent


def delete_skill(root: Path, skill_id: str) -> None:
    directory = _directory(root, skill_id)
    if not directory.is_dir():
        raise NotFoundError("技能不存在")
    shutil.rmtree(directory)
