from django.db import models


class Tombstone(models.Model):
    organization = models.ForeignKey('accounts.Organization', on_delete=models.PROTECT)
    entity = models.CharField(max_length=20)
    uuid = models.UUIDField()
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['entity', 'uuid'], name='sync_deleted_uuid_unique')]
