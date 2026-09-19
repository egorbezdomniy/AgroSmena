from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from crmserver.models import OrganizationOwnedModel


class Deal(OrganizationOwnedModel):
    class Stage(models.TextChoices):
        NEW = 'Новая', 'Новая'
        CONTACT = 'Контакт', 'Контакт'
        OFFER = 'Предложение', 'Предложение'
        NEGOTIATION = 'Переговоры', 'Переговоры'
        WON = 'Успешно', 'Успешно'
        LOST = 'Проиграна', 'Проиграна'

    title = models.CharField('Название', max_length=250, db_index=True)
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='deals')
    amount = models.DecimalField('Сумма', max_digits=14, decimal_places=2,
                                 default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0'))])
    stage = models.CharField('Стадия', max_length=50, choices=Stage.choices, default=Stage.NEW, db_index=True)
    description = models.TextField('Описание', blank=True, default='')
    expected_close_date = models.DateField('Дата закрытия', null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Сделка'
        verbose_name_plural = 'Сделки'
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name='deal_amount_nonnegative')]

    def __str__(self):
        return self.title
