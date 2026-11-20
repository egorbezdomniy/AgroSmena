"""Real PostgreSQL regressions for ordinary admin edits and assignment admission."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import test_assignment_consistency as audit
from accounts.models import Membership, Organization
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task


class OrganizationIntegrityTests(TransactionTestCase):
    setUp = audit.AssignmentConsistencyTests.setUp
    worker = audit.AssignmentConsistencyTests.worker
    observed = audit.AssignmentConsistencyTests.observed
    assert_lock_wait = audit.AssignmentConsistencyTests.assert_lock_wait
    exchange = audit.AssignmentConsistencyTests.exchange

    def admin_client(self):
        client = Client()
        client.force_login(self.root)
        return client

    def task_data(self, **overrides):
        return {'organization': self.org.pk, 'title': 'Must not persist',
                'priority': Task.Priority.NORMAL, 'status': Task.Status.NEW,
                'assignees': [self.colleague.pk], **overrides}

    def test_admin_rejects_foreign_assignees_and_rolls_back_whole_edit(self):
        other = Organization.objects.create(name='Synthetic foreign')
        foreign = Membership.objects.create(organization=other,
            user=get_user_model().objects.create_user('foreign-assignee'))
        task = Task.objects.create(organization=self.org, title='Before')
        task.assignees.add(self.member)
        client = self.admin_client()
        for url in ('/admin/tasks/task/add/', f'/admin/tasks/task/{task.pk}/change/'):
            with self.subTest(url=url):
                response = client.post(url, self.task_data(assignees=[self.colleague.pk, foreign.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertIn('assignees', response.context['adminform'].form.errors)
                self.assertFalse(Task.objects.filter(title='Must not persist').exists())
                task.refresh_from_db()
                self.assertEqual(task.title, 'Before')
                self.assertEqual(list(task.assignees.all()), [self.member])

    def test_admin_cannot_reassign_membership_identity(self):
        other = Organization.objects.create(name='Synthetic foreign')
        replacement = get_user_model().objects.create_user('replacement-account')
        task = Task.objects.create(organization=self.org, title='Identity remains')
        task.assignees.add(self.colleague)
        client = self.admin_client()
        for changes in ({'organization': other.pk}, {'user': replacement.pk}):
            with self.subTest(changes=changes):
                response = client.post(f'/admin/accounts/membership/{self.colleague.pk}/change/', {
                    'organization': self.org.pk, 'user': self.colleague_user.pk,
                    'role': 'supervisor', **changes})
                self.assertEqual(response.status_code, 200)
                self.assertIn(next(iter(changes)), response.context['adminform'].form.errors)
                self.colleague.refresh_from_db()
                self.assertEqual(self.colleague.organization_id, self.org.pk)
                self.assertEqual(self.colleague.user_id, self.colleague_user.pk)
                self.assertEqual(self.colleague.role, 'manager')
                self.assertEqual(list(task.assignees.all()), [self.colleague])

    def test_admin_cannot_move_existing_crm_records(self):
        other = Organization.objects.create(name='Synthetic foreign')
        customer = Customer.objects.create(organization=self.org, name='Before customer')
        foreign = Customer.objects.create(organization=other, name='Foreign customer')
        deal = Deal.objects.create(organization=self.org, customer=customer, title='Before deal')
        task = Task.objects.create(organization=self.org, customer=customer, deal=deal, title='Before task')
        task.assignees.add(self.colleague)
        cases = [
            (customer, '/admin/customers/customer/', {'name': 'Moved customer'}),
            (deal, '/admin/deals/deal/', {'title': 'Moved deal', 'customer': foreign.pk,
                'amount': '0.00', 'stage': Deal.Stage.NEW}),
            # Drop old links in the POST so relation validation alone cannot stop the move.
            (task, '/admin/tasks/task/', self.task_data(assignees=[])),
        ]
        client = self.admin_client()
        for obj, prefix, data in cases:
            with self.subTest(model=type(obj).__name__):
                response = client.post(f'{prefix}{obj.pk}/change/', {**data, 'organization': other.pk})
                self.assertEqual(response.status_code, 200)
                self.assertIn('organization', response.context['adminform'].form.errors)
                obj.refresh_from_db()
                self.assertEqual(obj.organization_id, self.org.pk)
        deal.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(deal.customer_id, customer.pk)
        self.assertEqual((task.customer_id, task.deal_id), (customer.pk, deal.pk))
        self.assertEqual(list(task.assignees.all()), [self.colleague])

    def test_model_save_also_rejects_identity_changes(self):
        other = Organization.objects.create(name='Synthetic foreign')
        replacement = get_user_model().objects.create_user('replacement-account')
        customer = Customer.objects.create(organization=self.org, name='Stable owner')
        for obj, field, value in ((customer, 'organization', other),
                                  (self.colleague, 'organization', other),
                                  (self.colleague, 'user', replacement)):
            with self.subTest(model=type(obj).__name__, field=field):
                setattr(obj, field, value)
                with self.assertRaises(ValidationError) as caught:
                    obj.save()
                self.assertIn(field, caught.exception.message_dict)
                obj.refresh_from_db()
        self.assertEqual(customer.organization_id, self.org.pk)
        self.assertEqual(self.colleague.organization_id, self.org.pk)
        self.assertEqual(self.colleague.user_id, self.colleague_user.pk)

    def test_admin_foreign_crm_links_already_rejected(self):
        other = Organization.objects.create(name='Synthetic foreign')
        foreign = Customer.objects.create(organization=other, name='Foreign customer')
        deal = Deal.objects.create(organization=other, customer=foreign, title='Foreign deal')
        client = self.admin_client()
        response = client.post('/admin/deals/deal/add/', {'organization': self.org.pk,
            'title': 'Must not persist', 'customer': foreign.pk, 'amount': '0', 'stage': Deal.Stage.NEW})
        self.assertEqual(response.status_code, 200)
        self.assertIn('customer', response.context['adminform'].form.errors)
        for field, pk in (('customer', foreign.pk), ('deal', deal.pk)):
            response = client.post('/admin/tasks/task/add/', self.task_data(**{field: pk}))
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context['adminform'].form.errors)
        self.assertFalse(Task.objects.filter(title='Must not persist').exists())

    def assert_stale_selection_rejected(self, path, revoke, update=False):
        client = APIClient() if path == 'rest' else Client()
        client.force_login(self.root if path == 'admin' else self.user)
        task = Task.objects.create(organization=self.org, title='Before') if update else None
        if task:
            task.assignees.add(self.member)
        attempted, pid = Event(), []

        def write():
            if path == 'rest':
                method = client.patch if update else client.post
                return method(f'/api/tasks/{task.pk}/' if update else '/api/tasks/', {
                    'title': 'Must not persist', 'assignee_usernames': [self.colleague_user.username]}, format='json')
            url = '/admin/tasks/task/add/' if path == 'admin' else '/tasks/new/'
            return client.post(url, self.task_data())

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(self.worker, lambda: self.observed(attempted, pid, write))
                self.assert_lock_wait(pending, attempted, pid)  # Validation finished before this wait.
                if revoke == 'delete':
                    self.colleague.delete()
                else:
                    self.colleague_user.is_active = False
                    self.colleague_user.save(update_fields=['is_active'])
            response = pending.result(timeout=10)
        self.assertEqual(response.status_code, 400 if path == 'rest' else 200)
        errors = (response.data if path == 'rest' else
                  response.context['adminform'].form.errors if path == 'admin' else response.context['form'].errors)
        self.assertIn('assignee_usernames' if path == 'rest' else 'assignees', errors)
        self.assertFalse(Task.objects.filter(title='Must not persist').exists())
        if task:
            task.refresh_from_db()
            self.assertEqual(task.title, 'Before')
            self.assertEqual(list(task.assignees.all()), [self.member])

    def test_rest_revalidates_after_org_wait_and_rolls_back_update(self):
        self.assert_stale_selection_rejected('rest', 'deactivate', update=True)

    def test_site_revalidates_after_org_wait(self):
        self.assert_stale_selection_rejected('site', 'deactivate')

    def test_rest_rejects_deleted_member_after_org_wait(self):
        self.assert_stale_selection_rejected('rest', 'delete')

    def test_admin_rejects_deleted_member_after_org_wait(self):
        self.assert_stale_selection_rejected('admin', 'delete')

    def test_rest_checks_current_activity_and_username_after_user_lock_wait(self):
        for change in ('deactivate', 'rename'):
            with self.subTest(change=change):
                self.colleague_user.refresh_from_db()
                self.colleague_user.is_active = True
                self.colleague_user.save(update_fields=['is_active'])
                requested_name = self.colleague_user.username
                client = APIClient()
                client.force_login(self.user)
                attempted, pid = Event(), []
                def write():
                    def observe(execute, sql, params, many, context):
                        if 'FOR NO KEY UPDATE' in sql and 'auth_user' in sql:
                            pid[:] = [connection.connection.info.backend_pid]
                            attempted.set()
                        return execute(sql, params, many, context)
                    with connection.execute_wrapper(observe):
                        return client.post('/api/tasks/', {'title': 'Must not persist',
                            'assignee_usernames': [requested_name]}, format='json')
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        locked = get_user_model().objects.select_for_update().get(pk=self.colleague_user.pk)
                        pending = pool.submit(self.worker, write)
                        self.assert_lock_wait(pending, attempted, pid)
                        if change == 'deactivate':
                            locked.is_active = False
                        else:
                            locked.username += '-renamed'
                        locked.save(update_fields=['is_active', 'username'])
                    response = pending.result(timeout=10)
                self.assertEqual(response.status_code, 400)
                self.assertIn('assignee_usernames', response.data)
                self.assertFalse(Task.objects.filter(title='Must not persist').exists())

    def test_user_changes_wait_until_assignment_commit(self):
        for path in ('rest', 'site', 'admin', 'sync'):
            with self.subTest(path=path):
                self.colleague_user.is_active = True
                self.colleague_user.save(update_fields=['is_active'])
                client = APIClient() if path == 'rest' else Client()
                client.force_login(self.root if path == 'admin' else self.user)
                paused, release, attempted, pid = Event(), Event(), Event(), []
                manager_type = type(Task(pk=1).assignees)
                original = manager_type.set
                def pause(manager, *args, **kwargs):
                    if manager.instance.title == 'Locked selection':
                        paused.set()
                        if not release.wait(15):
                            raise AssertionError('Task writer not released')
                    return original(manager, *args, **kwargs)
                def write():
                    if path == 'sync':
                        stamp = timezone.now() - timedelta(seconds=1)
                        self.exchange([{'entity': 'tasks', 'uuid': uuid4(), 'created_at': stamp,
                            'updated_at': stamp, 'deleted': False, 'fields': {'title': 'Locked selection',
                            'assignee_usernames': [self.colleague_user.username]}}])
                        return 200
                    if path == 'rest':
                        return client.post('/api/tasks/', {'title': 'Locked selection',
                            'assignee_usernames': [self.colleague_user.username]}, format='json').status_code
                    url = '/admin/tasks/task/add/' if path == 'admin' else '/tasks/new/'
                    return client.post(url, self.task_data(title='Locked selection')).status_code
                def deactivate():
                    def observe(execute, sql, params, many, context):
                        if sql.startswith('UPDATE "auth_user"'):
                            pid[:] = [connection.connection.info.backend_pid]
                            attempted.set()
                        return execute(sql, params, many, context)
                    with connection.execute_wrapper(observe):
                        get_user_model().objects.filter(pk=self.colleague_user.pk).update(is_active=False)
                with patch.object(manager_type, 'set', pause), ThreadPoolExecutor(max_workers=2) as pool:
                    writer = pool.submit(self.worker, write)
                    editor = None
                    try:
                        self.assertTrue(paused.wait(8))
                        editor = pool.submit(self.worker, deactivate)
                        self.assert_lock_wait(editor, attempted, pid)
                    finally:
                        release.set()
                    self.assertEqual(writer.result(timeout=10), 200 if path == 'sync' else
                                     201 if path == 'rest' else 302)
                    editor.result(timeout=10)
                task = Task.objects.get(title='Locked selection')
                self.assertEqual(list(task.assignees.all()), [self.colleague])
                self.assertFalse(get_user_model().objects.get(pk=self.colleague_user.pk).is_active)
                task.delete()

    def test_sync_assignment_error_rolls_back_earlier_record(self):
        stamp = timezone.now() - timedelta(seconds=1)
        from rest_framework.exceptions import ValidationError as APIValidationError
        with self.assertRaises(APIValidationError):
            self.exchange([
                {'entity': 'customers', 'uuid': uuid4(), 'created_at': stamp, 'updated_at': stamp,
                 'deleted': False, 'fields': {'name': 'Must roll back'}},
                {'entity': 'tasks', 'uuid': uuid4(), 'created_at': stamp, 'updated_at': stamp,
                 'deleted': False, 'fields': {'title': 'Must not persist', 'assignee_usernames': ['absent-user']}}
            ])
        self.assertFalse(Customer.objects.filter(name='Must roll back').exists())
        self.assertFalse(Task.objects.filter(title='Must not persist').exists())

    def test_admin_preserves_inactive_assignment_and_empty_means_common(self):
        self.colleague_user.is_active = False
        self.colleague_user.save(update_fields=['is_active'])
        task = Task.objects.create(organization=self.org, title='Before')
        task.assignees.add(self.colleague)
        client = self.admin_client()
        response = client.post(f'/admin/tasks/task/{task.pk}/change/', self.task_data(title='Still assigned'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(task.assignees.all()), [self.colleague])
        response = client.post(f'/admin/tasks/task/{task.pk}/change/', self.task_data(title='Common', assignees=[]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(task.assignees.exists())
