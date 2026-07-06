import uuid

from django.conf import settings
from django.db import models


class Family(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # users are deactivated, never hard-deleted
        related_name="families_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "families"
        verbose_name_plural = "families"

    def __str__(self):
        return self.name


class FamilyMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"
        MEMBER = "member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(
        Family, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "family_members"
        constraints = [
            models.UniqueConstraint(
                fields=["family", "user"], name="unique_family_user"
            )
        ]

    def __str__(self):
        return f"{self.user} in {self.family} ({self.role})"


class FamilyInvite(models.Model):
    """Pending email invite to join a family.

    Not in DATABASE-SCHEMA.md — required by the Stage 1 invite flow;
    see DECISIONS.md.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REVOKED = "revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(
        Family, on_delete=models.CASCADE, related_name="invites"
    )
    email = models.EmailField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_invites_sent",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "family_invites"

    def __str__(self):
        return f"Invite {self.email} → {self.family} ({self.status})"


class Child(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(
        Family, on_delete=models.CASCADE, related_name="children"
    )
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    full_name = models.CharField(max_length=255)
    date_of_birth = models.DateField(null=True, blank=True)
    grade = models.CharField(max_length=32, null=True, blank=True)
    photo_url = models.URLField(null=True, blank=True)
    color_tag = models.CharField(max_length=9, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)  # soft-delete flag
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "children"
        verbose_name_plural = "children"

    def __str__(self):
        return self.full_name
