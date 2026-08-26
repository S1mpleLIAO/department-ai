import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
DOMAIN_FILES = {
    "dashboard": {"__init__.py", "router.py"},
    "processes": {"__init__.py", "router.py", "schemas.py", "store.py"},
    "catalog": {"__init__.py", "router.py", "schemas.py", "store.py"},
    "documents": {"__init__.py", "router.py", "schemas.py", "store.py", "service.py"},
    "search": {"__init__.py", "router.py", "schemas.py", "store.py", "service.py"},
    "skills": {"__init__.py", "router.py", "schemas.py", "service.py"},
    "settings": {"__init__.py", "router.py", "schemas.py", "store.py"},
}


def main() -> None:
    core_sources = [
        path.read_text(encoding="utf-8")
        for path in (APP_DIR / "core").rglob("*.py")
    ]
    assert not any("app.features" in source for source in core_sources)

    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    business_decorators = []
    for node in ast.walk(main_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr in {"get", "post", "put", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
                and decorator.args[0].value.startswith("/api/")
            ):
                business_decorators.append(
                    (decorator.func.attr, decorator.args[0].value)
                )
    assert not business_decorators, business_decorators

    features_dir = APP_DIR / "features"
    for domain, required in DOMAIN_FILES.items():
        present = {
            path.name
            for path in (features_dir / domain).iterdir()
            if path.is_file()
        }
        assert required <= present, {domain: sorted(required - present)}

    print("backend-module-boundaries-check: ok")


if __name__ == "__main__":
    main()
