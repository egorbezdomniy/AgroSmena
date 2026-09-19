from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView, UpdateView

from accounts.access import OrganizationRequiredMixin
from accounts.forms import AddUserForm, LoginForm, ProfileForm, RegisterForm, RoleForm
from accounts.models import Membership
from accounts.services import add_user, change_membership, register_organization


class SignInView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


class RegisterView(FormView):
    template_name = 'accounts/register.html'
    form_class = RegisterForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('accounts:profile')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            user = register_organization(form)
        except IntegrityError:
            form.add_error(None, 'Не удалось создать аккаунт. Проверьте, свободен ли логин.')
            return self.form_invalid(form)
        login(self.request, user)
        return redirect('web:dashboard')


class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = 'accounts/profile.html'
    form_class = ProfileForm
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Профиль сохранён.')
        return super().form_valid(form)


class AdminRequiredMixin(OrganizationRequiredMixin):
    def check_membership(self):
        if self.membership.role != Membership.Role.ADMIN:
            raise PermissionDenied('Управление пользователями доступно только администратору.')


class UsersView(AdminRequiredMixin, ListView):
    template_name = 'accounts/users.html'
    context_object_name = 'members'

    def get_queryset(self):
        return Membership.objects.filter(organization=self.organization).select_related('user')


class AddUserView(AdminRequiredMixin, FormView):
    template_name = 'accounts/member_form.html'
    form_class = AddUserForm
    extra_context = {'page_title': 'Добавить пользователя'}

    def form_valid(self, form):
        try:
            add_user(self.organization.pk, self.request.user, form)
        except IntegrityError:
            form.add_error(None, 'Не удалось создать пользователя. Проверьте логин.')
            return self.form_invalid(form)
        messages.success(self.request, 'Пользователь добавлен.')
        return redirect('accounts:users')


class MemberView(AdminRequiredMixin, View):
    def get_member(self):
        return get_object_or_404(Membership.objects.select_related('user'),
                                 organization=self.organization, pk=self.kwargs['pk'])


class EditRoleView(MemberView):
    def get(self, request, *args, **kwargs):
        member = self.get_member()
        return render(request, 'accounts/member_form.html', {
            'page_title': f'Роль пользователя {member.user.username}', 'form': RoleForm(initial={'role': member.role})})

    def post(self, request, *args, **kwargs):
        member = self.get_member()
        form = RoleForm(request.POST)
        if form.is_valid():
            try:
                change_membership(self.organization.pk, request.user, member.pk, role=form.cleaned_data['role'])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Роль изменена.')
                return redirect('accounts:profile' if member.user_id == request.user.pk else 'accounts:users')
        return render(request, 'accounts/member_form.html', {'page_title': 'Изменить роль', 'form': form})


class RemoveUserView(MemberView):
    def get(self, request, *args, **kwargs):
        return render(request, 'accounts/member_delete.html', {'member': self.get_member()})

    def post(self, request, *args, **kwargs):
        member = self.get_member()
        try:
            change_membership(self.organization.pk, request.user, member.pk, remove=True)
        except ValidationError as error:
            return render(request, 'accounts/member_delete.html', {'member': member, 'error': error.messages[0]})
        messages.success(request, 'Пользователь удалён из организации. Записи CRM сохранены.')
        return redirect('accounts:profile' if member.user_id == request.user.pk else 'accounts:users')
