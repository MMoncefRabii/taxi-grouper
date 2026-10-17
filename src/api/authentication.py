"""Interim API-key authentication for service endpoints."""

import hmac
import os

from starlette.responses import JSONResponse


API_KEY_ENV_VAR = "TAXI_GROUPER_API_KEY"
MIN_API_KEY_LENGTH = 32
PUBLIC_ENDPOINTS = {
    ("GET", "/health"),
    ("GET", "/api/auth/login-url"),
    ("GET", "/auth/callback"),
}


class ApiKeyAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"].upper()
        path = scope["path"]
        if method == "OPTIONS" or (method, path) in PUBLIC_ENDPOINTS:
            await self.app(scope, receive, send)
            return

        expected_key = os.getenv(API_KEY_ENV_VAR)
        if not expected_key or len(expected_key) < MIN_API_KEY_LENGTH:
            response = JSONResponse(
                status_code=503,
                content={"detail": "Service authentication is not configured."},
            )
            await response(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, separator, supplied_key = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not supplied_key
            or not hmac.compare_digest(supplied_key, expected_key)
        ):
            response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
