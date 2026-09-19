from django.contrib import admin

from accounts.models import Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'uuid', 'created_at']
    search_fields = ['name', 'uuid']
    readonly_fields = ['uuid', 'created_at', 'updated_at']


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'role']
    list_filter = ['role', 'organization']
    search_fields = ['user__username', 'organization__name']
    readonly_fields = ['uuid', 'created_at', 'updated_at']
