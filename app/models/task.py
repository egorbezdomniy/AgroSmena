from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, RecordMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.deal import Deal


class Task(RecordMixin, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deal_id: Mapped[int | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    priority: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    customer: Mapped["Customer | None"] = relationship(back_populates="tasks")
    deal: Mapped["Deal | None"] = relationship(back_populates="tasks")

