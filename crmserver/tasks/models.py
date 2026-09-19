from django.core.exceptions import ValidationError
from django.db import models
from crmserver.models import OrganizationOwnedModel


class Task(OrganizationOwnedModel):
    class Priority(models.TextChoices):
        LOW = 'Низкий', 'Низкий'
        NORMAL = 'Обычный', 'Обычный'
        HIGH = 'Высокий', 'Высокий'

    class Status(models.TextChoices):
        NEW = 'Новая', 'Новая'
        IN_PROGRESS = 'В работе', 'В работе'
        DONE = 'Выполнена', 'Выполнена'
        CANCELED = 'Отменена', 'Отменена'

    title = models.CharField('Название', max_length=250, db_index=True)
    description = models.TextField('Описание', blank=True, default='')
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='tasks')
    deal = models.ForeignKey('deals.Deal', on_delete=models.SET_NULL,
                             null=True, blank=True, related_name='tasks')
    due_date = models.DateField('Срок', null=True, blank=True, db_index=True)
    priority = models.CharField('Приоритет', max_length=30, choices=Priority.choices,
                                 default=Priority.NORMAL, db_index=True)
    status = models.CharField('Статус', max_length=30, choices=Status.choices,
                               default=Status.NEW, db_index=True)

    class Meta:
        ordering = ['due_date', 'id']
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'

    def clean(self):
        super().clean()
        if self.customer_id and self.deal_id and self.deal.customer_id != self.customer_id:
            raise ValidationError({'deal': 'Сделка принадлежит другому клиенту.'})

    def __str__(self):
        return self.title
