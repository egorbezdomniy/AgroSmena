"""Real desktop SQLite services ↔ HTTP API ↔ PostgreSQL, plus website mutations."""
import sys
import tempfile
from datetime import timedelta, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.utils import timezone
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from accounts.models import Membership, Organization
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task
from synchronization.models import Tombstone
from synchronization.services import serialize_record
from app.core.database import Database
from app.models import Customer as LocalCustomer, Deal as LocalDeal, Task as LocalTask
from app.models.sync import SyncDeletion
from app.models.sync import SavedSyncLogin
from app.repositories.sync_repository import SyncRepository, iso
from app.services.customer_service import CustomerService
from app.services.deal_service import DealService
from app.services.task_service import TaskService
from app.services.sync_service import SyncClient, SyncError, SyncService

PASSWORD = 'Sync-Test-Password!762'


class DesktopSyncTests(StaticLiveServerTestCase):
    def setUp(self):
        cache.clear()
        self.organization = Organization.objects.create(name='Основная организация')
        self.user = get_user_model().objects.create_user('sync-user', password=PASSWORD)
        self.member = Membership.objects.create(organization=self.organization, user=self.user, role='manager')
        self.directory = tempfile.TemporaryDirectory(prefix='crm-sync-test-')
        self.database = Database(Path(self.directory.name) / 'crm.db')
        self.database.create_tables()
        self.customers = CustomerService(self.database.session_factory)
        self.deals = DealService(self.database.session_factory)
        self.tasks = TaskService(self.database.session_factory)
        self.sync = SyncService(self.database.session_factory)
        self.sync.login(self.live_server_url, 'sync-user', PASSWORD)
        self.client.force_login(self.user)

    def tearDown(self):
        self.sync.logout()
        self.database.dispose()
        self.directory.cleanup()
        super().tearDown()

    def seed_desktop(self, email=''):
        customer = self.customers.create(name='Desktop клиент', email=email)
        deal = self.deals.create(title='Desktop сделка', customer_id=customer.id, amount='125.50', stage='Новая')
        task = self.tasks.create(title='Desktop задача', customer_id=customer.id, deal_id=deal.id,
                                 priority='Обычный', status='Новая')
        self.sync.synchronize(confirm_binding=True)
        return customer, deal, task

    def test_bidirectional_create_update_uuid_and_restart(self):
        # Invalid legacy email remains synchronizable; the normal website/API stay strict.
        customer, deal, task = self.seed_desktop(email='телефон вместо почты')
        self.assertEqual(Customer.objects.get(uuid=customer.uuid).email, 'телефон вместо почты')
        self.assertEqual(str(Customer.objects.get().uuid), customer.uuid)
        self.assertEqual(str(Deal.objects.get().uuid), deal.uuid)
        self.assertEqual(str(Task.objects.get().uuid), task.uuid)
        self.assertContains(self.client.get('/customers/'), 'Desktop клиент')
        self.assertEqual(self.client.post(f'/customers/{Customer.objects.get().pk}/edit/',
            {'name': 'Сайт изменил клиента', 'email': ''}).status_code, 302)
        self.assertEqual(self.client.post(f'/deals/{Deal.objects.get().pk}/edit/', {'title': 'Сайт изменил сделку',
            'customer': Customer.objects.get().pk, 'amount': '300', 'stage': 'Предложение'}).status_code, 302)
        self.assertEqual(self.client.post(f'/tasks/{Task.objects.get().pk}/edit/', {'title': 'Сайт изменил задачу',
            'customer': Customer.objects.get().pk, 'deal': Deal.objects.get().pk,
            'priority': 'Высокий', 'status': 'В работе'}).status_code, 302)
        self.assertEqual(self.client.post('/customers/new/', {'name': 'Новый клиент сайта'}).status_code, 302)
        new_customer = Customer.objects.latest('id')
        self.assertEqual(self.client.post('/deals/new/', {'title': 'Новая сделка сайта', 'customer': new_customer.pk,
            'stage': 'Новая', 'amount': '42'}).status_code, 302)
        self.assertEqual(self.client.post('/tasks/new/', {'title': 'Новая задача сайта', 'priority': 'Обычный', 'status': 'Новая'}).status_code, 302)
        self.sync.synchronize()
        self.assertEqual(self.customers.get(customer.id).name, 'Сайт изменил клиента')
        self.assertEqual(self.deals.get(deal.id).title, 'Сайт изменил сделку')
        self.assertEqual(self.tasks.get(task.id).title, 'Сайт изменил задачу')
        self.assertEqual(len(self.customers.list()), 2)
        self.assertEqual(len(self.deals.list()), 2)
        self.assertEqual(len(self.tasks.list()), 2)
        self.customers.update(customer.id, name='Desktop обновил')
        self.deals.update(deal.id, title='Desktop обновил', customer_id=customer.id, stage='Успешно', amount='777')
        self.tasks.update(task.id, title='Desktop обновил', customer_id=customer.id, deal_id=deal.id,
                          status='Выполнена', priority='Высокий')
        self.sync.synchronize()
        self.assertEqual(Customer.objects.get(uuid=customer.uuid).name, 'Desktop обновил')
        self.assertEqual(Deal.objects.get(uuid=deal.uuid).stage, 'Успешно')
        self.assertEqual(Task.objects.get(uuid=task.uuid).status, 'Выполнена')
        stamp = self.sync.state()['last_sync_at']
        self.sync.synchronize()  # Idempotent retry, including UUID relationships.
        self.assertEqual(Customer.objects.count(), 2)
        with self.database.session_factory() as session:
            for local_model, server_model in [(LocalCustomer, Customer), (LocalDeal, Deal), (LocalTask, Task)]:
                for local in session.scalars(select(local_model)):
                    self.assertEqual(local.updated_at, server_model.objects.get(uuid=local.uuid).updated_at.replace(tzinfo=None))
        self.database.dispose()
        reopened = Database(Path(self.directory.name) / 'crm.db')
        try:
            restored = SyncService(reopened.session_factory)
            self.assertIsNotNone(restored.state()['last_sync_at'])
            self.assertIsNotNone(restored.client)
            self.assertEqual(restored.client.identity['username'], 'sync-user')
            self.assertEqual(CustomerService(reopened.session_factory).get(customer.id).uuid, customer.uuid)
            with reopened.session_factory() as session:
                saved = session.get(SavedSyncLogin, 1)
                self.assertNotEqual(saved.protected_token, restored.client.token)
                self.assertNotIn(restored.client.token, saved.protected_token)
            restored.logout(forget=True)
            with reopened.session_factory() as session:
                self.assertIsNone(session.get(SavedSyncLogin, 1))
        finally:
            reopened.dispose()
        self.assertIsNotNone(stamp)

    def test_server_customer_delete_cascades_and_syncs_task_links(self):
        customer, deal, task = self.seed_desktop()
        self.assertEqual(self.client.post(f'/customers/{Customer.objects.get().pk}/delete/').status_code, 302)
        self.assertEqual(Tombstone.objects.count(), 2)
        self.sync.synchronize()
        self.assertEqual(self.customers.list(), [])
        self.assertEqual(self.deals.list(), [])
        self.assertIsNone(self.tasks.get(task.id).customer_id)
        self.assertIsNone(self.tasks.get(task.id).deal_id)
        self.sync.synchronize()
        self.assertFalse(Customer.objects.exists())

    def test_desktop_customer_delete_cascades_and_keeps_tombstones(self):
        customer, deal, task = self.seed_desktop()
        self.customers.delete(customer.id)
        with self.database.session_factory() as session:
            self.assertEqual(len(list(session.scalars(select(SyncDeletion)))), 2)
        self.sync.synchronize()
        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Deal.objects.exists())
        self.assertIsNone(Task.objects.get().customer_id)
        self.assertIsNone(Task.objects.get().deal_id)
        self.tasks.delete(task.id)
        self.sync.synchronize()
        self.assertFalse(Task.objects.exists())
        self.assertEqual(Tombstone.objects.count(), 3)

    def test_newest_change_wins_including_delete_and_resurrection(self):
        customer, _, _ = self.seed_desktop()
        base = timezone.now() - timedelta(seconds=30)
        with self.database.session_factory.begin() as session:
            obj = session.get(LocalCustomer, customer.id)
            obj.name = 'Старая локальная версия'
            obj.created_at = (base - timedelta(seconds=1)).replace(tzinfo=None)
            obj.updated_at = base.replace(tzinfo=None)
        Customer.objects.filter(uuid=customer.uuid).update(name='Новая серверная версия', created_at=base - timedelta(seconds=1), updated_at=base + timedelta(seconds=1))
        self.sync.synchronize()
        self.assertEqual(self.customers.get(customer.id).name, 'Новая серверная версия')
        with self.database.session_factory.begin() as session:
            obj = session.get(LocalCustomer, customer.id)
            obj.name = 'Новейшая локальная версия'
            obj.updated_at = (base + timedelta(seconds=2)).replace(tzinfo=None)
        self.sync.synchronize()
        self.assertEqual(Customer.objects.get().name, 'Новейшая локальная версия')
        # Delete is a competing version, not an instruction to always overwrite newer edits.
        self.customers.delete(customer.id)
        with self.database.session_factory() as session:
            deleted_at = session.get(SyncDeletion, ('customers', customer.uuid)).updated_at
        Customer.objects.filter(uuid=customer.uuid).update(name='Изменено после удаления', updated_at=deleted_at.replace(tzinfo=datetime_timezone.utc) + timedelta(seconds=1))
        self.sync.synchronize()
        self.assertEqual(self.customers.list()[0].name, 'Изменено после удаления')

    def test_failed_response_retry_no_duplicates_binding_and_last_sync_preserved(self):
        self.customers.create(name='Не потерять')
        original = self.sync.client.request
        def lost_response(path, payload):
            original(path, payload)
            raise SyncError('Ответ потерян')
        with patch.object(self.sync.client, 'request', side_effect=lost_response):
            with self.assertRaises(SyncError):
                self.sync.synchronize(confirm_binding=True)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(len(self.customers.list()), 1)
        self.assertIsNone(self.sync.state()['last_sync_at'])
        self.assertEqual(self.sync.state()['organization'], str(self.organization.uuid))
        self.sync.synchronize()
        self.assertEqual(Customer.objects.count(), 1)
        last_sync = self.sync.state()['last_sync_at']
        with patch.object(self.sync.client, 'request', side_effect=SyncError('Нет сети')):
            with self.assertRaises(SyncError):
                self.sync.synchronize()
        self.assertEqual(self.sync.state()['last_sync_at'], last_sync)

    def test_organization_and_token_security(self):
        customer, _, _ = self.seed_desktop()
        other_org = Organization.objects.create(name='Другая организация')
        other_user = get_user_model().objects.create_user('other-user', password=PASSWORD)
        Membership.objects.create(user=other_user, organization=other_org, role='admin')
        foreign = Customer.objects.create(organization=other_org, name='Секрет')
        response = self.sync.client.request('exchange', {'organization': str(self.organization.uuid), 'changes': []})
        self.assertNotIn(str(foreign.uuid), [row['uuid'] for row in response['changes']])
        forged = serialize_record('customers', foreign)
        forged['updated_at'] = (timezone.now() + timedelta(seconds=1)).isoformat()
        with self.assertRaises(SyncError):
            self.sync.client.request('exchange', {'organization': str(self.organization.uuid), 'changes': [forged]})
        with self.assertRaises(SyncError):
            self.sync.login(self.live_server_url, 'other-user', PASSWORD)
        self.assertIsNone(self.sync.client)
        self.assertEqual(self.customers.get(customer.id).name, 'Desktop клиент')
        self.sync.login(self.live_server_url, 'sync-user', PASSWORD)
        self.member.delete()
        revoked_client = self.sync.client
        with self.assertRaises(SyncError):
            self.sync.synchronize()
        self.assertIsNone(self.sync.client)
        self.assertIsNone(revoked_client.token)
        with self.assertRaises(SyncError):
            SyncClient('http://remote.example')

    def test_foreign_relation_validation_is_atomic(self):
        self.seed_desktop()
        other_org = Organization.objects.create(name='Foreign')
        foreign = Customer.objects.create(organization=other_org, name='Secret')
        with self.database.session_factory() as session:
            changes = SyncRepository(session).export()
        for row in changes:
            row['updated_at'] = (timezone.now() + timedelta(seconds=1)).isoformat()
            if row['entity'] == 'customers':
                row['fields']['name'] = 'Should rollback'
            if row['entity'] == 'deals':
                row['fields']['customer_uuid'] = str(foreign.uuid)
        with self.assertRaises(SyncError):
            self.sync.client.request('exchange', {'organization': str(self.organization.uuid), 'changes': changes})
        self.assertFalse(Customer.objects.filter(name='Should rollback').exists())

    def test_single_deal_and_task_deletion_from_website(self):
        customer, deal, task = self.seed_desktop()
        self.assertEqual(self.client.post(f'/deals/{Deal.objects.get().pk}/delete/').status_code, 302)
        self.sync.synchronize()
        self.assertEqual(self.deals.list(), [])
        self.assertIsNone(self.tasks.get(task.id).deal_id)
        self.assertEqual(self.tasks.get(task.id).customer_id, customer.id)
        self.assertEqual(self.client.post(f'/tasks/{Task.objects.get().pk}/delete/').status_code, 302)
        self.sync.synchronize()
        self.assertEqual(self.tasks.list(), [])
        self.assertEqual(len(self.customers.list()), 1)

    def test_equal_timestamp_server_wins_and_newer_local_edit_resurrects(self):
        customer, _, _ = self.seed_desktop()
        original = Customer.objects.get().updated_at
        with self.database.session_factory.begin() as session:
            obj = session.get(LocalCustomer, customer.id)
            obj.name = 'Equal-time conflict'
            obj.updated_at = original.replace(tzinfo=None)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(obj, 'updated_at')
        self.sync.synchronize()
        self.assertEqual(self.customers.get(customer.id).name, 'Desktop клиент')
        with self.database.session_factory() as session:
            self.assertEqual(session.get(LocalCustomer, customer.id).updated_at, original.replace(tzinfo=None))
        Customer.objects.get().delete()
        newer = timezone.now() + timedelta(seconds=1)
        with self.database.session_factory.begin() as session:
            obj = session.get(LocalCustomer, customer.id)
            obj.name = 'Restored by newer edit'
            obj.updated_at = newer.replace(tzinfo=None)
        self.sync.synchronize()
        self.assertEqual(Customer.objects.get(uuid=customer.uuid).name, 'Restored by newer edit')
        self.assertFalse(Tombstone.objects.filter(entity='customers', uuid=customer.uuid).exists())
