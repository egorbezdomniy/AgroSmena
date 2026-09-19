from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALL_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else PROJECT_ROOT
USER_ROOT = Path(os.environ.get('AGROSMENA_DATA_ROOT') or (
    Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'AgroSmenaCRM'))
DATA_DIR = USER_ROOT / 'data'
DATABASE_PATH = DATA_DIR / "crm.db"


def sqlite_url(path: Path = DATABASE_PATH) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"
