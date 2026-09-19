from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.models import Customer
from app.repositories import CustomerRepository
from app.services.dto import CustomerDTO
from app.services.exceptions import NotFoundError, ValidationError
from app.services.mappers import customer_to_dto


class CustomerService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def list(self, search: str = "") -> list[CustomerDTO]:
        with self.session_factory() as session:
            return [customer_to_dto(item) for item in CustomerRepository(session).list(search)]

    def get(self, customer_id: int) -> CustomerDTO:
        with self.session_factory() as session:
            customer = CustomerRepository(session).get(customer_id)
            if customer is None:
                raise NotFoundError("Клиент не найден.")
            return customer_to_dto(customer)

    def create(self, **data) -> CustomerDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            customer = Customer(**clean)
            CustomerRepository(session).add(customer)
            return customer_to_dto(customer)

    def update(self, customer_id: int, **data) -> CustomerDTO:
        clean = self._validate(data)
        with self.session_factory.begin() as session:
            repository = CustomerRepository(session)
            customer = repository.get(customer_id)
            if customer is None:
                raise NotFoundError("Клиент не найден.")
            for field, value in clean.items():
                setattr(customer, field, value)
            session.flush()
            return customer_to_dto(customer)

    def delete(self, customer_id: int) -> None:
        with self.session_factory.begin() as session:
            repository = CustomerRepository(session)
            customer = repository.get(customer_id)
            if customer is None:
                raise NotFoundError("Клиент не найден.")
            repository.delete(customer)

    @staticmethod
    def _validate(data: dict) -> dict:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValidationError("Имя клиента обязательно.")
        return {
            "name": name,
            "company_name": str(data.get("company_name", "")).strip(),
            "phone": str(data.get("phone", "")).strip(),
            "email": str(data.get("email", "")).strip(),
            "telegram": str(data.get("telegram", "")).strip(),
            "position": str(data.get("position", "")).strip(),
            "notes": str(data.get("notes", "")).strip(),
        }
