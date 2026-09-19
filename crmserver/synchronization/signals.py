from contextvars import ContextVar

from django.db.models import F
from django.db.models.functions import Greatest
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from customers.models import Customer
from deals.models import Deal
from tasks.models import Task
from accounts.models import Organization
from .models import Tombstone

deletion_time = ContextVar('sync_deletion_time', default=None)
ENTITIES = {Customer: 'customers', Deal: 'deals', Task: 'tasks'}


@receiver(pre_delete, sender=Customer)
@receiver(pre_delete, sender=Deal)
@receiver(pre_delete, sender=Task)
def record_deletion(sender, instance, using, **kwargs):
    Organization.objects.using(using).select_for_update().get(pk=instance.organization_id)
    stamp = deletion_time.get() or timezone.now()
    marker, created = Tombstone.objects.using(using).get_or_create(
        entity=ENTITIES[sender], uuid=instance.uuid,
        defaults={'organization_id': instance.organization_id, 'updated_at': stamp})
    if not created and marker.updated_at < stamp:
        marker.updated_at = stamp
        marker.save(using=using, update_fields=['updated_at'])
    # Django's SET_NULL bypasses save()/auto_now; make those changes visible to sync.
    if sender in (Customer, Deal):
        relation = 'customer_id' if sender is Customer else 'deal_id'
        Task.objects.using(using).filter(**{relation: instance.pk}).update(
            updated_at=Greatest(F('updated_at'), stamp))
