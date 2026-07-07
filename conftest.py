import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

TEST_KID = "test-key-1"


@pytest.fixture(scope="session")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="session", autouse=True)
def _celery_eager():
    """Run Celery tasks inline in tests so `.delay()` never touches a broker
    (the app's real broker is a remote TLS Redis)."""
    from config.celery import app

    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = False
    yield


@pytest.fixture(autouse=True)
def _in_memory_channels(settings):
    """Keep every test off the real (remote) channel layer — notification and
    trip/chat broadcasts run against an in-process layer instead of Redis."""
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }
    from channels.layers import channel_layers

    channel_layers.backends = {}
    yield
    channel_layers.backends = {}


@pytest.fixture(autouse=True)
def _no_push_dispatch(monkeypatch):
    """The Notification post_save signal queues `send_push_notification.delay`
    on commit. Make it a no-op everywhere so transaction=True consumer tests
    never run the push task inline (eager) or hit the broker. Tests that need
    the push path call the task function directly."""
    from notifications.tasks import send_push_notification

    monkeypatch.setattr(send_push_notification, "delay", lambda *a, **k: None)


@pytest.fixture
def clerk_settings(settings):
    settings.CLERK_ISSUER = "https://test.clerk.accounts.dev"
    settings.CLERK_JWKS_URL = (
        "https://test.clerk.accounts.dev/.well-known/jwks.json"
    )
    settings.CLERK_AUTHORIZED_PARTIES = []
    # Dummy test signing secret — base64("testsecrettestsecret"), NOT a real
    # credential. Svix requires a valid base64 body after the whsec_ prefix.
    settings.CLERK_WEBHOOK_SIGNING_SECRET = "whsec_dGVzdHNlY3JldHRlc3RzZWNyZXQ="
    return settings


@pytest.fixture
def mock_jwks(rsa_keypair, clerk_settings, monkeypatch):
    """Point the JWKS client at our test public key instead of the network."""
    private_key, public_key = rsa_keypair

    class FakeSigningKey:
        key = public_key

    class FakeJWKSClient:
        uri = clerk_settings.CLERK_JWKS_URL

        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey()

    from accounts import authentication

    monkeypatch.setattr(authentication, "get_jwks_client", lambda: FakeJWKSClient())
    return private_key


@pytest.fixture
def make_token(mock_jwks, clerk_settings):
    """Factory producing signed Clerk-style session JWTs."""

    def _make(sub=None, issuer=None, exp_offset=300, **extra_claims):
        now = int(time.time())
        claims = {
            "sub": sub or f"user_{uuid.uuid4().hex[:12]}",
            "iss": issuer or clerk_settings.CLERK_ISSUER,
            "iat": now,
            "exp": now + exp_offset,
            **extra_claims,
        }
        return jwt.encode(
            claims, mock_jwks, algorithm="RS256", headers={"kid": TEST_KID}
        )

    return _make
