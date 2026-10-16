from __future__ import annotations

from datetime import date
import json

from sqlalchemy.orm import sessionmaker

from app.core.constants import ACTIVE_DEAL_STAGES, OPEN_TASK_STATUSES
from app.repositories import CustomerRepository, DealRepository, TaskRepository
from app.services.dto import DashboardDTO
from app.services.mappers import deal_to_dto, task_to_dto


class DashboardService:
    def __init__(self, session_factory: sessionmaker, username_provider=None) -> None:
        self.session_factory = session_factory
        self.username_provider = username_provider or (lambda: None)

    def get_summary(self) -> DashboardDTO:
        with self.session_factory() as session:
            customers = CustomerRepository(session)
            deals = DealRepository(session)
            tasks = TaskRepository(session)
            active_count, active_amount = deals.active_stats(ACTIVE_DEAL_STAGES)
            username = self.username_provider()
            visible = [item for item in tasks.list() if self._is_visible(item, username)]
            today = date.today()
            open_tasks = [item for item in visible if item.status in OPEN_TASK_STATUSES]
            today_count = sum(item.due_date == today for item in open_tasks)
            overdue_count = sum(item.due_date is not None and item.due_date < today for item in open_tasks)
            upcoming = sorted((item for item in open_tasks if item.due_date is not None and item.due_date >= today),
                              key=lambda item: (item.due_date, item.created_at))[:5]
            return DashboardDTO(
                customer_count=customers.count(),
                active_deal_count=active_count,
                active_deal_amount=active_amount,
                tasks_today=today_count,
                overdue_tasks=overdue_count,
                latest_deals=tuple(deal_to_dto(item) for item in deals.latest()),
                upcoming_tasks=tuple(task_to_dto(item) for item in upcoming),
            )

    @staticmethod
    def _is_visible(task, username) -> bool:
        try:
            assignees = json.loads(task.assignee_usernames or '[]')
        except (TypeError, ValueError):
            assignees = []
        if not isinstance(assignees, list):
            assignees = []
        return not assignees or bool(username and username in assignees)
