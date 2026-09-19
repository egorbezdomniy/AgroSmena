from rest_framework.permissions import BasePermission

from accounts.access import membership_for


class HasOrganization(BasePermission):
    message = 'Вы не состоите в организации.'

    def has_permission(self, request, view):
        request.crm_membership = membership_for(request.user)
        return request.crm_membership is not None
