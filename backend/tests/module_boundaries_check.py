import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
CORE_FILES = {"config.py", "database.py", "health.py", "schemas.py"}
DOMAIN_FILES = {
    "dashboard": {"__init__.py", "router.py"},
    "processes": {"__init__.py", "router.py", "schemas.py", "store.py"},
    "catalog": {"__init__.py", "router.py", "schemas.py", "store.py"},
    "documents": {"__init__.py", "router.py", "schemas.py", "store.py", "service.py"},
    "search": {"__init__.py", "router.py", "schemas.py", "store.py", "service.py"},
    "skills": {"__init__.py", "router.py", "schemas.py", "service.py"},
    "settings": {"__init__.py", "router.py", "schemas.py", "store.py"},
}


def _missing_files(directory: Path, required: set[str]) -> list[str]:
    present = {path.name for path in directory.iterdir() if path.is_file()}
    return sorted(required - present)


def _feature_imports(tree: ast.AST) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports_features = any(
                alias.name == "app.features"
                or alias.name.startswith("app.features.")
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports_features = (
                module == "app.features"
                or module.startswith("app.features.")
                or (
                    module == "app"
                    and any(alias.name == "features" for alias in node.names)
                )
                or (
                    node.level >= 2
                    and (
                        module == "features"
                        or module.startswith("features.")
                        or (
                            not module
                            and any(alias.name == "features" for alias in node.names)
                        )
                    )
                )
            )
        elif isinstance(node, ast.Attribute):
            imports_features = (
                isinstance(node.value, ast.Name)
                and node.value.id == "app"
                and node.attr == "features"
            )
        else:
            continue
        if imports_features:
            violations.append(ast.unparse(node))
    return violations


def _business_route(decorator: ast.expr) -> tuple[str, str] | None:
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "app"
        and decorator.func.attr in {"get", "post", "put", "delete"}
    ):
        return None
    path = decorator.args[0] if decorator.args else next(
        (keyword.value for keyword in decorator.keywords if keyword.arg == "path"),
        None,
    )
    if (
        isinstance(path, ast.Constant)
        and isinstance(path.value, str)
        and path.value.startswith("/api/")
    ):
        return decorator.func.attr, path.value
    return None


def main() -> None:
    core_dir = APP_DIR / "core"
    missing_core = _missing_files(core_dir, CORE_FILES)
    assert not missing_core, {"core": missing_core}

    core_feature_imports = {}
    for path in core_dir.rglob("*.py"):
        violations = _feature_imports(ast.parse(path.read_text(encoding="utf-8")))
        if violations:
            core_feature_imports[str(path.relative_to(APP_DIR))] = violations
    assert not core_feature_imports, core_feature_imports

    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    business_decorators = []
    for node in ast.walk(main_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if route := _business_route(decorator):
                business_decorators.append(route)
    assert not business_decorators, business_decorators

    features_dir = APP_DIR / "features"
    for domain, required in DOMAIN_FILES.items():
        missing = _missing_files(features_dir / domain, required)
        assert not missing, {domain: missing}

    print("backend-module-boundaries-check: ok")


if __name__ == "__main__":
    main()
