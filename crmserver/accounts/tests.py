from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from rest_framework.test import APIClient

from accounts.models import Membership, Organization
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task

User = get_user_model()
PASSWORD = 'Test-only-Long-Password!725'


class AccountsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Организация А')
        self.other_org = Organization.objects.create(name='Организация Б')
        self.users = {}
        for role in Membership.Role.values:
            user = User.objects.create_user(role, password=PASSWORD)
            Membership.objects.create(user=user, organization=self.org, role=role)
            self.users[role] = user
        self.other_user = User.objects.create_user('other', password=PASSWORD)
        self.other_member = Membership.objects.create(user=self.other_user, organization=self.other_org, role='admin')
        self.customer = Customer.objects.create(organization=self.org, name='Наш клиент')
        self.deal = Deal.objects.create(organization=self.org, customer=self.customer, title='Наша сделка', amount=100)
        self.task = Task.objects.create(organization=self.org, title='Наша задача')
        self.foreign_customer = Customer.objects.create(organization=self.other_org, name='Секретный клиент')
        self.foreign_deal = Deal.objects.create(organization=self.other_org, customer=self.foreign_customer,
                                                title='Секретная сделка', amount=999)
        self.foreign_task = Task.objects.create(organization=self.other_org, title='Секретная задача')
        self.api = APIClient()

    def sign_in(self, role='admin'):
        self.client.force_login(self.users[role])
        self.api.force_login(self.users[role])

    def test_anonymous_and_membershipless_denied(self):
        for url in ['/dashboard/', '/customers/', '/deals/', '/tasks/', '/profile/', '/settings/users/']:
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertTrue(self.client.get(url).url.startswith('/login/?next='))
        for resource in ['customers', 'deals', 'tasks']:
            self.assertEqual(self.api.get(f'/api/{resource}/').status_code, 403)
            self.assertEqual(self.api.post(f'/api/{resource}/', {}).status_code, 403)
        user = User.objects.create_user('unattached', password=PASSWORD)
        self.client.force_login(user)
        self.api.force_login(user)
        self.assertEqual(self.client.get('/profile/').status_code, 200)
        self.assertEqual(self.client.get('/dashboard/').status_code, 403)
        self.assertEqual(self.api.get('/api/customers/').status_code, 403)

    def test_registration_login_logout_profile_and_safe_next(self):
        response = self.client.post('/register/', {'username': 'new-owner', 'organization_name': 'Новая организация',
            'password1': PASSWORD, 'password2': PASSWORD, 'role': 'manager', 'organization': self.other_org.pk})
        self.assertRedirects(response, '/dashboard/')
        user = User.objects.get(username='new-owner')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.membership.role, 'admin')
        self.assertNotEqual(user.membership.organization_id, self.other_org.pk)
        self.assertEqual(self.client.get('/dashboard/').context['customer_count'], 0)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/logout/'), '/')
        self.assertFalse(self.client.get('/').wsgi_request.user.is_authenticated)
        self.assertEqual(self.client.post('/login/', {'username': user.username, 'password': 'wrong'}).status_code, 200)
        response = self.client.post('/login/', {'username': user.username, 'password': PASSWORD, 'next': 'https://evil.example/'})
        self.assertRedirects(response, '/dashboard/')
        response = self.client.post('/profile/', {'first_name': 'Анна', 'last_name': 'Тест', 'email': 'a@example.test',
            'is_staff': True, 'is_superuser': True, 'role': 'admin', 'organization': self.other_org.pk})
        self.assertRedirects(response, '/profile/')
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Анна')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotEqual(user.membership.organization_id, self.other_org.pk)

    def test_invalid_registration_is_atomic(self):
        count = Organization.objects.count()
        for payload in [
            {'username': 'admin', 'organization_name': 'X', 'password1': PASSWORD, 'password2': PASSWORD},
            {'username': 'new', 'organization_name': 'X', 'password1': '123', 'password2': '456'},
            {'username': 'new', 'organization_name': ' ', 'password1': PASSWORD, 'password2': PASSWORD},
        ]:
            self.assertEqual(self.client.post('/register/', payload).status_code, 200)
        self.assertEqual(Organization.objects.count(), count)
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_each_role_isolation_lists_dashboard_and_direct_urls(self):
        for role in Membership.Role.values:
            with self.subTest(role=role):
                self.sign_in(role)
                dashboard = self.client.get('/dashboard/')
                self.assertEqual(dashboard.context['customer_count'], 1)
                self.assertEqual(dashboard.context['active_amount'], 100)
                self.assertNotContains(dashboard, 'Секретная')
                for resource, own, foreign in [('customers', self.customer, self.foreign_customer),
                                               ('deals', self.deal, self.foreign_deal),
                                               ('tasks', self.task, self.foreign_task)]:
                    self.assertEqual(list(self.client.get(f'/{resource}/').context['records']), [own])
                    data = self.api.get(f'/api/{resource}/').data
                    self.assertEqual([row['id'] for row in data['results']], [own.pk])
                    self.assertEqual(self.api.get(f'/api/{resource}/', {'search': 'Секрет'}).data['count'], 0)
                    for action in ['edit', 'delete']:
                        url = f'/{resource}/{foreign.pk}/{action}/'
                        self.assertEqual(self.client.get(url).status_code, 404)
                        self.assertEqual(self.client.post(url, {}).status_code, 404)
                    url = f'/api/{resource}/{foreign.pk}/'
                    for method in ['get', 'put', 'patch', 'delete']:
                        self.assertEqual(getattr(self.api, method)(url).status_code, 404)
        self.api.force_login(self.other_user)
        self.assertEqual(self.api.get('/api/customers/').data['results'][0]['id'], self.foreign_customer.pk)

    def test_each_role_can_crud_all_entities(self):
        for role in Membership.Role.values:
            self.sign_in(role)
            for resource, model, payload in [
                ('customers', Customer, {'name': 'Тест'}),
                ('deals', Deal, {'title': 'Тест', 'customer_id': self.customer.pk, 'stage': 'Новая'}),
                ('tasks', Task, {'title': 'Тест', 'deal_id': self.deal.pk, 'priority': 'Обычный', 'status': 'Новая'}),
            ]:
                with self.subTest(role=role, resource=resource):
                    result = self.api.post(f'/api/{resource}/', {**payload, 'organization': self.other_org.pk}, format='json')
                    self.assertEqual(result.status_code, 201, result.data)
                    obj = model.objects.get(pk=result.data['id'])
                    self.assertEqual(obj.organization_id, self.org.pk)
                    detail = f'/api/{resource}/{obj.pk}/'
                    self.assertEqual(self.api.put(detail, payload, format='json').status_code, 200)
                    self.assertEqual(self.api.patch(detail, {'organization': self.other_org.pk}, format='json').status_code, 200)
                    obj.refresh_from_db()
                    self.assertEqual(obj.organization_id, self.org.pk)
                    self.assertEqual(self.api.delete(detail).status_code, 204)
                    web_payload = {key.removesuffix('_id'): value for key, value in payload.items()}
                    self.assertEqual(self.client.post(f'/{resource}/new/', web_payload).status_code, 302)
                    obj = model.objects.latest('pk')
                    self.assertEqual(obj.organization_id, self.org.pk)
                    self.assertEqual(self.client.post(f'/{resource}/{obj.pk}/edit/', web_payload).status_code, 302)
                    self.assertEqual(self.client.post(f'/{resource}/{obj.pk}/delete/').status_code, 302)

    def test_foreign_relations_rejected_in_forms_and_api(self):
        self.sign_in()
        for resource in ['deals', 'tasks']:
            form = self.client.get(f'/{resource}/new/').context['form']
            self.assertEqual(list(form.fields['customer'].queryset), [self.customer])
        form = self.client.get('/tasks/new/').context['form']
        self.assertEqual(list(form.fields['deal'].queryset), [self.deal])
        for resource, field, foreign in [('deals', 'customer', self.foreign_customer),
                                         ('tasks', 'customer', self.foreign_customer), ('tasks', 'deal', self.foreign_deal)]:
            payload = {'title': 'Bad', f'{field}_id': foreign.pk}
            self.assertEqual(self.api.post(f'/api/{resource}/', payload).status_code, 400)
            own = self.deal if resource == 'deals' else self.task
            self.assertEqual(self.api.patch(f'/api/{resource}/{own.pk}/', payload).status_code, 400)
            payload = {'title': 'Bad', field: foreign.pk, 'priority': 'Обычный', 'status': 'Новая', 'stage': 'Новая'}
            response = self.client.post(f'/{resource}/new/', payload)
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context['form'].errors)
        with self.assertRaises(ValidationError):
            Deal(organization=self.org, customer=self.foreign_customer, title='Bad').full_clean()

    def test_admin_management_role_changes_removal_and_last_admin(self):
        self.sign_in()
        self.assertEqual(self.client.get('/settings/users/').status_code, 200)
        self.assertNotContains(self.client.get('/settings/users/'), '>other<')
        response = self.client.post('/settings/users/new/', {'username': 'invited', 'password1': PASSWORD,
            'password2': PASSWORD, 'role': 'supervisor', 'organization': self.other_org.pk, 'is_superuser': True})
        self.assertRedirects(response, '/settings/users/')
        user = User.objects.get(username='invited')
        member = user.membership
        self.assertEqual(member.organization_id, self.org.pk)
        self.assertEqual(member.role, 'supervisor')
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.post(f'/settings/users/{member.pk}/role/', {'role': 'admin'}).status_code, 302)
        member.refresh_from_db()
        self.assertEqual(member.role, 'admin')
        self.assertEqual(self.client.post(f'/settings/users/{member.pk}/role/', {'role': 'invalid'}).status_code, 200)
        removed_client = Client()
        removed_client.force_login(user)
        self.assertEqual(self.client.get(f'/settings/users/{member.pk}/remove/').status_code, 200)
        self.assertTrue(Membership.objects.filter(pk=member.pk).exists())
        self.assertEqual(self.client.post(f'/settings/users/{member.pk}/remove/').status_code, 302)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertEqual(removed_client.get('/dashboard/').status_code, 403)
        self.assertEqual(removed_client.get('/api/customers/').status_code, 403)
        last = self.users['admin'].membership
        for url, payload in [(f'/settings/users/{last.pk}/role/', {'role': 'manager'}),
                             (f'/settings/users/{last.pk}/remove/', {})]:
            self.assertContains(self.client.post(url, payload), 'последнего администратора')
        self.assertEqual(Membership.objects.get(pk=last.pk).role, 'admin')
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())

    def test_management_permissions_and_cross_org_targets(self):
        for role in Membership.Role.values:
            self.sign_in(role)
            for url in ['/settings/users/', '/settings/users/new/',
                        f'/settings/users/{self.other_member.pk}/role/',
                        f'/settings/users/{self.other_member.pk}/remove/']:
                expected = (404 if str(self.other_member.pk) in url else 200) if role == 'admin' else 403
                self.assertEqual(self.client.get(url).status_code, expected)
                if role != 'admin' or str(self.other_member.pk) in url:
                    self.assertEqual(self.client.post(url, {'role': 'manager'}).status_code, expected)
            if role != 'admin':
                self.assertNotContains(self.client.get('/dashboard/'), 'href="/settings/users/"')
        member = self.users['manager'].membership
        member.role = 'admin'
        member.save()
        self.sign_in('manager')
        self.assertEqual(self.client.get('/settings/users/').status_code, 200)
        member.role = 'manager'
        member.save()
        self.assertEqual(self.client.get('/settings/users/').status_code, 403)
        user = self.users['manager']
        user.is_staff = True
        user.save()
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_csrf_login_logout_management_and_api(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/login/')
        self.assertEqual(client.post('/login/', {'username': 'admin', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(client.post('/register/', {}).status_code, 403)
        client.force_login(self.users['admin'])
        for url in ['/logout/', '/settings/users/new/', '/api/customers/']:
            self.assertEqual(client.post(url, {'name': 'Bad'}).status_code, 403)

    def test_dashboard_date_no_leading_zero(self):
        self.sign_in()
        with patch('web.views.timezone.localdate', return_value=date(2026, 9, 4)):
            page = self.client.get('/dashboard/')
        self.assertContains(page, 'Обзор вашей работы на 4 сентября 2026')
        self.assertNotContains(page, '&#x20;')
