from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.core.database import Database
from app.services import CustomerService, DashboardService, DealService, TaskService
from app.services.exceptions import ValidationError


class CrmServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "crm.db"
        self.database = Database(self.db_path)
        self.database.create_tables()
        factory = self.database.session_factory
        self.customers = CustomerService(factory)
        self.deals = DealService(factory)
        self.tasks = TaskService(factory)
        self.dashboard = DashboardService(factory)

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_complete_crud_search_filter_and_dashboard_flow(self) -> None:
        customer = self.customers.create(
            name="  Анна Петрова  ",
            company_name="Поле",
            phone="+7 999 111-22-33",
            email="anna@example.test",
            telegram="@anna",
            position="Директор",
            notes="Первый контакт",
        )
        self.assertEqual(customer.name, "Анна Петрова")
        self.assertEqual(len(customer.uuid), 36)
        self.assertEqual(len(self.customers.list("поле")), 1)

        updated = self.customers.update(
            customer.id,
            name="Анна Петрова",
            company_name="Новое поле",
            phone=customer.phone,
            email=customer.email,
            telegram=customer.telegram,
            position="CEO",
            notes=customer.notes,
        )
        self.assertEqual(updated.company_name, "Новое поле")
        self.assertEqual(self.customers.get(customer.id).position, "CEO")

        deal = self.deals.create(
            title="Поставка семян",
            customer_id=customer.id,
            amount="125000.50",
            stage="Переговоры",
            expected_close_date=date.today() + timedelta(days=10),
            description="Согласовать объём",
        )
        self.assertEqual(len(self.deals.list("СЕМЯН")), 1)
        self.assertEqual(len(self.deals.list(stage="Переговоры")), 1)
        self.assertEqual(len(self.deals.list(stage="Успешно")), 0)

        due_today = self.tasks.create(
            title="Позвонить клиенту",
            description="Уточнить условия",
            customer_id=customer.id,
            deal_id=deal.id,
            due_date=date.today(),
            priority="Высокий",
            status="Новая",
        )
        overdue = self.tasks.create(
            title="Отправить расчёт",
            description="",
            customer_id=customer.id,
            deal_id=None,
            due_date=date.today() - timedelta(days=1),
            priority="Обычный",
            status="В работе",
        )
        self.assertEqual(len(self.tasks.list("Позвонить")), 1)
        self.assertEqual(len(self.tasks.list(status="Новая", priority="Высокий")), 1)
        self.assertEqual(len(self.tasks.list(status="Выполнена")), 0)

        summary = self.dashboard.get_summary()
        self.assertEqual(summary.customer_count, 1)
        self.assertEqual(summary.active_deal_count, 1)
        self.assertAlmostEqual(summary.active_deal_amount, 125000.50)
        self.assertEqual(summary.tasks_today, 1)
        self.assertEqual(summary.overdue_tasks, 1)
        self.assertEqual(summary.latest_deals[0].id, deal.id)

        self.tasks.delete(due_today.id)
        self.tasks.delete(overdue.id)
        self.deals.delete(deal.id)
        self.customers.delete(customer.id)
        self.assertEqual(self.dashboard.get_summary().customer_count, 0)

    def test_validation(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Имя клиента"):
            self.customers.create(name="")
        customer = self.customers.create(name="Тест")
        with self.assertRaisesRegex(ValidationError, "Название сделки"):
            self.deals.create(
                title="", customer_id=customer.id, amount=0, stage="Новая"
            )
        with self.assertRaisesRegex(ValidationError, "отрицательной"):
            self.deals.create(
                title="Минус", customer_id=customer.id, amount=-1, stage="Новая"
            )
        with self.assertRaisesRegex(ValidationError, "Название задачи"):
            self.tasks.create(title="", priority="Обычный", status="Новая")

    def test_data_survives_database_reopen(self) -> None:
        customer = self.customers.create(name="Сохраняемый клиент")
        customer_uuid = customer.uuid
        self.database.dispose()

        reopened = Database(self.db_path)
        reopened.create_tables()
        try:
            saved = CustomerService(reopened.session_factory).list("Сохраняемый")
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].uuid, customer_uuid)
        finally:
            reopened.dispose()

    def test_deleting_parents_keeps_optional_task(self) -> None:
        customer = self.customers.create(name="Связанный клиент")
        deal = self.deals.create(
            title="Связанная сделка",
            customer_id=customer.id,
            amount=100,
            stage="Новая",
        )
        task = self.tasks.create(
            title="Связанная задача",
            customer_id=customer.id,
            deal_id=deal.id,
            due_date=None,
            priority="Обычный",
            status="Новая",
        )

        self.deals.delete(deal.id)
        self.assertIsNone(self.tasks.get(task.id).deal_id)
        self.customers.delete(customer.id)
        saved_task = self.tasks.get(task.id)
        self.assertIsNone(saved_task.customer_id)
        self.assertEqual(saved_task.title, "Связанная задача")

    def test_customer_delete_cascades_deals_and_preserves_tasks(self) -> None:
        customer = self.customers.create(name="Удаляемый клиент")
        other = self.customers.create(name="Другой клиент")
        deals = [self.deals.create(
            title=f"Сделка {index}", customer_id=customer.id, amount=100, stage="Новая"
        ) for index in range(2)]
        kept = self.deals.create(
            title="Оставить", customer_id=other.id, amount=200, stage="Новая"
        )
        task = self.tasks.create(
            title="Оставить задачу", customer_id=customer.id, deal_id=deals[0].id,
            priority="Обычный", status="Новая"
        )
        self.customers.delete(customer.id)
        self.assertEqual([item.id for item in self.customers.list()], [other.id])
        self.assertEqual([item.id for item in self.deals.list()], [kept.id])
        saved = self.tasks.get(task.id)
        self.assertIsNone(saved.customer_id)
        self.assertIsNone(saved.deal_id)

    def test_free_text_amount_validation(self) -> None:
        customer = self.customers.create(name="Клиент")
        for value in ("abc", "NaN", "Infinity", "-1", "1000000000000"):
            with self.subTest(amount=value), self.assertRaises(ValidationError):
                self.deals.create(
                    title="Сделка", customer_id=customer.id, amount=value, stage="Новая"
                )


if __name__ == "__main__":
    unittest.main()
