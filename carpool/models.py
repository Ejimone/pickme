import secrets
import uuid

from django.conf import settings
from django.db import models


def generate_invite_code():
    # 8 chars, unambiguous alphabet, ~40 bits — plenty for group joining
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class CarpoolGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="carpool_groups"
    )
    name = models.CharField(max_length=255)
    invite_code = models.CharField(
        max_length=16, unique=True, default=generate_invite_code
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="carpool_groups_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "carpool_groups"

    def __str__(self):
        return self.name


class CarpoolGroupMember(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin"
        MEMBER = "member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    carpool_group = models.ForeignKey(
        CarpoolGroup, on_delete=models.CASCADE, related_name="members"
    )
    family = models.ForeignKey(
        "families.Family",
        on_delete=models.CASCADE,
        related_name="carpool_memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "carpool_group_members"
        constraints = [
            models.UniqueConstraint(
                fields=["carpool_group", "family"], name="unique_group_family"
            )
        ]

    def __str__(self):
        return f"{self.family} in {self.carpool_group} ({self.role})"


class CarpoolRotationRule(models.Model):
    class RotationType(models.TextChoices):
        ROUND_ROBIN = "round_robin"
        WEIGHTED = "weighted"
        MANUAL_ONLY = "manual_only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    carpool_group = models.OneToOneField(
        CarpoolGroup, on_delete=models.CASCADE, related_name="rotation_rule"
    )
    rotation_type = models.CharField(max_length=20, choices=RotationType.choices)
    # Weekdays (0=Monday … 6=Sunday) the rotation covers, e.g. [0,1,2,3,4]
    cycle_days = models.JSONField()
    start_date = models.DateField()  # anchor for the rotation order
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carpool_rotation_rules"

    def __str__(self):
        return f"{self.carpool_group}: {self.rotation_type}"


class CarpoolRotationOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rotation_rule = models.ForeignKey(
        CarpoolRotationRule, on_delete=models.CASCADE, related_name="order_entries"
    )
    family = models.ForeignKey(
        "families.Family",
        on_delete=models.CASCADE,
        related_name="rotation_positions",
    )
    position = models.IntegerField()
    weight = models.IntegerField(default=1)  # weighted type: turns per cycle

    class Meta:
        db_table = "carpool_rotation_order"
        constraints = [
            models.UniqueConstraint(
                fields=["rotation_rule", "position"], name="unique_rule_position"
            )
        ]

    def __str__(self):
        return f"#{self.position} {self.family} (w{self.weight})"


class CarpoolAssignment(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested"
        CONFIRMED = "confirmed"
        SWAP_PENDING = "swap_pending"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    carpool_group = models.ForeignKey(
        CarpoolGroup, on_delete=models.CASCADE, related_name="assignments"
    )
    date = models.DateField()
    driver_family = models.ForeignKey(
        "families.Family",
        on_delete=models.CASCADE,
        related_name="driving_assignments",
    )
    driver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="driving_assignments",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.SUGGESTED
    )
    is_auto_suggested = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carpool_assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["carpool_group", "date"], name="unique_group_date"
            )
        ]

    def __str__(self):
        return f"{self.carpool_group} {self.date} → {self.driver_family}"


class CarpoolSwapRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REJECTED = "rejected"
        EXPIRED = "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(
        CarpoolAssignment, on_delete=models.CASCADE, related_name="swap_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="swap_requests_made",
    )
    target_family = models.ForeignKey(
        "families.Family",
        on_delete=models.CASCADE,
        related_name="swap_requests_received",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "carpool_swap_requests"

    @property
    def carpool_group_id(self):
        # Lets core.permissions.IsCarpoolGroupMember scope swap requests.
        return self.assignment.carpool_group_id

    def __str__(self):
        return f"Swap {self.assignment} → {self.target_family} ({self.status})"
