import uuid
from django.core.exceptions import ValidationError
from django.db import models, transaction, router


class TimestampedUUIDModel(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def validate_immutable_relations(self, *fields, using=None):
        # There is no transfer operation that repairs related rows/assignments.
        if not self.pk:
            return
        alias = using or self._state.db or router.db_for_read(type(self), instance=self)
        previous = type(self).objects.using(alias).filter(pk=self.pk).values(*fields).first()
        if previous:
            errors = {field: 'Изменение этой связи у существующей записи не поддерживается.'
                      for field in fields if previous[field] != getattr(self, f'{field}_id')}
            if errors:
                raise ValidationError(errors)


class OrganizationOwnedModel(TimestampedUUIDModel):
    organization = models.ForeignKey('accounts.Organization', on_delete=models.PROTECT,
                                     verbose_name='Организация')

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Web/API writes share the sync lock, so an exchange sees a consistent organization.
        from accounts.models import Organization
        alias = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=alias):
            if self.organization_id:
                Organization.objects.using(alias).select_for_update().get(pk=self.organization_id)
            self.validate_immutable_relations('organization', using=alias)
            return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.validate_immutable_relations('organization')
        errors = {}
        for field in ('customer', 'deal'):
            if getattr(self, f'{field}_id', None) and self.organization_id:
                if getattr(self, field).organization_id != self.organization_id:
                    errors[field] = 'Запись должна принадлежать той же организации.'
        if errors:
            raise ValidationError(errors)
