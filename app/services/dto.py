from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CustomerDTO:
    id: int
    uuid: str
    name: str
    company_name: str
    phone: str
    email: str
    telegram: str
    position: str
    notes: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DealDTO:
    id: int
    uuid: str
    title: str
    customer_id: int
    customer_name: str
    amount: Decimal
    stage: str
    description: str
    expected_close_date: date | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TaskDTO:
    id: int
    uuid: str
    title: str
    description: str
    customer_id: int | None
    customer_name: str
    deal_id: int | None
    deal_title: str
    due_date: date | None
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardDTO:
    customer_count: int
    active_deal_count: int
    active_deal_amount: float
    tasks_today: int
    overdue_tasks: int
    latest_deals: tuple[DealDTO, ...]
    upcoming_tasks: tuple[TaskDTO, ...]

