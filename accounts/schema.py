"""drf-spectacular extensions.

Registers the Clerk Bearer scheme so the exported OpenAPI schema (and the
Swagger "Authorize" button) documents `Authorization: Bearer <clerk jwt>`.
Imported from AccountsConfig.ready() so it's loaded at schema-generation time.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ClerkJWTScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.ClerkJWTAuthentication"
    name = "ClerkJWT"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Clerk session JWT. In Expo: `await getToken()`.",
        }
