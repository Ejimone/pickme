from rest_framework import serializers

from accounts.models import User


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "email", "avatar_url"]
        read_only_fields = fields
