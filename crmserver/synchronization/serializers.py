from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=4096, trim_whitespace=False, write_only=True)


class ChangeSerializer(serializers.Serializer):
    entity = serializers.ChoiceField(choices=['customers', 'deals', 'tasks'])
    uuid = serializers.UUIDField()
    updated_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField(required=False)
    deleted = serializers.BooleanField(default=False)
    fields = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        if attrs['updated_at'] > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError('Время изменения в будущем. Проверьте часы компьютера.')
        if not attrs['deleted'] and 'created_at' not in attrs:
            raise serializers.ValidationError('Не указано время создания.')
        if attrs.get('created_at', attrs['updated_at']) > attrs['updated_at']:
            raise serializers.ValidationError('Время изменения раньше времени создания.')
        return attrs


class ExchangeSerializer(serializers.Serializer):
    organization = serializers.UUIDField()
    changes = ChangeSerializer(many=True, max_length=10000)

    def validate_changes(self, changes):
        keys = [(row['entity'], row['uuid']) for row in changes]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError('UUID повторяется в пакете синхронизации.')
        return changes
