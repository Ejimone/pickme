import pytest
from rest_framework import exceptions
from rest_framework.test import APIClient, APIRequestFactory

from core.exceptions import envelope_exception_handler

pytestmark = pytest.mark.django_db


def _context():
    return {"view": None, "request": APIRequestFactory().get("/")}


def test_not_found_envelope():
    resp = envelope_exception_handler(
        exceptions.NotFound("Carpool group not found"), _context()
    )
    assert resp.status_code == 404
    assert resp.data == {
        "error": {
            "code": "not_found",
            "message": "Carpool group not found",
            "details": {},
        }
    }


def test_validation_error_envelope_carries_field_details():
    exc = exceptions.ValidationError({"name": ["This field is required."]})
    resp = envelope_exception_handler(exc, _context())
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "validation_error"
    assert "name" in resp.data["error"]["details"]


def test_unsigned_webhook_returns_envelope_shape():
    resp = APIClient().post("/api/v1/webhooks/clerk/")
    body = resp.json()
    assert {"code", "message", "details"} <= set(body["error"].keys())
