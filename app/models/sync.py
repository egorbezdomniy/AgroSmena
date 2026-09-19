from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncState(Base):
    __tablename__ = 'sync_state'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    server_url: Mapped[str] = mapped_column(String(500))
    organization_uuid: Mapped[str] = mapped_column(String(36))
    organization_name: Mapped[str] = mapped_column(String(200))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SyncDeletion(Base):
    __tablename__ = 'sync_deletions'
    entity: Mapped[str] = mapped_column(String(20), primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class SavedSyncLogin(Base):
    __tablename__ = 'saved_sync_login'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    server_url: Mapped[str] = mapped_column(String(500))
    organization_uuid: Mapped[str] = mapped_column(String(36))
    organization_name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(150))
    protected_token: Mapped[str] = mapped_column(String(8192))
