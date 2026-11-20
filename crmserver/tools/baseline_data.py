"""Deterministic fixtures for a verified, fresh, owned PostgreSQL cluster. No cleanup API."""
import json
import os
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def assert_disposable():
    from django.conf import settings
    from django.db import connection
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'crmserver.baseline_settings':
        raise RuntimeError('Only baseline_settings is allowed')
    root = Path(os.environ['STAGE1_VERIFY_ROOT']).resolve()
    marker = json.loads((root / 'baseline-owner.json').read_text(encoding='utf-8'))
    if (marker['purpose'] != 'agrosmena-synthetic-baseline-v1'
            or settings.DATABASES['default']['HOST'] != '127.0.0.1'
            or int(settings.DATABASES['default']['PORT']) != marker['port']):
        raise RuntimeError('Not an explicitly owned loopback cluster')
    with connection.cursor() as cursor:
        cursor.execute('SHOW data_directory')
        directory = Path(cursor.fetchone()[0]).resolve()
        cursor.execute('SELECT current_database()')
        database = cursor.fetchone()[0]
    if directory != (root / 'pgdata').resolve() or database != 'baseline_synthetic':
        raise RuntimeError('Connected database does not belong to this experiment')
    return root


def uid(label):
    return uuid5(NAMESPACE_URL, 'agrosmena-baseline-v1/' + label)


def generate(anchor=date(2026, 10, 16), seed=20261016):
    from django.contrib.auth import get_user_model
    from django.db import connection
    from accounts.models import Membership, Organization
    from catalog.models import Attribute, Product, ProductType, Storefront
    from customers.models import Customer
    from deals.models import Deal
    from tasks.models import Task
    from synchronization.models import Tombstone
    assert_disposable()
    if any(model.objects.exists() for model in (Organization, Customer, Deal, Task, Tombstone, Product, get_user_model())):
        raise RuntimeError('Generator refuses a populated database; create a NEW disposable cluster')
    rng = random.Random(seed)
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    layouts = [('small', 1000), ('medium', 5000), ('large', 9000)] + [(f'peer{i}', 1000) for i in range(4)]
    output = {'seed': seed, 'anchor': anchor.isoformat(), 'organizations': []}
    for label, total in layouts:
        org = Organization.objects.create(uuid=uid(label), name='Synthetic ' + label)
        members = []
        for i in range(5):
            user = get_user_model()(username=f'baseline_{label}_{i}', first_name='Synthetic', last_name=f'Member {i}')
            user.set_unusable_password()
            user.save()
            members.append(Membership.objects.create(organization=org, user=user,
                role=['admin', 'supervisor', 'manager', 'manager', 'manager'][i], uuid=uid(f'{label}/member/{i}')))
        nc, nd, nt = total * 4 // 10, total * 3 // 10, total * 3 // 10
        customers = Customer.objects.bulk_create([Customer(organization=org, uuid=uid(f'{label}/customer/{i}'),
            name=f'Клиент {i:05d}', company_name=f'Синтетическая компания {i % 50}',
            email=f'customer{i}@example.test', phone=f'+7000{i:07d}', position='Менеджер',
            notes='Синтетическая заметка. ' * (1 + i % 4)) for i in range(nc)], batch_size=500)
        stages = ([Deal.Stage.NEW] * 6 + [Deal.Stage.CONTACT] * 4 + [Deal.Stage.OFFER] * 4
                  + [Deal.Stage.NEGOTIATION] * 2 + [Deal.Stage.WON] * 3 + [Deal.Stage.LOST])
        deals = Deal.objects.bulk_create([Deal(organization=org, uuid=uid(f'{label}/deal/{i}'),
            customer=customers[0 if i < nd // 5 else rng.randrange(nc)], title=f'Сделка {i:05d}',
            amount=Decimal(1000 + i * 37) / 100, stage=stages[i % 20],
            expected_close_date=anchor + timedelta(days=i % 60 - 15), description='Синтетическое предложение. ' * 3)
            for i in range(nd)], batch_size=500)
        tasks = []
        statuses = [Task.Status.NEW] * 8 + [Task.Status.IN_PROGRESS] * 6 + [Task.Status.DONE] * 5 + [Task.Status.CANCELED]
        for i in range(nt):
            deal = deals[i % nd] if i % 10 < 7 else None
            customer = deal.customer if deal else (customers[rng.randrange(nc)] if i % 10 < 9 else None)
            tasks.append(Task(organization=org, uuid=uid(f'{label}/task/{i}'), title=f'Задача {i:05d}',
                description='Синтетическая рабочая задача. ' * 3, customer=customer, deal=deal,
                due_date=anchor + timedelta(days=i % 45 - 15) if i % 10 else None,
                status=statuses[(i * 7) % 20],
                priority=[Task.Priority.HIGH, Task.Priority.NORMAL, Task.Priority.NORMAL,
                          Task.Priority.NORMAL, Task.Priority.LOW][i % 5]))
        Task.objects.bulk_create(tasks, batch_size=500)
        through = Task.assignees.through
        assignments = []
        for i, task in enumerate(tasks):
            member_indices = ([] if i % 10 < 5 else [0] if i % 10 < 7 else
                              [1 + i % 4] if i % 10 < 9 else [0, 1 + i % 4])
            assignments.extend(through(task_id=task.pk, membership_id=members[j].pk) for j in member_indices)
        through.objects.bulk_create(assignments, batch_size=500)
        for model in (Customer, Deal, Task):
            model.objects.filter(organization=org).update(created_at=stamp, updated_at=stamp + timedelta(days=1))
        tomb_count = total // 20
        Tombstone.objects.bulk_create([Tombstone(organization=org, entity=['customers', 'deals', 'tasks'][i % 3],
            uuid=uid(f'{label}/deleted/{i}'), updated_at=stamp + timedelta(days=2)) for i in range(tomb_count)])
        output['organizations'].append({'label': label, 'organization_id': org.pk, 'uuid': str(org.uuid),
            'customers': nc, 'deals': nd, 'tasks': nt, 'live': total, 'tombstones': tomb_count,
            'members': 5, 'common_tasks': nt // 2, 'admin_visible_tasks': nt * 8 // 10,
            'admin_snapshot_records': nc + nd + nt * 8 // 10 + tomb_count,
            'customer_id': customers[0].pk, 'deal_id': deals[0].pk, 'task_id': tasks[0].pk,
            'member_id': members[0].pk, 'user_id': members[0].user_id})
    large = next(row for row in output['organizations'] if row['label'] == 'large')
    store = Storefront.objects.create(organization_id=large['organization_id'], slug='baseline-catalog')
    types = []
    for t in range(3):
        kind = ProductType.objects.create(storefront=store, name=f'Тип {t}')
        weight = Attribute.objects.create(product_type=kind, key=uid(f'catalog/weight/{t}'), name='Вес', kind='number')
        color = Attribute.objects.create(product_type=kind, key=uid(f'catalog/color/{t}'), name='Цвет', kind='choice',
                                         options=['Красный', 'Белый', 'Жёлтый'])
        Product.objects.bulk_create([Product(product_type=kind, name=f'Товар {t}-{i:03d}',
            description='Синтетический товар. ' * 5, price=Decimal(100 + i * 11),
            in_stock=i % 4 != 0, published=i % 10 != 0,
            values={weight.value_key: 1 + i % 20, color.value_key: ['Красный', 'Белый', 'Жёлтый'][i % 3]})
            for i in range(100)])
        types.append({'id': kind.pk, 'weight_key': weight.value_key, 'color_key': color.value_key})
    output['catalog'] = {'products': 300, 'published': 270, 'types': types, 'attributes': 6}
    with connection.cursor() as cursor:
        cursor.execute('ANALYZE')
    return output
