from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, RecordMixin

if TYPE_CHECKING:
    from app.models.deal import Deal
    from app.models.task import Task


class Customer(RecordMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    telegram: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    deals: Mapped[list["Deal"]] = relationship(
        back_populates="customer", cascade="all, delete"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="customer")
