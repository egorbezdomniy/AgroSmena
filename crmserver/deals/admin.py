from django.contrib import admin
from deals.models import Deal


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ['title', 'customer', 'amount', 'stage', 'expected_close_date']
    list_filter = ['stage']
    search_fields = ['title', 'customer__name', 'uuid']
    autocomplete_fields = ['customer']
    readonly_fields = ['uuid', 'created_at', 'updated_at']
