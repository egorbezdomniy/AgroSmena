from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from uuid import UUID
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Organization, Membership
from customers.models import Customer
from customers.serializers import CustomerSerializer
from rest_framework import serializers
from deals.models import Deal
from deals.serializers import DealSerializer
from tasks.models import Task, visible_tasks
from tasks.serializers import TaskSerializer
from .models import Tombstone
from .signals import deletion_time

class SyncCustomerSerializer(CustomerSerializer):
    # Desktop v0.1 historically allowed free text here. Keep normal web/API validation strict.
    email = serializers.CharField(max_length=200, required=False, allow_blank=True)


MODELS = {'customers': Customer, 'deals': Deal, 'tasks': Task}
SERIALIZERS = {'customers': SyncCustomerSerializer, 'deals': DealSerializer, 'tasks': TaskSerializer}


def serialize_record(entity, obj):
    fields = dict(SERIALIZERS[entity](obj).data)
    for key in ('id', 'uuid', 'created_at', 'updated_at'):
        fields.pop(key, None)
    for relation in ('customer', 'deal'):
        if f'{relation}_id' in fields:
            linked = getattr(obj, relation)
            fields.pop(f'{relation}_id')
            fields[f'{relation}_uuid'] = str(linked.uuid) if linked else None
    return {'entity': entity, 'uuid': str(obj.uuid), 'created_at': obj.created_at.isoformat(),
            'updated_at': obj.updated_at.isoformat(), 'deleted': False, 'fields': fields}


@transaction.atomic
def exchange(request, payload):
    membership = request.crm_membership
    organization = Organization.objects.select_for_update().get(pk=membership.organization_id)
    if str(organization.uuid) != str(payload['organization']):
        raise PermissionDenied('Организация локальной базы не совпадает с аккаунтом.')
    if not Membership.objects.filter(user=request.user, organization=organization).exists():
        raise PermissionDenied('Доступ к организации отозван.')
    changes = payload['changes']
    # Apply parent deletions first so cascading tombstones participate in conflict resolution.
    changes = sorted(changes, key=lambda row: (not row['deleted'], list(MODELS).index(row['entity'])))
    for row in changes:
        entity, uid, stamp = row['entity'], row['uuid'], row['updated_at']
        model = MODELS[entity]
        obj = model.objects.select_for_update().filter(uuid=uid).first()
        tomb = Tombstone.objects.filter(entity=entity, uuid=uid).first()
        if any(item and item.organization_id != organization.pk for item in (obj, tomb)):
            raise ValidationError('Недопустимый UUID в пакете синхронизации.')
        latest = max([item.updated_at for item in (obj, tomb) if item], default=None)
        # Equal timestamps are resolved consistently in favor of the server.
        if latest is not None and stamp <= latest:
            continue
        if entity == 'tasks' and obj and not visible_tasks(Task.objects.filter(pk=obj.pk), membership).exists():
            raise PermissionDenied('Задача назначена другим сотрудникам.')
        if row['deleted']:
            if obj:
                token = deletion_time.set(stamp)
                try:
                    obj.delete()
                finally:
                    deletion_time.reset(token)
            Tombstone.objects.update_or_create(entity=entity, uuid=uid,
                defaults={'organization': organization, 'updated_at': stamp})
            continue
        fields = dict(row['fields'])
        for relation, related_model in [('customer', Customer), ('deal', Deal)]:
            if (entity == 'deals' and relation == 'customer') or entity == 'tasks':
                related_uuid = fields.pop(f'{relation}_uuid', None)
                linked = None
                if related_uuid:
                    try:
                        related_uuid = UUID(str(related_uuid))
                        linked = related_model.objects.filter(organization=organization, uuid=related_uuid).first()
                    except (ValueError, DjangoValidationError):
                        raise ValidationError(f'Некорректный {relation}_uuid.') from None
                    if linked is None:
                        # A deleted parent cannot be reintroduced by a stale child record.
                        parent_entity = 'customers' if relation == 'customer' else 'deals'
                        deleted_parent = Tombstone.objects.filter(organization=organization, entity=parent_entity, uuid=related_uuid).first()
                        if deleted_parent:
                            if entity == 'deals':
                                if obj:
                                    token = deletion_time.set(max(stamp, deleted_parent.updated_at))
                                    try:
                                        obj.delete()
                                    finally:
                                        deletion_time.reset(token)
                                Tombstone.objects.update_or_create(entity=entity, uuid=uid,
                                    defaults={'organization': organization, 'updated_at': max(stamp, deleted_parent.updated_at)})
                                break
                            related_uuid = None
                        else:
                            raise ValidationError(f'Связанная запись {relation} не найдена в организации.')
                fields[f'{relation}_id'] = linked.pk if linked else None
        else:
            serializer = SERIALIZERS[entity](obj, data=fields, context={'request': request})
            serializer.is_valid(raise_exception=True)
            obj = serializer.save(organization=organization, uuid=uid)
            model.objects.filter(pk=obj.pk).update(created_at=row['created_at'], updated_at=stamp)
            if tomb:
                tomb.delete()
    records = []
    for entity, model in MODELS.items():
        queryset = model.objects.filter(organization=organization)
        if entity == 'deals':
            queryset = queryset.select_related('customer')
        if entity == 'tasks':
            queryset = visible_tasks(queryset, membership).select_related(
                'customer', 'deal').prefetch_related('assignees__user')
        records.extend(serialize_record(entity, obj) for obj in queryset)
    records.extend({'entity': tomb.entity, 'uuid': str(tomb.uuid), 'updated_at': tomb.updated_at.isoformat(),
                    'deleted': True} for tomb in Tombstone.objects.filter(organization=organization))
    members = Membership.objects.filter(organization=organization, user__is_active=True).select_related('user')
    return {'organization': str(organization.uuid), 'synced_at': timezone.now().isoformat(),
            'members': [{'username': item.user.username,
                         'name': item.user.get_full_name().strip() or item.user.username}
                        for item in members],
            'changes': records}
