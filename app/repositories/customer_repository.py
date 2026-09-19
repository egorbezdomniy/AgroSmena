from __future__ import annotations

from sqlalchemy import func, or_, select

from app.models import Customer, Deal
from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    def list(self, search: str = "") -> list[Customer]:
        statement = select(Customer)
        if search.strip():
            pattern = f"%{search.strip().casefold()}%"
            statement = statement.where(
                or_(
                    func.casefold(Customer.name).like(pattern),
                    func.casefold(Customer.company_name).like(pattern),
                    func.casefold(Customer.phone).like(pattern),
                    func.casefold(Customer.email).like(pattern),
                    func.casefold(Customer.telegram).like(pattern),
                )
            )
        return list(self.session.scalars(statement.order_by(Customer.name)).all())

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(Customer.id))) or 0)

    def deal_count(self, customer_id: int) -> int:
        statement = select(func.count(Deal.id)).where(Deal.customer_id == customer_id)
        return int(self.session.scalar(statement) or 0)
