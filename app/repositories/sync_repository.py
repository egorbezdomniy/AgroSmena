from datetime import date, datetime, timezone
from decimal import Decimal
import json

from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Customer, Deal, Task
from app.models.base import utc_now
from app.models.sync import SyncDeletion, SyncState

MODELS = {'customers': Customer, 'deals': Deal, 'tasks': Task}


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)


@event.listens_for(Session, 'before_flush')
def track_deletions(session, flush_context, instances):
    if session.info.get('sync_import'):
        return
    stamp = utc_now()
    deleted = list(session.deleted)
    for obj in deleted:
        entity = next((name for name, model in MODELS.items() if isinstance(obj, model)), None)
        if entity is None:
            continue
        marker = session.get(SyncDeletion, (entity, obj.uuid))
        if marker is None:
            session.add(SyncDeletion(entity=entity, uuid=obj.uuid, updated_at=stamp))
        else:
            marker.updated_at = stamp
        for relation, model in [('customer_id', Customer), ('deal_id', Deal)]:
            if isinstance(obj, model):
                for task in session.scalars(select(Task).where(getattr(Task, relation) == obj.id)):
                    if task not in session.deleted:
                        setattr(task, relation, None)
                        task.updated_at = stamp


class SyncRepository:
    def __init__(self, session):
        self.session = session

    def state(self):
        return self.session.get(SyncState, 1)

    def export(self):
        changes = []
        for entity, model in MODELS.items():
            for obj in self.session.scalars(select(model)):
                fields = {}
                for column in model.__table__.columns:
                    key = column.name
                    if key in {'id', 'uuid', 'created_at', 'updated_at'}:
                        continue
                    value = getattr(obj, key)
                    if key in {'customer_id', 'deal_id'}:
                        relation = key.removesuffix('_id')
                        linked = getattr(obj, relation)
                        fields[f'{relation}_uuid'] = linked.uuid if linked else None
                    elif key == 'assignee_usernames':
                        try:
                            assignees = json.loads(value)
                            fields[key] = assignees if isinstance(assignees, list) else []
                        except (TypeError, ValueError):
                            fields[key] = []
                    else:
                        fields[key] = value.isoformat() if isinstance(value, date) else str(value) if isinstance(value, Decimal) else value
                changes.append({'entity': entity, 'uuid': obj.uuid, 'created_at': iso(obj.created_at),
                                'updated_at': iso(obj.updated_at), 'deleted': False, 'fields': fields})
        changes.extend({'entity': row.entity, 'uuid': row.uuid, 'updated_at': iso(row.updated_at), 'deleted': True}
                       for row in self.session.scalars(select(SyncDeletion)))
        return changes

    def apply_snapshot(self, changes):
        self.session.info['sync_import'] = True
        live = {entity: {} for entity in MODELS}
        tombs = []
        seen = set()
        for row in changes:
            key = (row['entity'], row['uuid'])
            if key in seen or row['entity'] not in MODELS:
                raise ValueError('Некорректный пакет синхронизации сервера.')
            seen.add(key)
            if row['deleted']:
                tombs.append(row)
            else:
                live[row['entity']][row['uuid']] = row
        # Server response is a full authoritative snapshot after merging our transaction.
        for entity in reversed(MODELS):
            for obj in self.session.scalars(select(MODELS[entity])):
                if obj.uuid not in live[entity]:
                    self.session.delete(obj)
            self.session.flush()
        for entity, model in MODELS.items():
            for uid, row in live[entity].items():
                obj = self.session.scalar(select(model).where(model.uuid == uid))
                if obj is None:
                    obj = model(uuid=uid)
                    self.session.add(obj)
                fields = dict(row['fields'])
                for relation, linked_model in [('customer', Customer), ('deal', Deal)]:
                    if f'{relation}_uuid' in fields:
                        linked_uuid = fields.pop(f'{relation}_uuid')
                        linked = self.session.scalar(select(linked_model).where(linked_model.uuid == linked_uuid),
                                                     execution_options={'autoflush': False}) if linked_uuid else None
                        if linked_uuid and linked is None:
                            raise ValueError('Сервер вернул запись без связанного клиента/сделки.')
                        setattr(obj, relation, linked)
                for key, value in fields.items():
                    if key not in model.__table__.columns or key in {'id', 'uuid', 'created_at', 'updated_at', 'customer_id', 'deal_id'}:
                        raise ValueError('Неизвестное поле в ответе сервера.')
                    if key in {'due_date', 'expected_close_date'} and value:
                        value = date.fromisoformat(value)
                    if key == 'amount':
                        value = Decimal(value)
                    if key == 'assignee_usernames':
                        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                            raise ValueError('Сервер вернул некорректных исполнителей задачи.')
                        value = json.dumps(list(dict.fromkeys(value)), ensure_ascii=False)
                    setattr(obj, key, value)
                obj.created_at = parse_time(row['created_at'])
                obj.updated_at = parse_time(row['updated_at'])
                flag_modified(obj, 'updated_at')  # Never let SQLAlchemy invent a newer imported version.
                self.session.flush()
        for marker in self.session.scalars(select(SyncDeletion)):
            self.session.delete(marker)
        self.session.flush()
        for row in tombs:
            self.session.add(SyncDeletion(entity=row['entity'], uuid=row['uuid'], updated_at=parse_time(row['updated_at'])))
