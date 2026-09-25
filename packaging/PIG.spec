# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).parent
hidden_imports = (
    collect_submodules("extract_msg")
    + collect_submodules("py7zr")
    + ["sqlalchemy.dialects.sqlite.pysqlite"]
)
migrations_root = project_root / "migrations"
datas = [
    (str(project_root / "alembic.ini"), "."),
    (str(migrations_root / "env.py"), "migrations"),
    (str(migrations_root / "script.py.mako"), "migrations"),
] + [
    (str(path), "migrations/versions")
    for path in sorted((migrations_root / "versions").glob("*.py"))
]

a = Analysis(
    [str(project_root / "packaging" / "pig_desktop_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PIG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PIG",
)
