"""Read-only counts; never emit CRM fields, identifiers, SQL or parameters."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.models import F

from deals.models import Deal
from tasks.models import Task


def inspect_integrity(using='default'):
    connection = connections[using]
    if connection.vendor != 'postgresql' or connection.in_atomic_block:
        raise CommandError('Проверка требует отдельной транзакции PostgreSQL.')
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute("SET LOCAL statement_timeout = '25s'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
        counts = {
            'deal_customer_organization': Deal.objects.using(using).exclude(
                organization_id=F('customer__organization_id')).count(),
            'task_customer_organization': Task.objects.using(using).filter(
                customer_id__isnull=False).exclude(organization_id=F('customer__organization_id')).count(),
            'task_deal_organization': Task.objects.using(using).filter(
                deal_id__isnull=False).exclude(organization_id=F('deal__organization_id')).count(),
            'task_assignee_organization': Task.assignees.through.objects.using(using).exclude(
                task__organization_id=F('membership__organization_id')).count(),
        }
    return {'categories': counts, 'violation_count': sum(counts.values())}


class Command(BaseCommand):
    help = 'Только чтение: число межорганизационных связей CRM и назначений (без данных записей).'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default', choices=tuple(connections))

    def handle(self, *args, **options):
        result = inspect_integrity(options['database'])
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result['violation_count']:
            raise CommandError('Найдены нарушения целостности; данные не изменены.')
