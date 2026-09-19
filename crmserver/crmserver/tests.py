import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from accounts.models import Organization, Membership
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task


class CRMApiTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Тестовая организация')
        self.user = get_user_model().objects.create_user('crm-user', password='Test-only-724!pass')
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.Role.ADMIN)
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(organization=self.org, name='Тестовый клиент')
        self.deal = Deal.objects.create(organization=self.org, title='Сделка', customer=self.customer)

    def exercise_crud(self, resource, payload, patch, model):
        url = f'/api/{resource}/'
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        record = response.data
        uuid.UUID(record['uuid'])
        self.assertTrue(record['created_at'])
        self.assertTrue(record['updated_at'])
        detail = f"{url}{record['id']}/"
        self.assertEqual(self.client.get(detail).status_code, 200)
        listing = self.client.get(url)
        self.assertEqual(listing.status_code, 200)
        self.assertIn(record['id'], [row['id'] for row in listing.data['results']])
        updated = self.client.put(detail, payload, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        updated = self.client.patch(detail, {**patch, 'uuid': str(uuid.uuid4()),
                                             'created_at': '2000-01-01T00:00:00Z'}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        for key, value in patch.items():
            self.assertEqual(updated.data[key], value)
        self.assertEqual(updated.data['uuid'], record['uuid'])
        self.assertEqual(updated.data['created_at'], record['created_at'])
        self.assertGreater(updated.data['updated_at'], record['updated_at'])
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertFalse(model.objects.filter(pk=record['id']).exists())
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_customer_crud(self):
        self.exercise_crud('customers', {
            'name': 'Анна', 'company_name': 'Агро', 'phone': '+79991234567',
            'email': 'anna@example.test', 'telegram': '@anna', 'position': 'Директор', 'notes': 'Заметка'
        }, {'name': 'Анна Петрова'}, Customer)

    def test_deal_crud(self):
        self.exercise_crud('deals', {
            'title': 'Продажа', 'customer_id': self.customer.id, 'amount': '1250.50',
            'stage': 'Предложение', 'expected_close_date': '2026-10-01', 'description': 'Описание'
        }, {'stage': 'Успешно'}, Deal)

    def test_task_crud(self):
        self.exercise_crud('tasks', {
            'title': 'Позвонить', 'description': 'Описание', 'customer_id': self.customer.id,
            'deal_id': self.deal.id, 'due_date': '2026-10-01', 'priority': 'Высокий', 'status': 'Новая'
        }, {'status': 'Выполнена'}, Task)

    def test_task_optional_relations(self):
        response = self.client.post('/api/tasks/', {'title': 'Без связей'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['customer_id'])
        self.assertIsNone(response.data['deal_id'])
        self.assertIsNone(response.data['due_date'])
        response = self.client.post('/api/tasks/', {
            'title': 'Только сделка', 'deal_id': self.deal.id, 'customer_id': None
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_validation_errors(self):
        cases = [
            ('customers', {'name': '   '}),
            ('customers', {'name': 'Клиент', 'email': 'invalid'}),
            ('deals', {'title': 'Нет клиента'}),
            ('deals', {'title': 'Тест', 'customer_id': 999999}),
            ('deals', {'title': 'Тест', 'customer_id': self.customer.id, 'amount': '-1'}),
            ('deals', {'title': 'Тест', 'customer_id': self.customer.id, 'stage': 'invalid'}),
            ('tasks', {'title': ' '}),
            ('tasks', {'title': 'Тест', 'status': 'invalid'}),
            ('tasks', {'title': 'Тест', 'priority': 'invalid'}),
            ('tasks', {'title': 'Тест', 'deal_id': 999999}),
            ('tasks', {'title': 'Тест', 'due_date': 'invalid'}),
        ]
        for resource, payload in cases:
            with self.subTest(resource=resource, payload=payload):
                self.assertEqual(self.client.post(f'/api/{resource}/', payload, format='json').status_code, 400)

    def test_task_relation_validation_including_partial_update(self):
        other = Customer.objects.create(organization=self.org, name='Другой клиент')
        payload = {'title': 'Тест', 'customer_id': other.id, 'deal_id': self.deal.id}
        self.assertEqual(self.client.post('/api/tasks/', payload, format='json').status_code, 400)
        task = Task.objects.create(organization=self.org, title='Тест', customer=self.customer, deal=self.deal)
        detail = f'/api/tasks/{task.id}/'
        self.assertEqual(self.client.patch(detail, {'customer_id': other.id}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(detail, {'customer_id': None}, format='json').status_code, 200)

    def test_delete_cascade_preserves_tasks_and_other_customers(self):
        other = Customer.objects.create(organization=self.org, name='Не удалять')
        task = Task.objects.create(organization=self.org, title='Задача', customer=self.customer, deal=self.deal)
        self.assertEqual(self.client.delete(f'/api/customers/{self.customer.id}/').status_code, 204)
        self.assertFalse(Deal.objects.filter(id=self.deal.id).exists())
        self.assertTrue(Customer.objects.filter(id=other.id).exists())
        task.refresh_from_db()
        self.assertIsNone(task.customer_id)
        self.assertIsNone(task.deal_id)

    def test_amount_has_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Deal.objects.create(organization=self.org, title='Отрицательная', customer=self.customer, amount=Decimal('-1'))

    def test_search(self):
        response = self.client.get('/api/customers/', {'search': 'Тестовый'})
        self.assertEqual(response.data['count'], 1)

    def test_admin_pages(self):
        user = get_user_model().objects.create_superuser('admin', password='test-password-only')
        self.client.force_login(user)
        for app, model in [('customers', 'customer'), ('deals', 'deal'), ('tasks', 'task')]:
            self.assertEqual(self.client.get(f'/admin/{app}/{model}/').status_code, 200)
