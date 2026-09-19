from rest_framework import serializers
from accounts.api import OrganizationSerializer
from customers.models import Customer
from deals.models import Deal


class DealSerializer(OrganizationSerializer):
    customer_id = serializers.PrimaryKeyRelatedField(source='customer', queryset=Customer.objects.all())

    class Meta:
        model = Deal
        fields = ['id', 'uuid', 'title', 'customer_id', 'amount', 'stage',
                  'description', 'expected_close_date', 'created_at', 'updated_at']
        read_only_fields = ['id', 'uuid', 'created_at', 'updated_at']
