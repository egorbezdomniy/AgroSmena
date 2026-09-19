from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from accounts.models import Membership, Organization


@transaction.atomic
def register_organization(form):
    organization = Organization.objects.create(name=form.cleaned_data['organization_name'])
    user = form.save()
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.ADMIN)
    return user


def lock_admin(organization_id, actor):
    # Serialize membership mutations to prevent concurrent removal of all admins.
    organization = get_object_or_404(Organization.objects.select_for_update(), pk=organization_id)
    if not Membership.objects.filter(organization=organization, user=actor,
                                     role=Membership.Role.ADMIN, user__is_active=True).exists():
        raise PermissionDenied('Управление пользователями доступно только администратору.')
    return organization


@transaction.atomic
def add_user(organization_id, actor, form):
    organization = lock_admin(organization_id, actor)
    user = form.save()
    return Membership.objects.create(organization=organization, user=user, role=form.cleaned_data['role'])


@transaction.atomic
def change_membership(organization_id, actor, membership_id, *, role=None, remove=False):
    organization = lock_admin(organization_id, actor)
    member = get_object_or_404(Membership, organization=organization, pk=membership_id)
    if not remove and role not in Membership.Role.values:
        raise ValidationError('Неизвестная роль.')
    if member.role == Membership.Role.ADMIN and (remove or role != Membership.Role.ADMIN):
        others = organization.memberships.filter(role=Membership.Role.ADMIN, user__is_active=True).exclude(pk=member.pk)
        if not others.exists():
            raise ValidationError('Нельзя удалить или понизить последнего администратора организации.')
    if remove:
        # Keep the account; subsequent requests lose CRM access immediately.
        member.delete()
    else:
        member.role = role
        member.save(update_fields=['role', 'updated_at'])
