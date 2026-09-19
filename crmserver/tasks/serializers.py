from rest_framework import serializers
from accounts.api import OrganizationSerializer
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task


class TaskSerializer(OrganizationSerializer):
    customer_id = serializers.PrimaryKeyRelatedField(
        source='customer', queryset=Customer.objects.all(), required=False, allow_null=True
    )
    deal_id = serializers.PrimaryKeyRelatedField(
        source='deal', queryset=Deal.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Task
        fields = ['id', 'uuid', 'title', 'description', 'customer_id', 'deal_id',
                  'due_date', 'priority', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'uuid', 'created_at', 'updated_at']

    def validate(self, attrs):
        customer = attrs.get('customer', getattr(self.instance, 'customer', None))
        deal = attrs.get('deal', getattr(self.instance, 'deal', None))
        if customer and deal and deal.customer_id != customer.id:
            raise serializers.ValidationError({'deal_id': 'Сделка принадлежит другому клиенту.'})
        return attrs
