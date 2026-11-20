"""Outgoing snapshot behavior and SQL budgets on real PostgreSQL, without HTTP/input costs."""
from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Membership, Organization
from customers.models import Customer
from deals.models import Deal
from synchronization import services
from synchronization.models import Tombstone
from synchronization.serializers import ExchangeSerializer
from tasks.models import Task


class SnapshotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Synthetic snapshot org')
        cls.foreign_org = Organization.objects.create(name='Synthetic foreign org')
        cls.reader = get_user_model().objects.create_user('z-reader', first_name='  Reader  ')
        cls.member = Membership.objects.create(organization=cls.org, user=cls.reader)
        cls.alpha_user = get_user_model().objects.create_user('a-colleague', first_name='Alpha', last_name='One')
        cls.alpha = Membership.objects.create(organization=cls.org, user=cls.alpha_user)
        cls.inactive_user = get_user_model().objects.create_user('b-inactive', is_active=False)
        cls.inactive = Membership.objects.create(organization=cls.org, user=cls.inactive_user)
        cls.customer = Customer.objects.create(organization=cls.org, name='Synthetic customer',
                                              email='legacy free text', notes='Synthetic notes')
        cls.deal = Deal.objects.create(organization=cls.org, customer=cls.customer,
                                      title='Synthetic deal', amount='123.40', expected_close_date=date(2026, 10, 16))

    def snapshot(self, changes=None):
        return services.exchange(SimpleNamespace(user=self.reader, crm_membership=self.member), {
            'organization': self.org.uuid, 'changes': changes or [],
        })

    def measured_snapshot(self, changes=None):
        """Observe executed SQL only inside the existing response_prepare phase.

        Auth, organization lock, input apply and transaction statements are deliberately
        outside this budget. The real phase context and all real DB operations still run.
        """
        statements = []
        phase = services.sync_phase

        def collect(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        @contextmanager
        def measure(request, name):
            with phase(request, name):
                if name == 'response_prepare_ms':
                    with connection.execute_wrapper(collect):
                        yield
                else:
                    yield

        with patch.object(services, 'sync_phase', measure):
            response = self.snapshot(changes)
        return response, statements

    def test_snapshot_contents_visibility_order_and_unprepared_serializer_agree(self):
        common = Task.objects.create(organization=self.org, title='Common', description='No links')
        mine = Task.objects.create(organization=self.org, title='Mine', customer=self.customer,
                                   deal=self.deal, due_date=date(2026, 10, 20), priority=Task.Priority.HIGH)
        # Deliberately add in reverse username order; inactive assignees remain in the response.
        mine.assignees.add(self.member, self.inactive, self.alpha)
        customer_only = Task.objects.create(organization=self.org, title='Customer only', customer=self.customer)
        deal_only = Task.objects.create(organization=self.org, title='Deal only', deal=self.deal)
        hidden = Task.objects.create(organization=self.org, title='Other employee')
        hidden.assignees.add(self.alpha)
        Task.objects.create(organization=self.foreign_org, title='Foreign common')
        foreign_customer = Customer.objects.create(organization=self.foreign_org, name='Foreign customer')
        Deal.objects.create(organization=self.foreign_org, customer=foreign_customer, title='Foreign deal')
        Tombstone.objects.create(organization=self.foreign_org, entity='tasks', uuid=uuid4(), updated_at=timezone.now())

        # The standalone serializer exercises the established, non-prefetched path.
        expected = []
        for entity, objects in (
            ('customers', Customer.objects.filter(organization=self.org)),
            ('deals', Deal.objects.filter(organization=self.org)),
            ('tasks', Task.objects.filter(pk__in=[common.pk, mine.pk, customer_only.pk, deal_only.pk])),
        ):
            expected.extend(services.serialize_record(entity, obj) for obj in objects)
        result, queries = self.measured_snapshot()
        self.assertEqual(result['organization'], str(self.org.uuid))
        self.assertEqual(result['changes'], expected)  # Includes row order, dates and every field.
        self.assertEqual(result['members'], [
            {'username': 'a-colleague', 'name': 'Alpha One'}, {'username': 'z-reader', 'name': 'Reader'},
        ])
        rows = {row['uuid']: row for row in result['changes']}
        self.assertEqual(rows[str(mine.uuid)]['fields'], {
            'title': 'Mine', 'description': '', 'customer_uuid': str(self.customer.uuid),
            'deal_uuid': str(self.deal.uuid), 'due_date': '2026-10-20', 'priority': 'Высокий',
            'status': 'Новая', 'assignee_usernames': ['a-colleague', 'b-inactive', 'z-reader'],
        })
        self.assertEqual(rows[str(common.uuid)]['fields']['assignee_usernames'], [])
        self.assertIsNone(rows[str(common.uuid)]['fields']['customer_uuid'])
        self.assertIsNone(rows[str(common.uuid)]['fields']['deal_uuid'])
        self.assertEqual(rows[str(customer_only.uuid)]['fields']['customer_uuid'], str(self.customer.uuid))
        self.assertIsNone(rows[str(customer_only.uuid)]['fields']['deal_uuid'])
        self.assertIsNone(rows[str(deal_only.uuid)]['fields']['customer_uuid'])
        self.assertEqual(rows[str(deal_only.uuid)]['fields']['deal_uuid'], str(self.deal.uuid))
        self.assertEqual(rows[str(self.deal.uuid)]['fields']['amount'], '123.40')
        self.assertEqual(rows[str(self.deal.uuid)]['fields']['customer_uuid'], str(self.customer.uuid))
        self.assertEqual(rows[str(self.customer.uuid)]['fields']['email'], 'legacy free text')
        self.assertLessEqual(len(queries), 6)  # No deferred-field SELECTs for linked UUIDs/users.

    def test_deleted_member_makes_formerly_assigned_task_common(self):
        removed = Membership.objects.create(organization=self.org,
            user=get_user_model().objects.create_user('removed-colleague'))
        task = Task.objects.create(organization=self.org, title='Former assignment')
        task.assignees.add(removed)
        self.assertNotIn(str(task.uuid), {row['uuid'] for row in self.snapshot()['changes']})
        removed.delete()
        result = self.snapshot()
        row = next(row for row in result['changes'] if row['uuid'] == str(task.uuid))
        self.assertEqual(row['fields']['assignee_usernames'], [])
        self.assertNotIn('removed-colleague', [member['username'] for member in result['members']])

    def test_parent_deletions_keep_tombstones_and_null_task_links(self):
        task = Task.objects.create(organization=self.org, title='Survives deletion',
                                   customer=self.customer, deal=self.deal)
        customer_uuid, deal_uuid = str(self.customer.uuid), str(self.deal.uuid)
        deleted_task = Task.objects.create(organization=self.org, title='Deleted task')
        deleted_task_uuid = str(deleted_task.uuid)
        deleted_task.delete()
        self.customer.delete()
        result, queries = self.measured_snapshot()
        rows = {row['uuid']: row for row in result['changes']}
        self.assertEqual(set(rows), {customer_uuid, deal_uuid, str(task.uuid), deleted_task_uuid})
        for uid, entity in [(customer_uuid, 'customers'), (deal_uuid, 'deals'), (deleted_task_uuid, 'tasks')]:
            marker = Tombstone.objects.get(uuid=uid)
            self.assertEqual(rows[uid], {'entity': entity, 'uuid': uid, 'deleted': True,
                                        'updated_at': marker.updated_at.isoformat()})
        self.assertIsNone(rows[str(task.uuid)]['fields']['customer_uuid'])
        self.assertIsNone(rows[str(task.uuid)]['fields']['deal_uuid'])
        task.refresh_from_db()
        self.assertEqual(rows[str(task.uuid)]['updated_at'], task.updated_at.isoformat())
        self.assertLessEqual(len(queries), 6)

    def test_growing_tasks_does_not_grow_assignee_or_snapshot_selects(self):
        def add_task(i):
            task = Task.objects.create(organization=self.org, title=f'Synthetic task {i}',
                                       customer=self.customer, deal=self.deal)
            task.assignees.add(self.alpha, self.member)

        add_task(0)
        small, small_queries = self.measured_snapshot()
        for i in range(1, 25):
            add_task(i)
        large, large_queries = self.measured_snapshot()
        self.assertEqual(len(large['changes']) - len(small['changes']), 24)
        for row in large['changes']:
            if row['entity'] == 'tasks':
                self.assertEqual(row['fields']['assignee_usernames'], ['a-colleague', 'z-reader'])
                self.assertEqual(row['fields']['customer_uuid'], str(self.customer.uuid))
                self.assertEqual(row['fields']['deal_uuid'], str(self.deal.uuid))
        # Both legacy per-task SELECT and batched prefetch read this M2M table.
        def assignee_selects(queries):
            return [sql for sql in queries if 'FROM "accounts_membership"' in sql and 'tasks_task_assignees' in sql]
        self.assertEqual(len(assignee_selects(small_queries)), 1)
        self.assertEqual(len(assignee_selects(large_queries)), 1)
        self.assertEqual(len(small_queries), len(large_queries))
        self.assertLessEqual(len(large_queries), 6)

        # A no-op full input still does per-record conflict reads, outside that budget.
        serializer = ExchangeSerializer(data={'organization': str(self.org.uuid), 'changes': large['changes']})
        serializer.is_valid(raise_exception=True)
        again, prepare_queries = self.measured_snapshot(serializer.validated_data['changes'])
        self.assertEqual(again['changes'], large['changes'])
        self.assertEqual(again['members'], large['members'])
        self.assertEqual(len(prepare_queries), len(large_queries))

    def test_failed_incoming_change_rolls_back_before_snapshot(self):
        before = services.serialize_record('customers', self.customer)
        modified = {**before, 'updated_at': (timezone.now() + timedelta(seconds=1)).isoformat(),
                    'fields': {**before['fields'], 'notes': 'Must roll back'}}
        invalid = {'entity': 'deals', 'uuid': str(uuid4()), 'deleted': False,
                   'created_at': modified['created_at'], 'updated_at': modified['updated_at'],
                   'fields': {'title': 'Invalid parent', 'customer_uuid': str(uuid4())}}
        serializer = ExchangeSerializer(data={'organization': str(self.org.uuid), 'changes': [modified, invalid]})
        serializer.is_valid(raise_exception=True)
        with self.assertRaises(ValidationError):
            self.snapshot(serializer.validated_data['changes'])
        self.customer.refresh_from_db()
        self.assertEqual(services.serialize_record('customers', self.customer), before)
        self.assertEqual(Deal.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(Tombstone.objects.filter(organization=self.org).count(), 0)
