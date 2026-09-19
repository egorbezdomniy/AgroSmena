from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import sessionmaker

from app.core.constants import DEAL_STAGES
from app.models import Deal
from app.repositories import CustomerRepository, DealRepository
from app.services.dto import DealDTO
from app.services.exceptions import NotFoundError, ValidationError
from app.services.mappers import deal_to_dto


class DealService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def list(self, search: str = "", stage: str | None = None) -> list[DealDTO]:
        with self.session_factory() as session:
            return [deal_to_dto(item) for item in DealRepository(session).list(search, stage)]

    def get(self, deal_id: int) -> DealDTO:
        with self.session_factory() as session:
            deal = DealRepository(session).get(deal_id)
            if deal is None:
                raise NotFoundError("Сделка не найдена.")
            return deal_to_dto(deal)

    def create(self, **data) -> DealDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            if CustomerRepository(session).get(clean["customer_id"]) is None:
                raise ValidationError("Выбранный клиент не найден.")
            deal = Deal(**clean)
            DealRepository(session).add(deal)
            return deal_to_dto(deal)

    def update(self, deal_id: int, **data) -> DealDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            if CustomerRepository(session).get(clean["customer_id"]) is None:
                raise ValidationError("Выбранный клиент не найден.")
            repository = DealRepository(session)
            deal = repository.get(deal_id)
            if deal is None:
                raise NotFoundError("Сделка не найдена.")
            for field, value in clean.items():
                setattr(deal, field, value)
            session.flush()
            return deal_to_dto(deal)

    def change_stage(self, deal_id: int, stage: str) -> DealDTO:
        if stage not in DEAL_STAGES:
            raise ValidationError("Выберите корректную стадию сделки.")
        with self.session_factory.begin() as session:
            deal = DealRepository(session).get(deal_id)
            if deal is None:
                raise NotFoundError("Сделка не найдена.")
            deal.stage = stage
            session.flush()
            return deal_to_dto(deal)

    def delete(self, deal_id: int) -> None:
        with self.session_factory.begin() as session:
            repository = DealRepository(session)
            deal = repository.get(deal_id)
            if deal is None:
                raise NotFoundError("Сделка не найдена.")
            repository.delete(deal)

    @staticmethod
    def _validate(data: dict) -> dict:
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValidationError("Название сделки обязательно.")
        customer_id = data.get("customer_id")
        if customer_id is None:
            raise ValidationError("Клиент у сделки обязателен.")
        try:
            amount = Decimal(str(data.get("amount", 0))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise ValidationError("Введите корректную сумму сделки.") from None
        if not amount.is_finite():
            raise ValidationError("Введите корректную сумму сделки.")
        if amount < 0:
            raise ValidationError("Сумма сделки не может быть отрицательной.")
        if amount > Decimal("999999999999.99"):
            raise ValidationError("Сумма сделки слишком велика.")
        stage = str(data.get("stage", ""))
        if stage not in DEAL_STAGES:
            raise ValidationError("Выберите корректную стадию сделки.")
        close_date = data.get("expected_close_date")
        if close_date is not None and not isinstance(close_date, date):
            raise ValidationError("Введите корректную дату закрытия.")
        return {
            "title": title,
            "customer_id": int(customer_id),
            "amount": amount,
            "stage": stage,
            "description": str(data.get("description", "")).strip(),
            "expected_close_date": close_date,
        }
