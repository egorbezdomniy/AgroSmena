# Build with: python -m PyInstaller AgroSmena.spec
from pathlib import Path
import os

root = Path(SPECPATH)
debug_console = os.environ.get("AGROSMENA_BUILD_CONSOLE") == "1"
app_name = "AgroSmenaCRM-Debug" if debug_console else "AgroSmenaCRM"
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "assets" / "crm-logo.png"), "assets"),
        (str(root / "assets" / "chevron-down.svg"), "assets"),
        *[(str(path), str(path.parent.relative_to(root))) for path in (root / 'migrations').rglob('*')
          if path.is_file() and path.suffix in {'.py', '.mako'} and '__pycache__' not in path.parts],
    ],
    hiddenimports=["sqlalchemy.dialects.sqlite", "alembic", "alembic.ddl.sqlite"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["django", "rest_framework", "tkinter", "unittest", "pytest"],
    noarchive=False,
)
# Qt uses the unversioned ICU API supplied by Windows 10/11. Do not bundle
# incompatible ICU DLLs discovered in third-party tools on the build host PATH.
a.binaries = [
    entry for entry in a.binaries
    if not Path(entry[0]).name.lower().startswith(("icuuc", "icudt"))
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    strip=False,
    upx=False,
    console=debug_console,
    icon=str(root / "build" / "crm.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name=app_name,
)
