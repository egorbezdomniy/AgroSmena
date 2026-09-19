from accounts.api import OrganizationViewSet
from deals.models import Deal
from deals.serializers import DealSerializer


class DealViewSet(OrganizationViewSet):
    queryset = Deal.objects.select_related('customer').all()
    serializer_class = DealSerializer
    search_fields = ['title', 'customer__name']
