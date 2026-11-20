from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from crmserver.models import OrganizationOwnedModel


def lock_task_assignees(organization_id, members, *, require_active=False, usernames=None, using='default'):
    """Validate under O -> User locks, retained by the caller's outer atomic.

    Membership identity is immutable; its deletion takes O before through rows.
    User updates do not take O, so lock those rows too, in user PK order. Inspect
    activity/username AFTER waiting for that lock, not on cached form objects.
    """
    from accounts.models import Membership, Organization
    Organization.objects.using(using).select_for_update().only('pk').get(pk=organization_id)
    member_ids = {member.pk for member in members}
    current = list(Membership.objects.using(using).filter(
        organization_id=organization_id, pk__in=member_ids).select_related('user').only(
            'pk', 'organization_id', 'user_id', 'user__username', 'user__is_active')
        .order_by('user_id').select_for_update(of=('user',), no_key=True))
    if ({member.pk for member in current} != member_ids
            or (require_active and any(not member.user.is_active for member in current))
            or (usernames is not None and {member.user.username for member in current} != set(usernames))):
        raise ValidationError('Сотрудник не найден в организации или больше недоступен.')
    return current


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
    assignees = models.ManyToManyField('accounts.Membership', blank=True, related_name='assigned_tasks',
                                       verbose_name='Сотрудники')

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


def visible_tasks(queryset, membership):
    """Empty assignee set means that the task belongs to the whole organization."""
    return queryset.filter(Q(assignees__isnull=True) | Q(assignees=membership)).distinct()
