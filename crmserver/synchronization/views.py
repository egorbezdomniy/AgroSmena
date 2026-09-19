from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.access import membership_for
from accounts.permissions import HasOrganization
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
        return Response({'token': issue_token(user, membership), 'organization': str(membership.organization.uuid),
                         'organization_name': membership.organization.name, 'username': user.username})


class ExchangeView(APIView):
    authentication_classes = [SyncAuthentication]
    permission_classes = [IsAuthenticated, HasOrganization]

    def post(self, request):
        serializer = ExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(exchange(request, serializer.validated_data))
