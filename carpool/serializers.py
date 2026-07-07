from rest_framework import serializers

from carpool.models import (
    CarpoolAssignment,
    CarpoolGroup,
    CarpoolGroupInvite,
    CarpoolGroupMember,
    CarpoolRotationOrder,
    CarpoolRotationRule,
    CarpoolSwapRequest,
)
from families.models import Family


class CarpoolGroupSerializer(serializers.ModelSerializer):
    family = serializers.PrimaryKeyRelatedField(
        queryset=Family.objects.all(), write_only=True
    )  # the creating user's family, becomes the first admin member
    member_count = serializers.SerializerMethodField()
    school_name = serializers.CharField(source="school.name", read_only=True)

    class Meta:
        model = CarpoolGroup
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "invite_code",
            "member_count",
            "created_by",
            "created_at",
            "family",
        ]
        read_only_fields = ["id", "invite_code", "created_by", "created_at"]

    def get_member_count(self, obj):
        return obj.members.count()

    def validate_family(self, family):
        user = self.context["request"].user
        if not family.members.filter(user=user).exists():
            raise serializers.ValidationError(
                "You are not a member of this family."
            )
        return family


class CarpoolGroupInviteSerializer(serializers.ModelSerializer):
    invite_code = serializers.CharField(
        source="group.invite_code", read_only=True
    )

    class Meta:
        model = CarpoolGroupInvite
        fields = ["id", "group", "email", "status", "invite_code", "created_at"]
        read_only_fields = fields


class CarpoolInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CarpoolInviteAcceptSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    family = serializers.PrimaryKeyRelatedField(queryset=Family.objects.all())

    def validate_family(self, family):
        user = self.context["request"].user
        if not family.members.filter(user=user).exists():
            raise serializers.ValidationError(
                "You are not a member of this family."
            )
        return family


class CarpoolGroupMemberSerializer(serializers.ModelSerializer):
    family_name = serializers.CharField(source="family.name", read_only=True)

    class Meta:
        model = CarpoolGroupMember
        fields = ["id", "family", "family_name", "role", "joined_at"]
        read_only_fields = fields


class JoinGroupSerializer(serializers.Serializer):
    invite_code = serializers.CharField()
    family = serializers.PrimaryKeyRelatedField(queryset=Family.objects.all())

    def validate_family(self, family):
        user = self.context["request"].user
        if not family.members.filter(user=user).exists():
            raise serializers.ValidationError(
                "You are not a member of this family."
            )
        return family


class RotationOrderEntrySerializer(serializers.ModelSerializer):
    family_name = serializers.CharField(source="family.name", read_only=True)

    class Meta:
        model = CarpoolRotationOrder
        fields = ["family", "family_name", "position", "weight"]

    def validate_weight(self, value):
        if value < 1:
            raise serializers.ValidationError("weight must be >= 1.")
        return value


class RotationRuleSerializer(serializers.ModelSerializer):
    order = RotationOrderEntrySerializer(
        source="order_entries", many=True, required=True
    )

    class Meta:
        model = CarpoolRotationRule
        fields = [
            "id",
            "rotation_type",
            "cycle_days",
            "start_date",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_cycle_days(self, value):
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(d, int) and 0 <= d <= 6 for d in value)
            or len(set(value)) != len(value)
        ):
            raise serializers.ValidationError(
                "cycle_days must be a non-empty list of unique weekday ints 0–6."
            )
        return value

    def validate(self, attrs):
        entries = attrs.get("order_entries", [])
        group = self.context["carpool_group"]
        if attrs.get("rotation_type") != CarpoolRotationRule.RotationType.MANUAL_ONLY:
            if not entries:
                raise serializers.ValidationError(
                    {"order": ["At least one rotation entry is required."]}
                )
        positions = [e["position"] for e in entries]
        if len(set(positions)) != len(positions):
            raise serializers.ValidationError(
                {"order": ["Positions must be unique."]}
            )
        member_family_ids = set(
            group.members.values_list("family_id", flat=True)
        )
        for entry in entries:
            if entry["family"].id not in member_family_ids:
                raise serializers.ValidationError(
                    {"order": [f"{entry['family']} is not a member of this group."]}
                )
        return attrs

    def save_for_group(self, group):
        """Create/replace the group's rule + order atomically."""
        entries = self.validated_data.pop("order_entries", [])
        rule, _ = CarpoolRotationRule.objects.update_or_create(
            carpool_group=group, defaults=self.validated_data
        )
        rule.order_entries.all().delete()
        CarpoolRotationOrder.objects.bulk_create(
            [CarpoolRotationOrder(rotation_rule=rule, **entry) for entry in entries]
        )
        return rule


class AssignmentSerializer(serializers.ModelSerializer):
    driver_family_name = serializers.CharField(
        source="driver_family.name", read_only=True
    )

    class Meta:
        model = CarpoolAssignment
        fields = [
            "id",
            "carpool_group",
            "date",
            "driver_family",
            "driver_family_name",
            "driver_user",
            "status",
            "is_auto_suggested",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "carpool_group",
            "date",
            "status",
            "is_auto_suggested",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        assignment = self.instance
        driver_family = attrs.get("driver_family")
        if driver_family is not None:
            is_member = assignment.carpool_group.members.filter(
                family=driver_family
            ).exists()
            if not is_member:
                raise serializers.ValidationError(
                    {"driver_family": ["Family is not a member of this group."]}
                )
        driver_user = attrs.get("driver_user")
        if driver_user is not None:
            family = driver_family or assignment.driver_family
            if not family.members.filter(user=driver_user).exists():
                raise serializers.ValidationError(
                    {"driver_user": ["User is not a member of the driver family."]}
                )
        return attrs


class GenerateAssignmentsSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def to_internal_value(self, data):
        # API-DESIGN.md uses {"from": ..., "to": ...}
        remapped = {
            "date_from": data.get("from", data.get("date_from")),
            "date_to": data.get("to", data.get("date_to")),
        }
        return super().to_internal_value(remapped)

    def validate(self, attrs):
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError("'from' must be on or before 'to'.")
        if (attrs["date_to"] - attrs["date_from"]).days > 366:
            raise serializers.ValidationError("Range too large (max one year).")
        return attrs


class SwapRequestSerializer(serializers.ModelSerializer):
    target_family_name = serializers.CharField(
        source="target_family.name", read_only=True
    )

    class Meta:
        model = CarpoolSwapRequest
        fields = [
            "id",
            "assignment",
            "requested_by",
            "target_family",
            "target_family_name",
            "status",
            "reason",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "assignment",
            "requested_by",
            "status",
            "created_at",
            "resolved_at",
        ]


class SwapRespondSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "reject"])
