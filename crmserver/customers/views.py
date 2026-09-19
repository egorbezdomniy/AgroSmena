from accounts.api import OrganizationViewSet
from customers.models import Customer
from customers.serializers import CustomerSerializer


class CustomerViewSet(OrganizationViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    search_fields = ['name', 'company_name', 'phone', 'email', 'telegram']
