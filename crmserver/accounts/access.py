from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from accounts.models import Membership


def membership_for(user):
    if not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.select_related('organization').filter(user=user).first()


class OrganizationRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.membership = membership_for(request.user)
        if self.membership is None:
            raise PermissionDenied('Вы не состоите в организации. Обратитесь к администратору.')
        self.organization = self.membership.organization
        self.check_membership()
        return super().dispatch(request, *args, **kwargs)

    def check_membership(self):
        pass


class OrganizationQuerysetMixin(OrganizationRequiredMixin):
    def get_queryset(self):
        return super().get_queryset().filter(organization=self.organization)


def organization_context(request):
    from catalog.models import Storefront
    membership = membership_for(request.user)
    return {'current_membership': membership,
            'current_storefront': Storefront.objects.defer('logo').filter(organization=membership.organization).first() if membership else None,
            'can_manage_users': bool(membership and membership.role == Membership.Role.ADMIN)}
