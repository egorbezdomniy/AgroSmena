from django.contrib import admin
from customers.models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'company_name', 'phone', 'email', 'created_at']
    search_fields = ['name', 'company_name', 'phone', 'email', 'uuid']
    readonly_fields = ['uuid', 'created_at', 'updated_at']
