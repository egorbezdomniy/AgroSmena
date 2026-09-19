from django.contrib import admin
from tasks.models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'customer', 'deal', 'due_date', 'priority', 'status']
    list_filter = ['status', 'priority', 'due_date']
    search_fields = ['title', 'customer__name', 'deal__title', 'uuid']
    autocomplete_fields = ['customer', 'deal']
    readonly_fields = ['uuid', 'created_at', 'updated_at']
