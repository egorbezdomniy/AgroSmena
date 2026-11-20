from accounts.api import OrganizationViewSet
from django.db import transaction
from tasks.models import Task, visible_tasks
from tasks.serializers import TaskSerializer


class TaskViewSet(OrganizationViewSet):
    queryset = Task.objects.select_related('customer', 'deal').all()
    serializer_class = TaskSerializer
    search_fields = ['title', 'description', 'customer__name', 'deal__title']

    @transaction.atomic
    def perform_create(self, serializer):
        # The serializer writes the row first and M2M afterwards.
        return super().perform_create(serializer)

    @transaction.atomic
    def perform_update(self, serializer):
        return super().perform_update(serializer)

    def get_queryset(self):
        return visible_tasks(super().get_queryset(), self.request.crm_membership).prefetch_related('assignees__user')
