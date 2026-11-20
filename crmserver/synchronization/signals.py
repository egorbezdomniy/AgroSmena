from contextvars import ContextVar

from django.contrib.auth import get_user_model
from django.db.models import F
from django.db.models.query import QuerySet
from django.db.models.functions import Greatest
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from customers.models import Customer
from deals.models import Deal
from tasks.models import Task
from accounts.models import Membership, Organization
from .models import Tombstone

deletion_time = ContextVar('sync_deletion_time', default=None)
ENTITIES = {Customer: 'customers', Deal: 'deals', Task: 'tasks'}


@receiver(pre_delete, sender=Membership)
def lock_membership_deletion(sender, instance, using, origin, **kwargs):
    # Collector.delete() is atomic and calls pre_delete before deleting through
    # rows. Cover admin delete, queryset delete and a cascading User deletion.
    organization_ids = [instance.organization_id]
    if isinstance(origin, QuerySet):
        selected = origin.using(using)
        if origin.model is Membership:
            organization_ids = selected.values('organization_id')
        elif origin.model is get_user_model():
            organization_ids = Membership.objects.using(using).filter(
                user_id__in=selected.values('pk')).values('organization_id')
        elif origin.model is Organization:
            organization_ids = selected.values('pk')
    # Global admin can delete across organizations: use one stable lock order,
    # rather than the possibly interleaved membership/user PK order.
    list(Organization.objects.using(using).filter(pk__in=organization_ids)
         .order_by('pk').select_for_update())


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
