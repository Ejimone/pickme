"""DRF exception handler producing the API-DESIGN.md error envelope:

{"error": {"code": "...", "message": "...", "details": {...}}}
"""

from rest_framework.views import exception_handler as drf_exception_handler


def envelope_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # non-API exception → Django's 500 handling

    detail = response.data
    code = getattr(getattr(exc, "detail", None), "code", None) or getattr(
        exc, "default_code", "error"
    )
    details = {}

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
    elif isinstance(detail, dict):
        # Validation errors: field → [messages]
        code = "validation_error"
        message = "Invalid input."
        details = detail
    elif isinstance(detail, list):
        code = "validation_error"
        message = "Invalid input."
        details = {"non_field_errors": detail}
    else:
        message = str(detail)

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
