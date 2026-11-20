from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from tasks.models import Task, lock_task_assignees


class TaskAdminForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('organization') and 'assignees' in cleaned:
            try:
                # Admin POST validation already runs inside changeform's atomic.
                # Keep inactive assignments supported by the existing admin.
                cleaned['assignees'] = lock_task_assignees(
                    cleaned['organization'].pk, cleaned['assignees'])
            except ValidationError as exc:
                self.add_error('assignees', exc)
        return cleaned


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskAdminForm
    list_display = ['title', 'customer', 'deal', 'due_date', 'priority', 'status']
    list_filter = ['status', 'priority', 'due_date']
    search_fields = ['title', 'customer__name', 'deal__title', 'uuid']
    autocomplete_fields = ['customer', 'deal']
    filter_horizontal = ['assignees']
    readonly_fields = ['uuid', 'created_at', 'updated_at']
