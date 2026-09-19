"""Read-only public release catalog. Contains no customer/organization data."""
import json
import logging
import re
from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class VersionField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        pattern = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
        match = re.fullmatch(pattern, value)
        if not match or any(p.isdigit() and len(p) > 1 and p[0] == '0' for p in (match.group(4) or '').split('.')):
            raise serializers.ValidationError('Expected SemVer')
        return value


class PatchSerializer(serializers.Serializer):
    from_version = VersionField()
    to_version = VersionField()
    url = serializers.URLField()
    sha256 = serializers.RegexField(r'^[a-f0-9]{64}$')
    mandatory = serializers.BooleanField(default=False)
    release_notes = serializers.CharField(default='', allow_blank=True)

    def validate_url(self, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.fragment:
            raise serializers.ValidationError('HTTPS URL required')
        return value


class CatalogSerializer(serializers.Serializer):
    latest_version = VersionField()
    mandatory = serializers.BooleanField(default=False)
    release_notes = serializers.CharField(default='', allow_blank=True)
    patches = PatchSerializer(many=True)

    def validate(self, data):
        def key(version):
            base, _, pre = version.split('+')[0].partition('-')
            return (*map(int, base.split('.')), not bool(pre),
                    tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split('.') if p))
        latest, edges = key(data['latest_version']), set()
        for patch in data['patches']:
            edge = (key(patch['from_version']), key(patch['to_version']))
            if edge[0] >= edge[1] or edge[1] > latest or edge in edges:
                raise serializers.ValidationError('Invalid/duplicate patch version edge')
            edges.add(edge)
        return data


class AppUpdateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            catalog = json.loads(Path(settings.APP_UPDATE_CATALOG).read_text(encoding='utf-8'))
            serializer = CatalogSerializer(data=catalog)
            serializer.is_valid(raise_exception=True)
        except (OSError, ValueError, serializers.ValidationError):
            logging.getLogger(__name__).exception('Invalid/unavailable app release catalog')
            return Response({'detail': 'Каталог обновлений временно недоступен.'}, status=503)
        return Response(serializer.data, headers={'Cache-Control': 'no-store'})
