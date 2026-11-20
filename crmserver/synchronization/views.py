from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.access import membership_for
from accounts.models import Membership
from accounts.permissions import HasOrganization
from crmserver.observability import sync_exception, sync_phase, sync_record_counts
from .auth import SyncAuthentication, issue_token
from .serializers import ExchangeSerializer, LoginSerializer
from .services import exchange


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'sync_login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        membership = membership_for(user) if user else None
        if not membership:
            return Response({'detail': 'Неверный логин/пароль или нет доступа к организации.'}, status=401)
        members = Membership.objects.filter(
            organization=membership.organization, user__is_active=True).select_related('user')
        return Response({'token': issue_token(user, membership), 'organization': str(membership.organization.uuid),
                         'organization_name': membership.organization.name, 'username': user.username,
                         'members': [{'username': item.user.username,
                                      'name': item.user.get_full_name().strip() or item.user.username}
                                     for item in members]})


class ExchangeView(APIView):
    authentication_classes = [SyncAuthentication]
    permission_classes = [IsAuthenticated, HasOrganization]

    def handle_exception(self, exc):
        sync_exception(self.request, exc)
        return super().handle_exception(exc)

    def post(self, request):
        with sync_phase(request, 'input_validation_ms'):
            serializer = ExchangeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
        # Only inspect validated records; never access the raw body again.
        sync_record_counts(request, 'incoming', serializer.validated_data['changes'])
        return Response(exchange(request, serializer.validated_data))
