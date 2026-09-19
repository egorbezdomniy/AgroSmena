from django.conf import settings
from django.db import models

from crmserver.models import TimestampedUUIDModel


class Organization(TimestampedUUIDModel):
    name = models.CharField('Название организации', max_length=200)

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'Организация'
        verbose_name_plural = 'Организации'

    def __str__(self):
        return self.name


class Membership(TimestampedUUIDModel):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Администратор'
        SUPERVISOR = 'supervisor', 'Руководитель'
        MANAGER = 'manager', 'Менеджер'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membership')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField('Роль', max_length=20, choices=Role.choices, default=Role.MANAGER)

    class Meta:
        ordering = ['user__username']
        verbose_name = 'Участник организации'
        verbose_name_plural = 'Участники организаций'

    def __str__(self):
        return f'{self.user} — {self.organization}'
