from __future__ import annotations

import ast
from pathlib import Path


def test_domain_package_does_not_import_sqlalchemy_or_alembic() -> None:
    domain_root = Path("src/pig/domain")
    imported_modules: list[str] = []
    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)

    assert not any(name.startswith("sqlalchemy") for name in imported_modules)
    assert not any(name.startswith("alembic") for name in imported_modules)


def test_desktop_window_does_not_bypass_application_boundary() -> None:
    path = Path("src/pig/ui/main_window.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden = (
        "sqlalchemy",
        "alembic",
        "pig.infrastructure",
        "pig.handlers",
    )
    assert not any(
        name.startswith(prefix)
        for name in imported_modules
        for prefix in forbidden
    )
