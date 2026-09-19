from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, record_id: int) -> ModelT | None:
        return self.session.get(self.model, record_id)

    def add(self, record: ModelT) -> ModelT:
        self.session.add(record)
        self.session.flush()
        return record

    def delete(self, record: ModelT) -> None:
        self.session.delete(record)
        self.session.flush()

    def all(self) -> list[ModelT]:
        return list(self.session.scalars(select(self.model)).all())

