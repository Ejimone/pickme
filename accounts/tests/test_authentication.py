import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


class TestClerkJWTAuthentication:
    def _authenticate(self, token):
        """Run the auth class directly against a fake request."""
        from rest_framework.test import APIRequestFactory

        from accounts.authentication import ClerkJWTAuthentication

        request = APIRequestFactory().get(
            "/", HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        return ClerkJWTAuthentication().authenticate(request)

    def test_valid_token_jit_provisions_user(self, make_token):
        token = make_token(sub="user_abc123")
        assert not User.objects.filter(clerk_user_id="user_abc123").exists()

        user, claims = self._authenticate(token)

        assert user.clerk_user_id == "user_abc123"
        assert claims["sub"] == "user_abc123"
        assert User.objects.filter(clerk_user_id="user_abc123").count() == 1

    def test_valid_token_reuses_existing_user(self, make_token):
        existing = User.objects.create_user(
            email="p@example.com", clerk_user_id="user_abc123"
        )
        token = make_token(sub="user_abc123")

        user, _ = self._authenticate(token)

        assert user.pk == existing.pk
        assert User.objects.count() == 1

    def test_expired_token_rejected(self, make_token):
        from rest_framework.exceptions import AuthenticationFailed

        token = make_token(exp_offset=-60)
        with pytest.raises(AuthenticationFailed):
            self._authenticate(token)

    def test_wrong_issuer_rejected(self, make_token):
        from rest_framework.exceptions import AuthenticationFailed

        token = make_token(issuer="https://evil.example.com")
        with pytest.raises(AuthenticationFailed):
            self._authenticate(token)

    def test_garbage_token_rejected(self, mock_jwks):
        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed):
            self._authenticate("not-a-jwt")

    def test_disallowed_azp_rejected(self, make_token, clerk_settings):
        from rest_framework.exceptions import AuthenticationFailed

        clerk_settings.CLERK_AUTHORIZED_PARTIES = ["https://app.example.com"]
        token = make_token(azp="https://evil.example.com")
        with pytest.raises(AuthenticationFailed):
            self._authenticate(token)

    def test_no_header_returns_none(self):
        from rest_framework.test import APIRequestFactory

        from accounts.authentication import ClerkJWTAuthentication

        request = APIRequestFactory().get("/")
        assert ClerkJWTAuthentication().authenticate(request) is None
