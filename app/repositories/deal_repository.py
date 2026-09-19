from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models import Customer, Deal
from app.repositories.base import BaseRepository


class DealRepository(BaseRepository[Deal]):
    model = Deal

    def list(self, search: str = "", stage: str | None = None) -> list[Deal]:
        statement = select(Deal).options(joinedload(Deal.customer)).join(Customer)
        if search.strip():
            pattern = f"%{search.strip().casefold()}%"
            statement = statement.where(
                or_(
                    func.casefold(Deal.title).like(pattern),
                    func.casefold(Customer.name).like(pattern),
                )
            )
        if stage:
            statement = statement.where(Deal.stage == stage)
        return list(self.session.scalars(statement.order_by(Deal.updated_at.desc())).unique().all())

    def latest(self, limit: int = 5) -> list[Deal]:
        statement = (
            select(Deal)
            .options(joinedload(Deal.customer))
            .order_by(Deal.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement).unique().all())

    def touch(self, deal: Deal) -> None:
        deal.updated_at = datetime.now()

    def active_stats(self, active_stages: tuple[str, ...]) -> tuple[int, float]:
        statement = select(func.count(Deal.id), func.coalesce(func.sum(Deal.amount), 0)).where(
            Deal.stage.in_(active_stages)
        )
        count, amount = self.session.execute(statement).one()
        return int(count), float(amount)
