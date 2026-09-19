from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization, Membership
from django.contrib.auth import get_user_model
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task


class WebTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Тестовая организация')
        self.user = get_user_model().objects.create_user('crm-user', password='Test-only-724!pass')
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.Role.ADMIN)
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(organization=self.org, name='Анна', company_name='Агро')
        self.deal = Deal.objects.create(organization=self.org, title='Семена', customer=self.customer, amount=Decimal('1250.50'))
        self.task = Task.objects.create(organization=self.org, title='Позвонить', customer=self.customer, deal=self.deal)

    def test_navigation_and_all_forms(self):
        self.assertRedirects(self.client.get('/'), '/dashboard/')
        for section in ['dashboard', 'customers', 'deals', 'tasks']:
            response = self.client.get(reverse(f'web:{section}'))
            self.assertEqual(response.status_code, 200)
            for link in ['/dashboard/', '/customers/', '/deals/', '/tasks/']:
                self.assertContains(response, f'href="{link}"')
            self.assertContains(response, 'name="viewport"')
        for entity, instance in [('customer', self.customer), ('deal', self.deal), ('task', self.task)]:
            for action in ['create', 'edit', 'delete']:
                with self.subTest(entity=entity, action=action):
                    url = reverse(f'web:{entity}-{action}', args=[] if action == 'create' else [instance.pk])
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'csrfmiddlewaretoken')

    def exercise_crud(self, entity, model, payload, update):
        response = self.client.post(reverse(f'web:{entity}-create'), payload)
        self.assertEqual(response.status_code, 302)
        obj = model.objects.latest('id')
        original_uuid = obj.uuid
        response = self.client.post(reverse(f'web:{entity}-edit', args=[obj.pk]), {**payload, **update})
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.uuid, original_uuid)
        for key, value in update.items():
            self.assertEqual(getattr(obj, key), value)
        url = reverse(f'web:{entity}-delete', args=[obj.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(model.objects.filter(pk=obj.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(model.objects.filter(pk=obj.pk).exists())
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_customer_crud(self):
        self.exercise_crud('customer', Customer, {'name': 'Иван', 'email': 'ivan@example.com'}, {'company_name': 'Поле'})

    def test_deal_crud(self):
        self.exercise_crud('deal', Deal, {'title': 'Новая продажа', 'customer': self.customer.pk,
            'amount': '400.50', 'stage': 'Новая', 'expected_close_date': '2026-10-01'}, {'stage': 'Успешно'})

    def test_task_crud(self):
        self.exercise_crud('task', Task, {'title': 'Новая задача', 'customer': self.customer.pk,
            'deal': self.deal.pk, 'due_date': '2026-10-01', 'priority': 'Высокий', 'status': 'Новая'}, {'status': 'Выполнена'})

    def test_blank_amount_and_optional_task_relations(self):
        form = self.client.get(reverse('web:deal-create')).context['form']
        self.assertIsNone(form['amount'].value())
        response = self.client.post(reverse('web:deal-create'), {'title': 'Без суммы',
            'customer': self.customer.pk, 'amount': '', 'stage': 'Новая'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Deal.objects.latest('id').amount, Decimal('0'))
        response = self.client.post(reverse('web:task-create'), {'title': 'Без связей',
            'priority': 'Обычный', 'status': 'Новая'})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Task.objects.latest('id').deal_id)

    def test_validation_and_values_preserved(self):
        other = Customer.objects.create(organization=self.org, name='Другой')
        cases = [
            ('customer', {'name': ' '}, 'name'),
            ('customer', {'name': 'Анна', 'email': 'bad'}, 'email'),
            ('deal', {'title': 'Нет клиента', 'stage': 'Новая'}, 'customer'),
            ('deal', {'title': 'Минус', 'customer': self.customer.pk, 'amount': '-1', 'stage': 'Новая'}, 'amount'),
            ('deal', {'title': 'Нет клиента', 'customer': 999999, 'stage': 'Новая'}, 'customer'),
            ('task', {'title': 'Тест', 'customer': other.pk, 'deal': self.deal.pk,
                      'priority': 'Обычный', 'status': 'Новая'}, 'deal'),
            ('task', {'title': 'Тест', 'priority': 'Invalid', 'status': 'Новая'}, 'priority'),
            ('task', {'title': 'Тест', 'priority': 'Обычный', 'status': 'Новая', 'due_date': 'Invalid'}, 'due_date'),
        ]
        for entity, payload, field in cases:
            with self.subTest(entity=entity, field=field):
                response = self.client.post(reverse(f'web:{entity}-create'), payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertEqual(response.context['form'].data.dict(),
                                 {key: str(value) for key, value in payload.items()})

    def test_filters_search_and_pagination(self):
        Deal.objects.create(organization=self.org, title='Другая', customer=self.customer, stage='Успешно')
        self.assertEqual(self.client.get('/customers/', {'q': 'Агро'}).context['paginator'].count, 1)
        response = self.client.get('/deals/', {'q': 'Семена', 'stage': 'Новая'})
        self.assertEqual(list(response.context['records']), [self.deal])
        self.assertEqual(self.client.get('/deals/', {'stage': 'Проиграна'}).context['paginator'].count, 0)
        self.task.priority = 'Высокий'
        self.task.save()
        response = self.client.get('/tasks/', {'q': 'Позвонить', 'status': 'Новая', 'priority': 'Высокий'})
        self.assertEqual(list(response.context['records']), [self.task])
        self.assertEqual(self.client.get('/tasks/', {'priority': 'Низкий'}).context['paginator'].count, 0)
        for index in range(23):
            Task.objects.create(organization=self.org, title=f'Страница {index}', status='Новая', priority='Высокий')
        response = self.client.get('/tasks/', {'q': 'Страница', 'status': 'Новая', 'priority': 'Высокий', 'page': 2})
        self.assertEqual(len(response.context['records']), 3)
        self.assertContains(response, 'page=1')
        self.assertContains(response, 'priority=')

    def test_dashboard_statistics(self):
        today = timezone.localdate()
        Deal.objects.create(organization=self.org, title='Закрыта', customer=self.customer, stage='Успешно', amount=999)
        self.task.due_date = today
        self.task.save()
        Task.objects.create(organization=self.org, title='Просрочена', due_date=today - timedelta(days=1))
        Task.objects.create(organization=self.org, title='Завершена', due_date=today - timedelta(days=2), status='Выполнена')
        context = self.client.get('/dashboard/').context
        self.assertEqual(context['customer_count'], 1)
        self.assertEqual(context['active_deals'], 1)
        self.assertEqual(context['active_amount'], Decimal('1250.50'))
        self.assertEqual(context['tasks_today'], 1)
        self.assertEqual(context['overdue_tasks'], 1)
        self.assertEqual(context['pending_tasks'], 2)

    def test_customer_cascade_and_csrf(self):
        url = reverse('web:customer-delete', args=[self.customer.pk])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(url)
        self.assertContains(page, 'Удаление клиента также удалит все сделки')
        self.assertEqual(client.post(url).status_code, 403)
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())
        self.assertEqual(client.post(url, {'csrfmiddlewaretoken': client.cookies['csrftoken'].value}).status_code, 302)
        self.assertFalse(Deal.objects.filter(pk=self.deal.pk).exists())
        self.task.refresh_from_db()
        self.assertIsNone(self.task.customer_id)
        self.assertIsNone(self.task.deal_id)

    def test_html_is_escaped(self):
        self.customer.name = '<script>alert(1)</script>'
        self.customer.save()
        page = self.client.get('/customers/')
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')
