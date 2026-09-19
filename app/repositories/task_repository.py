from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models import Customer, Deal, Task
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    model = Task

    def _with_relations(self):
        return select(Task).options(joinedload(Task.customer), joinedload(Task.deal))

    def list(
        self,
        search: str = "",
        status: str | None = None,
        priority: str | None = None,
    ) -> list[Task]:
        statement = self._with_relations()
        if search.strip():
            pattern = f"%{search.strip().casefold()}%"
            statement = (
                statement.outerjoin(Customer, Task.customer_id == Customer.id)
                .outerjoin(Deal, Task.deal_id == Deal.id)
                .where(
                    or_(
                        func.casefold(Task.title).like(pattern),
                        func.casefold(Task.description).like(pattern),
                        func.casefold(Customer.name).like(pattern),
                        func.casefold(Deal.title).like(pattern),
                    )
                )
            )
        if status:
            statement = statement.where(Task.status == status)
        if priority:
            statement = statement.where(Task.priority == priority)
        statement = statement.order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc())
        return list(self.session.scalars(statement).unique().all())

    def upcoming(self, statuses: tuple[str, ...], limit: int = 5) -> list[Task]:
        statement = (
            self._with_relations()
            .where(Task.status.in_(statuses), Task.due_date >= date.today())
            .order_by(Task.due_date, Task.created_at)
            .limit(limit)
        )
        return list(self.session.scalars(statement).unique().all())

    def due_counts(self, statuses: tuple[str, ...]) -> tuple[int, int]:
        today = date.today()
        today_count = self.session.scalar(
            select(func.count(Task.id)).where(Task.status.in_(statuses), Task.due_date == today)
        )
        overdue_count = self.session.scalar(
            select(func.count(Task.id)).where(Task.status.in_(statuses), Task.due_date < today)
        )
        return int(today_count or 0), int(overdue_count or 0)
