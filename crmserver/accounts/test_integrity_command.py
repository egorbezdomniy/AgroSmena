import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from accounts.models import Membership, Organization
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task


class IntegrityCommandTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Synthetic own')
        self.other = Organization.objects.create(name='Synthetic other')
        self.customer = Customer.objects.create(organization=self.org, name='Never print this CRM value')
        self.foreign = Customer.objects.create(organization=self.other, name='Synthetic foreign')
        self.deal = Deal.objects.create(organization=self.org, customer=self.customer, title='Synthetic deal')
        self.task = Task.objects.create(organization=self.org, customer=self.customer, deal=self.deal,
                                       title='Never print this task value')
        self.member = Membership.objects.create(organization=self.org,
            user=get_user_model().objects.create_user('synthetic-own'))
        self.foreign_member = Membership.objects.create(organization=self.other,
            user=get_user_model().objects.create_user('synthetic-foreign'))
        self.task.assignees.add(self.member)

    def test_clean_fixture_reports_zero_including_nullable_links(self):
        Task.objects.create(organization=self.org, title='Common, no links')
        output = StringIO()
        call_command('check_crm_integrity', stdout=output)
        self.assertEqual(json.loads(output.getvalue()), {'violation_count': 0, 'categories': {
            'deal_customer_organization': 0, 'task_customer_organization': 0,
            'task_deal_organization': 0, 'task_assignee_organization': 0}})

    def test_dirty_fixture_counts_relations_without_content_or_mutation(self):
        # Deliberately construct legacy corruption ONLY in this disposable test DB.
        foreign_deal = Deal.objects.create(organization=self.other, customer=self.foreign, title='Synthetic foreign')
        Deal.objects.filter(pk=self.deal.pk).update(customer=self.foreign)
        Task.objects.filter(pk=self.task.pk).update(customer=self.foreign, deal=foreign_deal)
        self.task.assignees.add(self.foreign_member)
        before = (list(Deal.objects.values()), list(Task.objects.values()),
                  list(Task.assignees.through.objects.values()))
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command('check_crm_integrity', stdout=output)
        self.assertEqual(json.loads(output.getvalue()), {'violation_count': 4, 'categories': {
            'deal_customer_organization': 1, 'task_customer_organization': 1,
            'task_deal_organization': 1, 'task_assignee_organization': 1}})
        self.assertNotIn('Never print', output.getvalue())
        self.assertNotIn('synthetic-foreign', output.getvalue())
        self.assertEqual(before, (list(Deal.objects.values()), list(Task.objects.values()),
                                 list(Task.assignees.through.objects.values())))
