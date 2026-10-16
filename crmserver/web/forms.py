from decimal import Decimal

from django import forms

from customers.models import Customer
from deals.models import Deal
from tasks.models import Task
from accounts.models import Membership


class MembershipChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, membership):
        name = membership.user.get_full_name().strip()
        return f'{name} · {membership.user.username}' if name else membership.user.username


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.instance.organization = organization
        for name in ('customer', 'deal'):
            if name in self.fields:
                field = self.fields[name]
                field.queryset = (field.queryset.filter(organization=organization)
                                  if organization is not None else field.queryset.none())
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['rows'] = 4
            if field.required:
                field.widget.attrs['aria-required'] = 'true'
            field.widget.attrs['aria-describedby'] = f'id_{name}_help id_{name}_errors'


class CustomerForm(StyledModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'company_name', 'phone', 'email', 'telegram', 'position', 'notes']
        widgets = {'phone': forms.TextInput(attrs={'type': 'tel'})}


class DealForm(StyledModelForm):
    class Meta:
        model = Deal
        fields = ['title', 'customer', 'amount', 'stage', 'expected_close_date', 'description']
        labels = {'customer': 'Клиент'}
        widgets = {
            'expected_close_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'Сумма в ₽'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount'].required = False
        self.fields['amount'].widget.attrs.pop('aria-required', None)
        if not self.instance.pk:
            self.initial['amount'] = None

    def clean_amount(self):
        return self.cleaned_data['amount'] if self.cleaned_data['amount'] is not None else Decimal('0.00')


class TaskForm(StyledModelForm):
    assignees = MembershipChoiceField(
        queryset=Membership.objects.none(), required=False, label='Сотрудники',
        help_text='Никого не выбирайте, чтобы задача отображалась у всех сотрудников.',
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Task
        fields = ['title', 'description', 'customer', 'deal', 'due_date', 'priority', 'status', 'assignees']
        labels = {'customer': 'Клиент', 'deal': 'Сделка'}
        widgets = {'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.instance.organization if self.instance.organization_id else None
        self.fields['assignees'].queryset = (Membership.objects.filter(
            organization=organization, user__is_active=True).select_related('user')
            if organization else Membership.objects.none())
        self.fields['deal'].queryset = self.fields['deal'].queryset.select_related('customer')
        self.fields['deal'].help_text = 'Если выбран клиент, сделка должна принадлежать ему.'
