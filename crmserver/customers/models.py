from django.db import models
from crmserver.models import OrganizationOwnedModel


class Customer(OrganizationOwnedModel):
    name = models.CharField('Имя', max_length=200, db_index=True)
    company_name = models.CharField('Компания', max_length=200, blank=True, default='')
    phone = models.CharField('Телефон', max_length=50, blank=True, default='')
    email = models.EmailField('Email', max_length=200, blank=True, default='')
    telegram = models.CharField('Telegram', max_length=100, blank=True, default='')
    position = models.CharField('Должность', max_length=150, blank=True, default='')
    notes = models.TextField('Заметки', blank=True, default='')

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'

    def __str__(self):
        return self.name
