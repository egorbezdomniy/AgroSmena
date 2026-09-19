from __future__ import annotations

from datetime import date

from sqlalchemy.orm import sessionmaker

from app.core.constants import TASK_PRIORITIES, TASK_STATUSES
from app.models import Task
from app.repositories import CustomerRepository, DealRepository, TaskRepository
from app.services.dto import TaskDTO
from app.services.exceptions import NotFoundError, ValidationError
from app.services.mappers import task_to_dto


class TaskService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def list(
        self, search: str = "", status: str | None = None, priority: str | None = None
    ) -> list[TaskDTO]:
        with self.session_factory() as session:
            items = TaskRepository(session).list(search, status, priority)
            return [task_to_dto(item) for item in items]

    def get(self, task_id: int) -> TaskDTO:
        with self.session_factory() as session:
            task = TaskRepository(session).get(task_id)
            if task is None:
                raise NotFoundError("Задача не найдена.")
            return task_to_dto(task)

    def create(self, **data) -> TaskDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            self._validate_relations(session, clean)
            task = Task(**clean)
            TaskRepository(session).add(task)
            return task_to_dto(task)

    def update(self, task_id: int, **data) -> TaskDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            self._validate_relations(session, clean)
            repository = TaskRepository(session)
            task = repository.get(task_id)
            if task is None:
                raise NotFoundError("Задача не найдена.")
            for field, value in clean.items():
                setattr(task, field, value)
            session.flush()
            return task_to_dto(task)

    def delete(self, task_id: int) -> None:
        with self.session_factory.begin() as session:
            repository = TaskRepository(session)
            task = repository.get(task_id)
            if task is None:
                raise NotFoundError("Задача не найдена.")
            repository.delete(task)

    @staticmethod
    def _validate(data: dict) -> dict:
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValidationError("Название задачи обязательно.")
        priority = str(data.get("priority", ""))
        status = str(data.get("status", ""))
        if priority not in TASK_PRIORITIES:
            raise ValidationError("Выберите корректный приоритет.")
        if status not in TASK_STATUSES:
            raise ValidationError("Выберите корректный статус.")
        due_date = data.get("due_date")
        if due_date is not None and not isinstance(due_date, date):
            raise ValidationError("Введите корректный срок задачи.")
        return {
            "title": title,
            "description": str(data.get("description", "")).strip(),
            "customer_id": int(data["customer_id"]) if data.get("customer_id") else None,
            "deal_id": int(data["deal_id"]) if data.get("deal_id") else None,
            "due_date": due_date,
            "priority": priority,
            "status": status,
        }

    @staticmethod
    def _validate_relations(session, data: dict) -> None:
        customer_id = data["customer_id"]
        deal_id = data["deal_id"]
        if customer_id and CustomerRepository(session).get(customer_id) is None:
            raise ValidationError("Выбранный клиент не найден.")
        if deal_id:
            deal = DealRepository(session).get(deal_id)
            if deal is None:
                raise ValidationError("Выбранная сделка не найдена.")
            if customer_id and deal.customer_id != customer_id:
                raise ValidationError("Выбранная сделка принадлежит другому клиенту.")

