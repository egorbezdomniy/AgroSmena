from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.access import membership_for
from accounts.permissions import HasOrganization


class OrganizationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrganization]

    def get_queryset(self):
        return super().get_queryset().filter(organization=self.request.crm_membership.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.crm_membership.organization)

    def perform_update(self, serializer):
        serializer.save(organization=self.request.crm_membership.organization)


class OrganizationSerializer(serializers.ModelSerializer):
    """Restrict both accepted relation IDs and browsable API choices."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        membership = membership_for(request.user) if request else None
        for name in ('customer_id', 'deal_id'):
            if name in self.fields:
                field = self.fields[name]
                field.queryset = (field.queryset.filter(organization=membership.organization)
                                  if membership else field.queryset.none())
