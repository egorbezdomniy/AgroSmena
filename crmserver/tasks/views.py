from accounts.api import OrganizationViewSet
from tasks.models import Task, visible_tasks
from tasks.serializers import TaskSerializer


class TaskViewSet(OrganizationViewSet):
    queryset = Task.objects.select_related('customer', 'deal').all()
    serializer_class = TaskSerializer
    search_fields = ['title', 'description', 'customer__name', 'deal__title']

    def get_queryset(self):
        return visible_tasks(super().get_queryset(), self.request.crm_membership).prefetch_related('assignees__user')
