from accounts.api import OrganizationViewSet
from tasks.models import Task
from tasks.serializers import TaskSerializer


class TaskViewSet(OrganizationViewSet):
    queryset = Task.objects.select_related('customer', 'deal').all()
    serializer_class = TaskSerializer
    search_fields = ['title', 'description', 'customer__name', 'deal__title']
