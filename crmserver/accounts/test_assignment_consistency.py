"""Small PostgreSQL concurrency regressions; events coordinate real writes, not mocks of DB results."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Membership, Organization
from accounts.services import change_membership
from synchronization import services
from synchronization.auth import issue_token
from tasks.models import Task


class AssignmentConsistencyTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Synthetic assignment audit')
        self.user = get_user_model().objects.create_user('audit-reader')
        self.member = Membership.objects.create(user=self.user, organization=self.org, role='admin')
        self.colleague_user = get_user_model().objects.create_user('audit-colleague')
        self.colleague = Membership.objects.create(user=self.colleague_user, organization=self.org)
        self.root = get_user_model().objects.create_superuser('audit-root', password=None)

    def exchange(self, changes=None):
        return services.exchange(SimpleNamespace(user=self.user, crm_membership=self.member),
                                 {'organization': self.org.uuid, 'changes': changes or []})

    def worker(self, function):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout='10s'")
                cursor.execute("SET lock_timeout='8s'")
            return function()
        finally:
            connection.close()

    def observed(self, attempted, pid, function):
        def observe(execute, sql, params, many, context):
            if 'FOR UPDATE' in sql and 'accounts_organization' in sql:
                pid[:] = [connection.connection.info.backend_pid]
                attempted.set()
            return execute(sql, params, many, context)
        with connection.execute_wrapper(observe):
            return function()

    def assert_lock_wait(self, future, attempted, pid):
        self.assertTrue(attempted.wait(5), 'Writer/reader did not attempt the organization lock')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if future.done():
                result = future.result()  # Surface real errors instead of hiding them behind a timeout.
                self.fail(f'Operation completed before lock release: {str(result)[:150]}')
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', pid)
                row = cursor.fetchone()
            if row and row[0] == 'Lock':
                return
            time.sleep(.01)
        self.fail('No real PostgreSQL lock wait observed')

    def assert_assignment_write_atomic(self, path, update=False):
        client = APIClient() if path == 'rest' else Client()
        client.force_login(self.root if path == 'admin' else self.user)
        existing = Task.objects.create(organization=self.org, title='Originally common') if update else None
        paused, release, attempted, pid = Event(), Event(), Event(), []
        manager_type = type(Task(pk=1).assignees)
        original = manager_type.set

        def pause(manager, *args, **kwargs):
            if manager.instance.title == 'Private audit task':
                paused.set()  # Task.save has returned, M2M has not been written yet.
                if not release.wait(15):
                    raise AssertionError('Assignment writer not released')
            return original(manager, *args, **kwargs)

        def write():
            if path == 'sync':
                stamp = timezone.now() - timedelta(seconds=1)
                self.exchange([{'entity': 'tasks', 'uuid': uuid4(), 'created_at': stamp, 'updated_at': stamp,
                    'deleted': False, 'fields': {'title': 'Private audit task',
                                                'assignee_usernames': [self.colleague_user.username]}}])
                return 200
            if path == 'rest':
                method = client.patch if update else client.post
                url = f'/api/tasks/{existing.pk}/' if update else '/api/tasks/'
                return method(url, {'title': 'Private audit task',
                    'assignee_usernames': [self.colleague_user.username]}, format='json').status_code
            url = '/admin/tasks/task/add/' if path == 'admin' else (f'/tasks/{existing.pk}/edit/' if update else '/tasks/new/')
            return client.post(url, {'title': 'Private audit task', 'priority': Task.Priority.NORMAL,
                'status': Task.Status.NEW, 'assignees': [self.colleague.pk], 'organization': self.org.pk}).status_code

        with patch.object(manager_type, 'set', pause), ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(self.worker, write)
            reader = None
            try:
                self.assertTrue(paused.wait(8))
                reader = pool.submit(self.worker, lambda: self.observed(attempted, pid, self.exchange))
                self.assert_lock_wait(reader, attempted, pid)
            finally:
                release.set()
            expected = 200 if path == 'sync' else ((200 if update else 201) if path == 'rest' else 302)
            self.assertEqual(writer.result(timeout=10), expected)
            snapshot = reader.result(timeout=10)
        task = Task.objects.get(title='Private audit task')
        self.assertEqual(list(task.assignees.all()), [self.colleague])
        self.assertNotIn(str(task.uuid), {row['uuid'] for row in snapshot['changes']})

    def test_site_create_and_assign_are_one_transaction_against_sync(self):
        self.assert_assignment_write_atomic('site')

    def test_rest_create_and_assign_are_one_transaction_against_sync(self):
        self.assert_assignment_write_atomic('rest')

    def test_admin_task_assignment_already_has_outer_atomic(self):
        self.assert_assignment_write_atomic('admin')

    def test_sync_task_assignment_retains_outer_atomic(self):
        self.assert_assignment_write_atomic('sync')

    def test_existing_site_and_rest_task_updates_are_atomic_against_sync(self):
        for path in ('rest', 'site'):
            with self.subTest(path=path):
                self.assert_assignment_write_atomic(path, update=True)
                Task.objects.filter(title='Private audit task').delete()

    def test_assignment_failure_rolls_back_task_creation_and_update(self):
        client = APIClient()
        client.force_login(self.user)
        manager_type = type(Task(pk=1).assignees)
        original = manager_type.set
        def fail_after_real_write(manager, *args, **kwargs):
            original(manager, *args, **kwargs)
            raise RuntimeError('Synthetic fault after M2M write')
        for update in (False, True):
            with self.subTest(update=update):
                task = Task.objects.create(organization=self.org, title='Before rollback') if update else None
                with patch.object(manager_type, 'set', fail_after_real_write), self.assertRaises(RuntimeError):
                    method = client.patch if update else client.post
                    url = f'/api/tasks/{task.pk}/' if update else '/api/tasks/'
                    method(url, {'title': 'Must roll back', 'assignee_usernames': [self.colleague_user.username]}, format='json')
                self.assertFalse(Task.objects.filter(title='Must roll back').exists())
                if update:
                    task.refresh_from_db()
                    self.assertEqual(task.title, 'Before rollback')
                    self.assertFalse(task.assignees.exists())

    def test_admin_membership_delete_waits_for_snapshot(self):
        self.assert_membership_delete_waits('membership')

    def test_admin_user_delete_cascade_waits_for_snapshot(self):
        self.assert_membership_delete_waits('user')

    def assert_membership_delete_waits(self, kind):
        task = Task.objects.create(organization=self.org, title='Audit assigned')
        task.assignees.add(self.member, self.colleague)
        paused, release, attempted, pid = Event(), Event(), Event(), []
        client = Client()
        client.force_login(self.root)

        def snapshot():
            def pause_after_tasks(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if sql.startswith('SELECT') and 'FROM "synchronization_tombstone"' in sql:
                    paused.set()  # Task representations are ready, members directory is still unread.
                    if not release.wait(15):
                        raise AssertionError('Snapshot not released')
                return result
            with connection.execute_wrapper(pause_after_tasks):
                return self.exchange()

        def delete():
            url = (f'/admin/accounts/membership/{self.colleague.pk}/delete/' if kind == 'membership'
                   else f'/admin/auth/user/{self.colleague_user.pk}/delete/')
            return client.post(url, {'post': 'yes'}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(self.worker, snapshot)
            writer = None
            try:
                self.assertTrue(paused.wait(8))
                writer = pool.submit(self.worker, lambda: self.observed(attempted, pid, delete))
                # Pre-fix delete has no organization lock and finishes, so also wake the assertion.
                deadline = time.monotonic() + 5
                while not attempted.is_set() and not writer.done() and time.monotonic() < deadline:
                    time.sleep(.01)
                if writer.done():
                    self.fail(f'Admin deletion committed while sync held org lock: {writer.result()}')
                self.assert_lock_wait(writer, attempted, pid)
            finally:
                release.set()
            result = reader.result(timeout=10)
            self.assertEqual(writer.result(timeout=10), 302)
        row = next(row for row in result['changes'] if row['uuid'] == str(task.uuid))
        self.assertEqual(set(row['fields']['assignee_usernames']), {self.user.username, self.colleague_user.username})
        self.assertIn(self.colleague_user.username, {m['username'] for m in result['members']})
        after = self.exchange()
        row = next(row for row in after['changes'] if row['uuid'] == str(task.uuid))
        self.assertEqual(row['fields']['assignee_usernames'], [self.user.username])
        self.assertEqual(get_user_model().objects.filter(pk=self.colleague_user.pk).exists(), kind == 'membership')

    def test_deactivation_while_sync_waits_for_org_rejects_old_authenticated_user(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_token(self.user, self.member))
        attempted, pid = Event(), []
        uid = str(uuid4())
        stamp = timezone.now() - timedelta(seconds=1)
        payload = {'organization': str(self.org.uuid), 'changes': [{'entity': 'customers', 'uuid': uid,
            'created_at': stamp.isoformat(), 'updated_at': stamp.isoformat(), 'fields': {'name': 'Must not create'}}]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(self.worker, lambda: self.observed(attempted, pid,
                    lambda: client.post('/api/sync/exchange/', payload, format='json')))
                self.assert_lock_wait(pending, attempted, pid)
                self.user.is_active = False
                self.user.save(update_fields=['is_active'])
            response = pending.result(timeout=10)
        self.assertEqual(response.status_code, 403)
        from customers.models import Customer
        self.assertFalse(Customer.objects.filter(uuid=uid).exists())
        self.assertEqual(client.post('/api/sync/exchange/', {'organization': str(self.org.uuid), 'changes': []},
                                     format='json').status_code, 401)
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        self.assertEqual(client.post('/api/sync/exchange/', {'organization': str(self.org.uuid), 'changes': []},
                                     format='json').status_code, 200)

    def test_recreated_membership_does_not_reuse_queued_old_membership(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_token(self.user, self.member))
        attempted, pid = Event(), []
        old_member_id = self.member.pk
        payload = {'organization': str(self.org.uuid), 'changes': []}
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(self.worker, lambda: self.observed(attempted, pid,
                    lambda: client.post('/api/sync/exchange/', payload, format='json')))
                self.assert_lock_wait(pending, attempted, pid)
                self.member.delete()
                new_member = Membership.objects.create(user=self.user, organization=self.org, role='admin')
            self.assertEqual(pending.result(timeout=10).status_code, 403)
        self.assertNotEqual(new_member.pk, old_member_id)
        self.assertEqual(client.post('/api/sync/exchange/', payload, format='json').status_code, 200)

    def test_bulk_admin_deletions_take_organization_locks_in_order(self):
        client = Client()
        client.force_login(self.root)
        for model in ('membership', 'user'):
            with self.subTest(model=model):
                low = Organization.objects.create(name='Synthetic low ' + model)
                high = Organization.objects.create(name='Synthetic high ' + model)
                # Membership insertion order deliberately differs from organization order.
                high_member = Membership.objects.create(organization=high,
                    user=get_user_model().objects.create_user('high-' + model))
                low_member = Membership.objects.create(organization=low,
                    user=get_user_model().objects.create_user('low-' + model))
                selected = ([high_member.pk, low_member.pk] if model == 'membership'
                            else [high_member.user_id, low_member.user_id])
                url = '/admin/accounts/membership/' if model == 'membership' else '/admin/auth/user/'
                attempted, pid = Event(), []
                def delete():
                    return client.post(url, {'action': 'delete_selected', '_selected_action': selected,
                                             'post': 'yes'}).status_code
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        Organization.objects.select_for_update().get(pk=low.pk)
                        pending = pool.submit(self.worker, lambda: self.observed(attempted, pid, delete))
                        self.assert_lock_wait(pending, attempted, pid)
                        # Waiting admin must not already own the higher org lock.
                        with transaction.atomic():
                            Organization.objects.select_for_update(nowait=True).get(pk=high.pk)
                    self.assertEqual(pending.result(timeout=10), 302)
                self.assertFalse(Membership.objects.filter(pk__in=[low_member.pk, high_member.pk]).exists())

    def test_admin_membership_insert_waits_on_organization_fk_lock(self):
        client = Client()
        client.force_login(self.root)
        user = get_user_model().objects.create_user('new-admin-member')
        attempted, pid = Event(), []
        def write():
            def observe_insert(execute, sql, params, many, context):
                if sql.startswith('INSERT INTO "accounts_membership"'):
                    pid[:] = [connection.connection.info.backend_pid]
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe_insert):
                return client.post('/admin/accounts/membership/add/', {'user': user.pk,
                    'organization': self.org.pk, 'role': 'manager'}).status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(self.worker, write)
                self.assert_lock_wait(pending, attempted, pid)
                self.assertFalse(Membership.objects.filter(user=user).exists())
            self.assertEqual(pending.result(timeout=10), 302)
        self.assertEqual(Membership.objects.get(user=user).organization_id, self.org.pk)

    def test_admin_role_update_is_not_serialized_by_organization_lock(self):
        client = Client()
        client.force_login(self.root)
        def write():
            return client.post(f'/admin/accounts/membership/{self.colleague.pk}/change/', {
                'user': self.colleague_user.pk, 'organization': self.org.pk, 'role': 'supervisor'}).status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(self.worker, write)
                self.assertEqual(pending.result(timeout=5), 302)
                self.assertEqual(Membership.objects.get(pk=self.colleague.pk).role, 'supervisor')

    def test_removing_last_assignee_keeps_account_and_makes_task_common_in_full_sync(self):
        task = Task.objects.create(organization=self.org, title='Becomes common')
        task.assignees.add(self.colleague)
        self.assertNotIn(str(task.uuid), {row['uuid'] for row in self.exchange()['changes']})
        change_membership(self.org.pk, self.user, self.colleague.pk, remove=True)
        self.assertTrue(get_user_model().objects.filter(pk=self.colleague_user.pk).exists())
        row = next(row for row in self.exchange()['changes'] if row['uuid'] == str(task.uuid))
        self.assertEqual(row['fields']['assignee_usernames'], [])
