from rest_framework import serializers

from accounts.serializers import UserSummarySerializer
from families.models import Activity, Child, Family, FamilyInvite, FamilyMember


class FamilySerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Family
        fields = ["id", "name", "created_by", "created_at", "member_count"]
        read_only_fields = ["id", "created_by", "created_at"]


class FamilyMemberSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = FamilyMember
        fields = ["id", "user", "role", "joined_at"]
        read_only_fields = fields


class FamilyInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilyInvite
        fields = ["id", "family", "email", "status", "created_at"]
        read_only_fields = ["id", "family", "status", "created_at"]


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.UUIDField()


class ChildSerializer(serializers.ModelSerializer):
    class Meta:
        model = Child
        fields = [
            "id",
            "family",
            "school",
            "full_name",
            "date_of_birth",
            "grade",
            "photo_url",
            "color_tag",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_family(self, family):
        user = self.context["request"].user
        if not family.members.filter(user=user).exists():
            raise serializers.ValidationError(
                "You are not a member of this family."
            )
        return family


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = [
            "id",
            "child",
            "name",
            "day_of_week",
            "start_time",
            "end_time",
            "location_name",
            "location_lat",
            "location_lng",
            "created_at",
        ]
        read_only_fields = ["id", "child", "created_at"]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": ["end_time must be after start_time."]}
            )
        return attrs
