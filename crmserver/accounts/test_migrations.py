from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyMigrationTests(TransactionTestCase):
    def test_legacy_rows_and_relations_preserved_without_granting_access(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [('customers', '0002_organization'), ('deals', '0002_organization'),
                  ('tasks', '0002_organization'), ('accounts', '0001_initial')]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            customer = apps.get_model('customers', 'Customer').objects.create(name='Legacy customer')
            deal = apps.get_model('deals', 'Deal').objects.create(title='Legacy deal', customer_id=customer.pk)
            task = apps.get_model('tasks', 'Task').objects.create(title='Legacy task', customer_id=customer.pk, deal_id=deal.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            organization = apps.get_model('accounts', 'Organization').objects.get(name='Данные до v0.5')
            self.assertEqual(apps.get_model('accounts', 'Membership').objects.count(), 0)
            for app, model, original in [('customers', 'Customer', customer), ('deals', 'Deal', deal), ('tasks', 'Task', task)]:
                row = apps.get_model(app, model).objects.get(pk=original.pk)
                self.assertEqual(row.organization_id, organization.pk)
                self.assertEqual(row.uuid, original.uuid)
                self.assertEqual(row.created_at, original.created_at)
                if app != 'customers':
                    self.assertEqual(row.customer_id, customer.pk)
        finally:
            MigrationExecutor(connection).migrate(latest)
