import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, clerk_user_id, **extra_fields):
        if not clerk_user_id:
            raise ValueError("clerk_user_id is required")
        user = self.model(
            email=self.normalize_email(email),
            clerk_user_id=clerk_user_id,
            **extra_fields,
        )
        user.set_unusable_password()  # Clerk owns credentials
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        # Local admin access only (django admin); not a Clerk-backed account.
        extra_fields.setdefault("clerk_user_id", f"local_admin_{uuid.uuid4().hex}")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """Local mirror of a Clerk user (DATABASE-SCHEMA.md §1).

    Synced primarily via Clerk webhooks; JIT-provisioned on first
    authenticated request as a fallback.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clerk_user_id = models.CharField(max_length=255, unique=True, db_index=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email
