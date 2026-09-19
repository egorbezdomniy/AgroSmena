from django.contrib.admin import AdminSite


class SystemAdminSite(AdminSite):
    """Global maintenance is reserved for trusted system superusers."""

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser
