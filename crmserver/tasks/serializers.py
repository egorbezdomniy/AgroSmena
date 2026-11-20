from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from accounts.api import OrganizationSerializer
from customers.models import Customer
from deals.models import Deal
from tasks.models import Task, lock_task_assignees
from accounts.access import membership_for
from accounts.models import Membership


class AssigneeUsernamesField(serializers.Field):
    def get_attribute(self, instance):
        return instance

    def to_representation(self, task):
        if hasattr(task, '_sync_ordered_assignees'):
            # This list is explicitly ordered by the DB; querying the manager again
            # (including order_by/values_list) would bypass the prepared prefetch.
            return [member.user.username for member in task._sync_ordered_assignees]
        return list(task.assignees.order_by('user__username').values_list('user__username', flat=True))

    def to_internal_value(self, data):
        if not isinstance(data, list) or len(data) > 200:
            raise serializers.ValidationError('Ожидается список сотрудников.')
        usernames = []
        for value in data:
            if not isinstance(value, str) or not value.strip() or len(value) > 150:
                raise serializers.ValidationError('Некорректный логин сотрудника.')
            username = value.strip()
            if username not in usernames:
                usernames.append(username)
        return usernames


class TaskSerializer(OrganizationSerializer):
    assignee_usernames = AssigneeUsernamesField(required=False)
    customer_id = serializers.PrimaryKeyRelatedField(
        source='customer', queryset=Customer.objects.all(), required=False, allow_null=True
    )
    deal_id = serializers.PrimaryKeyRelatedField(
        source='deal', queryset=Deal.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Task
        fields = ['id', 'uuid', 'title', 'description', 'customer_id', 'deal_id',
                  'due_date', 'priority', 'status', 'assignee_usernames', 'created_at', 'updated_at']
        read_only_fields = ['id', 'uuid', 'created_at', 'updated_at']

    def validate(self, attrs):
        customer = attrs.get('customer', getattr(self.instance, 'customer', None))
        deal = attrs.get('deal', getattr(self.instance, 'deal', None))
        if customer and deal and deal.customer_id != customer.id:
            raise serializers.ValidationError({'deal_id': 'Сделка принадлежит другому клиенту.'})
        if 'assignee_usernames' in attrs:
            request = self.context.get('request')
            membership = getattr(request, 'crm_membership', None) or (
                membership_for(request.user) if request else None)
            usernames = attrs['assignee_usernames']
            members = list(Membership.objects.filter(
                organization=membership.organization, user__is_active=True,
                user__username__in=usernames).select_related('user')) if membership else []
            if {item.user.username for item in members} != set(usernames):
                raise serializers.ValidationError({'assignee_usernames': 'Сотрудник не найден в организации.'})
            attrs['assignee_usernames'] = members
        return attrs

    def create(self, validated_data):
        members = validated_data.pop('assignee_usernames', [])
        members = self.lock_assignees(validated_data['organization'].pk, members)
        task = super().create(validated_data)
        task.assignees.set(members)
        return task

    def update(self, instance, validated_data):
        missing = object()
        members = validated_data.pop('assignee_usernames', missing)
        if members is not missing:
            members = self.lock_assignees(instance.organization_id, members)
        task = super().update(instance, validated_data)
        if members is not missing:
            task.assignees.set(members)
        return task

    def lock_assignees(self, organization_id, members):
        try:
            return lock_task_assignees(organization_id, members, require_active=True,
                                       usernames=[member.user.username for member in members])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'assignee_usernames': exc.messages}) from exc
