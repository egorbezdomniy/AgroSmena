from alembic import context
from sqlalchemy import create_engine

from app.core.config import sqlite_url
from app.models import Base

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=sqlite_url(), target_metadata=Base.metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'])
else:
    engine = create_engine(sqlite_url())
    with engine.begin() as connection:
        run(connection)
    engine.dispose()
