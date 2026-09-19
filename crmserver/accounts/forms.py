from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from accounts.models import Membership


class StyledFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LoginForm(StyledFieldsMixin, AuthenticationForm):
    pass


class RegisterForm(StyledFieldsMixin, UserCreationForm):
    organization_name = forms.CharField(label='Название организации', max_length=200)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email']


class AddUserForm(StyledFieldsMixin, UserCreationForm):
    role = forms.ChoiceField(label='Роль', choices=Membership.Role.choices,
                            initial=Membership.Role.MANAGER)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email']


class RoleForm(StyledFieldsMixin, forms.Form):
    role = forms.ChoiceField(label='Роль', choices=Membership.Role.choices)


class ProfileForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']
