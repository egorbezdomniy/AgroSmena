from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.core.constants import ACTIVE_DEAL_STAGES, OPEN_TASK_STATUSES
from app.repositories import CustomerRepository, DealRepository, TaskRepository
from app.services.dto import DashboardDTO
from app.services.mappers import deal_to_dto, task_to_dto


class DashboardService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def get_summary(self) -> DashboardDTO:
        with self.session_factory() as session:
            customers = CustomerRepository(session)
            deals = DealRepository(session)
            tasks = TaskRepository(session)
            active_count, active_amount = deals.active_stats(ACTIVE_DEAL_STAGES)
            today_count, overdue_count = tasks.due_counts(OPEN_TASK_STATUSES)
            return DashboardDTO(
                customer_count=customers.count(),
                active_deal_count=active_count,
                active_deal_amount=active_amount,
                tasks_today=today_count,
                overdue_tasks=overdue_count,
                latest_deals=tuple(deal_to_dto(item) for item in deals.latest()),
                upcoming_tasks=tuple(task_to_dto(item) for item in tasks.upcoming(OPEN_TASK_STATUSES)),
            )

