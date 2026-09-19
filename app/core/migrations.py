"""Programmatic equivalent of `alembic upgrade head`, including frozen builds."""
import sqlite3
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(engine):
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')


def import_legacy_database(destination, legacy):
    """Copy an existing development database once; never delete the original."""
    if destination.exists() or not legacy.exists() or destination.resolve() == legacy.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.importing')
    try:
        with closing(sqlite3.connect(f'{legacy.resolve().as_uri()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise RuntimeError('Legacy SQLite integrity check failed')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
